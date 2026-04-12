"""
OpenAPI Schema Compiler

Transforms OpenAPI 3.x specifications into native Delfhos format:
  - ToolCapability + ToolActionSpec for the prefilter registry
  - COMPRESSED_API_DOCS for code generation prompts
  - Python function signatures from JSON Schema parameters

Cache system: compiled manifests are saved to ~/delfhos/api_cache/{hash}/
so the spec only needs to be parsed once.

No LLM required — pure deterministic schema transformation.
"""

import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from delfhos.errors import ConnectionConfigurationError


# JSON Schema type → LLM-friendly type annotation
_TYPE_MAP = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
}

CACHE_DIR = Path.home() / "delfhos" / "api_cache"

MAX_ENDPOINTS = None  # No cap — all endpoints in the spec are compiled.

# Use threads for larger specs where schema transformation dominates startup time.
API_PARALLEL_THRESHOLD = 40
API_PROGRESS_EVERY = 25


def _log_compile(message: str, details: str) -> None:
    """Best-effort compile telemetry for CLI visibility."""
    try:
        from cortex._engine.utils.console import console
        console.tool(message, details)
    except Exception:
        return


def _load_spec(source: str) -> Dict[str, Any]:
    """Load an OpenAPI spec from a URL or local file path.

    Supports JSON and YAML formats. For URLs, fetches via httpx.
    """
    text: str

    if source.startswith(("http://", "https://")):
        import httpx
        resp = httpx.get(source, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        text = resp.text
    else:
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise ConnectionConfigurationError(
                tool_name="api",
                detail=f"OpenAPI spec file not found: {path}",
            )
        text = path.read_text(encoding="utf-8")

    # Try JSON first, fall back to YAML
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        raise ConnectionConfigurationError(
            tool_name="api",
            detail=(
                "OpenAPI spec appears to be YAML but PyYAML is required to parse it. "
                "Install it with: pip install pyyaml"
            ),
        )
    except Exception as exc:
        raise ConnectionConfigurationError(
            tool_name="api",
            detail=f"Failed to parse OpenAPI spec: {exc}",
        )


def _resolve_ref(spec: Dict[str, Any], ref: str) -> Dict[str, Any]:
    """Resolve a $ref pointer like '#/components/schemas/Pet'."""
    if not ref.startswith("#/"):
        return {}
    parts = ref.lstrip("#/").split("/")
    node = spec
    for part in parts:
        node = node.get(part, {})
        if not isinstance(node, dict):
            return {}
    return node


def _deep_resolve(spec: Dict[str, Any], schema: Any, depth: int = 0) -> Any:
    """Recursively resolve $ref pointers in a schema, up to a depth limit."""
    if depth > 8 or not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        resolved = _resolve_ref(spec, schema["$ref"])
        return _deep_resolve(spec, resolved, depth + 1)
    result = {}
    for key, value in schema.items():
        if isinstance(value, dict):
            result[key] = _deep_resolve(spec, value, depth + 1)
        elif isinstance(value, list):
            result[key] = [
                _deep_resolve(spec, item, depth + 1) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def _infer_schema(data: Any, depth: int = 0, max_depth: int = 5) -> Dict[str, Any]:
    """Infer a JSON Schema from actual response data (no LLM needed)."""
    if depth > max_depth:
        return {"type": "object"}
    if data is None:
        return {"type": "null"}
    if isinstance(data, bool):
        return {"type": "boolean"}
    if isinstance(data, int):
        return {"type": "integer"}
    if isinstance(data, float):
        return {"type": "number"}
    if isinstance(data, str):
        return {"type": "string"}
    if isinstance(data, list):
        if not data:
            return {"type": "array"}
        return {"type": "array", "items": _infer_schema(data[0], depth + 1, max_depth)}
    if isinstance(data, dict):
        props = {}
        for k, v in data.items():
            props[k] = _infer_schema(v, depth + 1, max_depth)
        return {"type": "object", "properties": props}
    return {"type": "string"}


class OpenAPICompiler:
    """
    Compiles an OpenAPI 3.x specification into Delfhos-native tool_docs and registry entries.

    No LLM needed — pure deterministic schema transformation.
    """

    def __init__(self, tool_name: str, spec_source: str, base_url: Optional[str] = None, cache: bool = False):
        """
        Args:
            tool_name:   Delfhos tool name (e.g., "petstore", "stripe")
            spec_source: URL or file path to an OpenAPI 3.x JSON/YAML spec
            base_url:    Override for the API base URL. If None, extracted from
                         spec's ``servers[0].url``.
            cache:       Whether to read/write the disk cache.
        """
        self.tool_name = tool_name
        self.spec_source = spec_source
        self.base_url_override = base_url
        self.cache = cache
        self._cache_dir = CACHE_DIR / self._cache_key()
        self.manifest: Optional[Dict[str, Any]] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def compile(self, spec: Optional[Dict[str, Any]] = None, max_endpoints: Optional[int] = None) -> Dict[str, Any]:
        """Parse the OpenAPI spec and compile every operation into Delfhos format.

        Args:
            spec:          Pre-loaded spec dict. If None, loads from ``self.spec_source``.
            max_endpoints: Override for MAX_ENDPOINTS cap. Pass 0 for unlimited.

        Returns:
            Compiled manifest dict.
        """
        started = time.perf_counter()
        if spec is None:
            _log_compile("API COMPILER", f"{self.tool_name}: loading spec from {self.spec_source}")
            spec = _load_spec(self.spec_source)

        # Validate minimum spec structure
        if "paths" not in spec:
            raise ConnectionConfigurationError(
                tool_name="api",
                detail="OpenAPI spec has no 'paths' key. Ensure this is a valid OpenAPI 3.x document.",
            )

        # Extract base URL
        base_url = self.base_url_override
        if not base_url:
            servers = spec.get("servers", [])
            if servers and isinstance(servers[0], dict):
                base_url = servers[0].get("url", "")
            if not base_url:
                raise ConnectionConfigurationError(
                    tool_name="api",
                    detail=(
                        "No base URL found in spec's 'servers' field and no base_url= was provided. "
                        "Pass base_url='https://api.example.com' explicitly."
                    ),
                )

        # Strip trailing slash for clean path joining
        base_url = base_url.rstrip("/")

        limit = float("inf") if (max_endpoints is None or max_endpoints == 0) else max_endpoints

        operation_candidates: List[Tuple[int, str, str, Dict[str, Any]]] = []
        hit_limit = False

        for path, path_item in spec.get("paths", {}).items():
            if hit_limit:
                break
            if not isinstance(path_item, dict):
                continue
            for method in ("get", "post", "put", "patch", "delete", "head", "options"):
                operation = path_item.get(method)
                if not operation or not isinstance(operation, dict):
                    continue
                if len(operation_candidates) >= limit:
                    hit_limit = True
                    break
                operation_candidates.append((len(operation_candidates), method, path, operation))

        total_candidates = len(operation_candidates)
        use_parallel = total_candidates >= API_PARALLEL_THRESHOLD
        _log_compile(
            "API COMPILER",
            f"{self.tool_name}: compiling {total_candidates} endpoint(s) ({'parallel' if use_parallel else 'sequential'})",
        )

        compiled_indexed: List[Tuple[int, Dict[str, Any]]] = []
        completed = 0

        if use_parallel:
            max_workers = min(32, (os.cpu_count() or 4) + 4, total_candidates)
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_to_idx = {
                    pool.submit(self._compile_operation, spec, method, path, operation, base_url): idx
                    for idx, method, path, operation in operation_candidates
                }
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    compiled = future.result()
                    if compiled:
                        compiled_indexed.append((idx, compiled))
                    completed += 1
                    if completed % API_PROGRESS_EVERY == 0 or completed == total_candidates:
                        _log_compile(
                            "API COMPILER",
                            f"{self.tool_name}: compiled {completed}/{total_candidates} endpoint(s)",
                        )
        else:
            for idx, method, path, operation in operation_candidates:
                compiled = self._compile_operation(spec, method, path, operation, base_url)
                if compiled:
                    compiled_indexed.append((idx, compiled))
                completed += 1
                if completed % API_PROGRESS_EVERY == 0 or completed == total_candidates:
                    _log_compile(
                        "API COMPILER",
                        f"{self.tool_name}: compiled {completed}/{total_candidates} endpoint(s)",
                    )

        compiled_indexed.sort(key=lambda pair: pair[0])
        compiled_tools = [tool for _, tool in compiled_indexed]

        info = spec.get("info", {})
        self.manifest = {
            "spec_source": self.spec_source,
            "base_url": base_url,
            "compiled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "api_title": info.get("title", "unknown"),
            "api_version": info.get("version", "unknown"),
            "tool_name": self.tool_name,
            "tools": compiled_tools,
        }

        self._merge_sampled_schemas()
        self._save_cache()
        elapsed = time.perf_counter() - started
        _log_compile(
            "API COMPILER",
            f"{self.tool_name}: ready ({len(compiled_tools)} endpoint(s), {elapsed:.2f}s, hit_limit={hit_limit})",
        )
        return self.manifest

    def load_cache(self) -> Optional[Dict[str, Any]]:
        """Try to load a previously compiled manifest from cache."""
        if not self.cache:
            return None
        manifest_path = self._cache_dir / "manifest.json"
        if not manifest_path.exists():
            _log_compile("API CACHE", f"{self.tool_name}: miss")
            return None
        try:
            with open(manifest_path, "r") as f:
                self.manifest = json.load(f)
            _log_compile("API CACHE", f"{self.tool_name}: hit")
            self._merge_sampled_schemas()
            return self.manifest
        except (json.JSONDecodeError, OSError):
            _log_compile("API CACHE", f"{self.tool_name}: corrupted cache, recompiling")
            return None

    def get_capability(self, tools: Optional[List[Dict[str, Any]]] = None):
        """Build a ToolCapability from the compiled manifest.

        Returns:
            (ToolCapability, action_summaries_dict)
        """
        from cortex._engine.tools.tool_registry import ToolCapability, ToolActionSpec

        if not self.manifest:
            raise ConnectionConfigurationError(
                tool_name="api",
                detail="No compiled manifest. Call compile() or load_cache() first.",
            )

        actions = []
        summaries = {}

        source_tools = self.manifest["tools"] if tools is None else tools
        for tool in source_tools:
            action_name = tool["action_name"]
            actions.append(ToolActionSpec(
                action=action_name,
                description=tool["description"],
                parameters=tool["parameters"],
            ))
            summaries[action_name] = tool["summary"]

        capability = ToolCapability(
            tool_name=self.tool_name,
            actions=actions,
        )
        return capability, summaries

    def get_api_docs(self, tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, str]:
        """Build COMPRESSED_API_DOCS entries from the compiled manifest.

        Returns:
            Dict of "tool:action" → compressed API doc string
        """
        if not self.manifest:
            raise ConnectionConfigurationError(
                tool_name="api",
                detail="No compiled manifest. Call compile() or load_cache() first.",
            )
        docs = {}
        source_tools = self.manifest["tools"] if tools is None else tools
        for tool in source_tools:
            key = f"{self.tool_name}:{tool['action_name'].lower()}"
            docs[key] = tool["api_doc"]
        return docs

    def get_action_names(self) -> List[str]:
        """Get list of compiled action names from the manifest."""
        if not self.manifest:
            return []
        return [t["action_name"] for t in self.manifest["tools"]]

    # ── LLM Enrichment ────────────────────────────────────────────────────────

    def enrich(self, llm: str) -> Dict[str, Any]:
        """Use an LLM to improve endpoint descriptions and infer response schemas.

        Runs once per spec version. Results are baked into the manifest and cached
        so subsequent calls return immediately with zero token cost.

        Args:
            llm: Model identifier (e.g., "gemini-2.5-flash", "claude-sonnet-4-5-20241022").

        Returns:
            Dict with ``tokens_input``, ``tokens_output``, ``cost_usd``, ``cached``.
        """
        if not self.manifest:
            raise ConnectionConfigurationError(
                tool_name="api",
                detail="No compiled manifest. Call compile() or load_cache() first.",
            )

        # Already enriched — return cached result (zero cost)
        if self.manifest.get("enriched"):
            _log_compile("API ENRICH", f"{self.tool_name}: already enriched (cached) | 0 tokens | cost $0.000000")
            return {
                "tokens_input": 0, "tokens_output": 0,
                "cost_usd": 0.0, "cached": True,
                "model": self.manifest.get("enriched_with", llm),
                "endpoints_enriched": 0,
            }

        import asyncio
        from cortex._engine.internal.llm import llm_completion_async
        from cortex._engine.config.pricing import calculate_cost_usd

        tools = self.manifest["tools"]
        _log_compile("API ENRICH", f"{self.tool_name}: enriching {len(tools)} endpoint(s) with {llm}")

        # Build enrichment prompt with endpoint info
        endpoints_info = []
        for t in tools:
            endpoints_info.append({
                "func_name": t["func_name"],
                "method": t["method"],
                "path": t["path"],
                "description": t["description"],
                "parameters": [p["name"] for p in t.get("params_spec", [])],
                "response_hint": t.get("response_hint"),
            })

        prompt = (
            "Improve these REST API endpoint descriptions for an AI coding agent.\n\n"
            "For each endpoint:\n"
            "1. Write a clear, actionable description (1-2 sentences) explaining what the endpoint does and what data it returns\n"
            "2. If response_hint is null, \"obj\", or \"str\", infer the response structure using this compact format: "
            "{field:type,...} where type is str/int/num/bool/[inner]/null. Nested objects use {} again. "
            "If you cannot infer, set response_hint to null.\n\n"
            f"Endpoints:\n{json.dumps(endpoints_info, indent=2)}\n\n"
            "Respond with ONLY a JSON array (no markdown, no explanation):\n"
            '[{"func_name":"...","description":"...","response_hint":"..." or null}]'
        )
        system_message = "You are an API documentation expert. Be concise and precise. Output only valid JSON."

        started = time.perf_counter()

        # Run the LLM call synchronously (handle both sync and async contexts)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        coro = llm_completion_async(
            llm, prompt, system_message,
            temperature=0.0, max_tokens=4096, response_format="text",
        )
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                content, token_info = pool.submit(asyncio.run, coro).result()
        else:
            content, token_info = asyncio.run(coro)

        elapsed_ms = int((time.perf_counter() - started) * 1000)

        # Calculate cost
        input_tokens = token_info.get("input_tokens", 0)
        output_tokens = token_info.get("output_tokens", 0)
        cost_usd = calculate_cost_usd(llm, input_tokens, output_tokens)

        # Parse LLM response
        enriched_count = 0
        try:
            enriched = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            # Try to extract JSON array from response
            import re as _re
            match = _re.search(r'\[.*\]', content, _re.DOTALL)
            if match:
                try:
                    enriched = json.loads(match.group())
                except (json.JSONDecodeError, ValueError):
                    enriched = []
            else:
                enriched = []

        # Apply enrichments to manifest tools
        tool_map = {t["func_name"]: t for t in tools}
        for item in enriched:
            if not isinstance(item, dict):
                continue
            fname = item.get("func_name")
            if not fname or fname not in tool_map:
                continue
            tool = tool_map[fname]
            changed = False
            if item.get("description"):
                tool["description"] = item["description"]
                tool["summary"] = self._build_summary(item["description"])
                changed = True
            if item.get("response_hint") and item["response_hint"] not in (None, "null"):
                tool["response_hint"] = item["response_hint"]
                changed = True
            if changed:
                tool["api_doc"] = self._build_api_doc(
                    tool["func_name"], tool["method"], tool["path"],
                    tool["description"], tool["python_signature"],
                    tool["params_spec"], tool.get("response_hint"),
                )
                enriched_count += 1

        self.manifest["enriched"] = True
        self.manifest["enriched_with"] = llm
        self._save_cache()

        cost_str = f"${cost_usd:.6f}" if cost_usd is not None else "n/a"
        _log_compile(
            "API ENRICH",
            f"{self.tool_name}: enriched {enriched_count}/{len(tools)} endpoint(s) in {elapsed_ms}ms"
            f" | {input_tokens:,} in / {output_tokens:,} out tokens | cost {cost_str}",
        )

        return {
            "tokens_input": input_tokens,
            "tokens_output": output_tokens,
            "cost_usd": cost_usd,
            "cached": False,
            "model": llm,
            "endpoints_enriched": enriched_count,
            "duration_ms": elapsed_ms,
        }

    # ── Background Schema Sampling ────────────────────────────────────────────

    def save_sampled_schema(self, func_name: str, status_code: int, response_data: Any) -> None:
        """Infer and save a response schema from actual API response data.

        Called asynchronously in the background after each successful API call.
        No LLM involved — pure structural inference. Zero token cost.

        The sampled schema is stored in ``sampled_schemas.json`` alongside the
        manifest. On the next compilation or cache load, these sampled schemas
        are merged into the manifest's ``response_hint`` fields, progressively
        improving the agent's understanding of API responses.
        """
        schema = _infer_schema(response_data)

        # Load existing sampled schemas
        sampled_path = self._cache_dir / "sampled_schemas.json"
        sampled: Dict[str, Any] = {}
        if sampled_path.exists():
            try:
                with open(sampled_path, "r") as f:
                    sampled = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        # Store under func_name → status_code
        if func_name not in sampled:
            sampled[func_name] = {}
        sampled[func_name][str(status_code)] = schema

        # Write atomically
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = sampled_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w") as f:
                json.dump(sampled, f, indent=2)
            tmp_path.replace(sampled_path)
        except OSError:
            pass

        # Also update the in-memory manifest if we have a success schema
        if self.manifest and str(status_code).startswith("2"):
            for tool in self.manifest.get("tools", []):
                if tool["func_name"] == func_name:
                    hint = self._describe_response_schema(schema)
                    if hint and hint not in ("obj", "str"):
                        tool["response_hint"] = hint
                        tool["api_doc"] = self._build_api_doc(
                            tool["func_name"], tool["method"], tool["path"],
                            tool["description"], tool["python_signature"],
                            tool["params_spec"], hint,
                        )
                    break
            self._save_cache()

    def _merge_sampled_schemas(self) -> None:
        """Merge previously sampled response schemas into the current manifest.

        Called after compile() or load_cache() to incorporate schemas captured
        from real API responses during previous task executions.
        """
        if not self.manifest:
            return
        sampled_path = self._cache_dir / "sampled_schemas.json"
        if not sampled_path.exists():
            return

        try:
            with open(sampled_path, "r") as f:
                sampled = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        updated = 0
        for tool in self.manifest.get("tools", []):
            fname = tool["func_name"]
            if fname not in sampled:
                continue
            # Prefer the 200/201/202 status code schema
            schema = None
            for code in ("200", "201", "202"):
                if code in sampled[fname]:
                    schema = sampled[fname][code]
                    break
            if not schema:
                # Use any 2xx schema
                schema = next(
                    (s for c, s in sampled[fname].items() if c.startswith("2")),
                    None,
                )
            if not schema:
                continue

            hint = self._describe_response_schema(schema)
            if hint and hint not in ("obj", "str"):
                existing = tool.get("response_hint")
                # Only update if the sampled hint is more detailed
                if not existing or existing in ("obj", "str", None) or len(hint) > len(existing or ""):
                    tool["response_hint"] = hint
                    tool["api_doc"] = self._build_api_doc(
                        tool["func_name"], tool["method"], tool["path"],
                        tool["description"], tool["python_signature"],
                        tool["params_spec"], hint,
                    )
                    updated += 1

        if updated:
            _log_compile(
                "API SAMPLE",
                f"{self.tool_name}: merged {updated} sampled response schema(s)",
            )

    # ── Single Operation Compilation ──────────────────────────────────────────

    def _compile_operation(
        self,
        spec: Dict[str, Any],
        method: str,
        path: str,
        operation: Dict[str, Any],
        base_url: str,
    ) -> Optional[Dict[str, Any]]:
        """Compile a single OpenAPI operation into Delfhos format."""

        # Derive a clean function name
        operation_id = operation.get("operationId")
        if operation_id:
            func_name = self._sanitize_name(operation_id)
        else:
            func_name = self._path_to_name(method, path)

        action_name = func_name.upper()

        description = (
            operation.get("summary")
            or operation.get("description")
            or f"{method.upper()} {path}"
        )

        # Collect all parameters (path, query, header) and request body
        params_spec = self._collect_parameters(spec, operation, path)

        # Extract response schema for output-format hints
        response_schema = self._collect_response_schema(spec, operation)
        response_hint = self._build_response_hint(response_schema)

        # Build Python signature and parameter descriptions
        signature, parameters = self._build_signature(func_name, params_spec)

        summary = self._build_summary(description)
        api_doc = self._build_api_doc(func_name, method, path, description, signature, params_spec, response_hint)

        return {
            "func_name": func_name,
            "action_name": action_name,
            "method": method.upper(),
            "path": path,
            "base_url": base_url,
            "description": description,
            "summary": summary,
            "parameters": parameters,
            "python_signature": signature,
            "api_doc": api_doc,
            "params_spec": params_spec,
            "response_hint": response_hint,
        }

    def _collect_parameters(
        self, spec: Dict[str, Any], operation: Dict[str, Any], path: str,
    ) -> List[Dict[str, Any]]:
        """Collect path, query, header params and request body fields into a flat list.

        Each entry: {name, in, type, description, required, default?}
        """
        params: List[Dict[str, Any]] = []

        # Operation-level parameters (path, query, header, cookie)
        for raw_param in operation.get("parameters", []):
            param = _deep_resolve(spec, raw_param)
            schema = param.get("schema", {})
            schema = _deep_resolve(spec, schema)
            params.append({
                "name": param.get("name", ""),
                "in": param.get("in", "query"),
                "type": self._describe_type(schema),
                "description": param.get("description") or schema.get("description", ""),
                "required": param.get("required", False),
                "default": schema.get("default"),
            })

        # Request body → flatten top-level properties as body params
        request_body = operation.get("requestBody")
        if request_body:
            request_body = _deep_resolve(spec, request_body)
            content = request_body.get("content", {})
            # Prefer application/json
            media = content.get("application/json") or next(iter(content.values()), {})
            body_schema = _deep_resolve(spec, media.get("schema", {}))

            if body_schema.get("type") == "object" and body_schema.get("properties"):
                body_required = set(body_schema.get("required", []))
                for prop_name, prop_schema in body_schema["properties"].items():
                    prop_schema = _deep_resolve(spec, prop_schema)
                    params.append({
                        "name": prop_name,
                        "in": "body",
                        "type": self._describe_type(prop_schema),
                        "description": prop_schema.get("description", ""),
                        "required": prop_name in body_required,
                        "default": prop_schema.get("default"),
                    })
            else:
                # Non-object body (raw string, array, etc.) → single `body` param
                params.append({
                    "name": "body",
                    "in": "body",
                    "type": self._describe_type(body_schema),
                    "description": request_body.get("description", "Request body"),
                    "required": request_body.get("required", False),
                    "default": None,
                })

        return params

    def _collect_response_schema(
        self, spec: Dict[str, Any], operation: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Extract the success response JSON schema from an operation.

        Tries 200, 201, 202, then 2XX/default. Returns the resolved
        ``application/json`` schema or None if not documented.
        """
        responses = operation.get("responses") or {}

        resp = None
        for code in ("200", "201", "202"):
            resp = responses.get(code)
            if resp:
                break
        if not resp:
            resp = responses.get("2XX") or responses.get("default")
        if not resp:
            return None

        resp = _deep_resolve(spec, resp)
        content = resp.get("content", {})
        media = content.get("application/json") or next(iter(content.values()), {})
        schema = media.get("schema")
        if not schema:
            return None
        return _deep_resolve(spec, schema)

    # Short type names for token efficiency
    _SHORT_TYPES = {
        "string": "str", "integer": "int", "number": "num",
        "boolean": "bool", "array": "array", "object": "obj",
    }

    def _build_response_hint(self, response_schema: Optional[Dict[str, Any]]) -> Optional[str]:
        """Build a full response-type hint. No truncation — every field is shown.

        Uses short type names (str/int/num/bool) and complex-first field ordering
        so the LLM always sees payload fields before metadata.
        """
        if not response_schema:
            return None
        hint = self._describe_response_schema(response_schema, depth=0)
        if hint in self._SHORT_TYPES.values() or hint in ("obj", "array"):
            return hint
        return hint

    def _describe_response_schema(
        self, schema: Dict[str, Any], depth: int = 0,
    ) -> str:
        """Recursively describe a full response schema — no field or char limits.

        Uses token-efficient short type names. Complex fields (objects, arrays)
        are sorted first so payload fields are visible before metadata.
        Max recursion depth: 5 to avoid infinite loops on circular refs.
        """
        if depth > 5 or not isinstance(schema, dict):
            return "obj"

        schema_type = schema.get("type", "object")
        if isinstance(schema_type, list):
            non_null = [t for t in schema_type if t != "null"]
            schema_type = non_null[0] if non_null else "string"

        if schema_type == "array":
            items = schema.get("items", {})
            if items:
                inner = self._describe_response_schema(items, depth + 1)
                return f"[{inner}]"
            return "array"

        if schema_type == "object":
            props = schema.get("properties", {})
            if not props:
                return "obj"

            # Complex types first: objects/arrays carry the payload, primitives are metadata
            def _complexity(item):
                _name, prop = item
                t = prop.get("type", "")
                if isinstance(t, list):
                    t = next((x for x in t if x != "null"), "")
                if t in ("object", "array") or prop.get("properties") or prop.get("items"):
                    return 0
                return 1

            fields = []
            for fname, fprop in sorted(props.items(), key=_complexity):
                inner = self._describe_response_schema(fprop, depth + 1)
                fields.append(f"{fname}:{inner}")
            return "{" + ",".join(fields) + "}"

        if "enum" in schema:
            vals = schema["enum"][:6]
            return "str(" + "|".join(str(v) for v in vals) + ")"

        return self._SHORT_TYPES.get(schema_type, schema_type)

    def _build_signature(
        self, func_name: str, params_spec: List[Dict[str, Any]],
    ) -> Tuple[str, Dict[str, str]]:
        """Build a Python function signature and parameter descriptions dict."""
        parts = []
        parameters: Dict[str, str] = {}

        # Required params first, then optional
        required = [p for p in params_spec if p.get("required")]
        optional = [p for p in params_spec if not p.get("required")]

        for param in required + optional:
            name = param["name"]
            type_str = param["type"]
            desc = param.get("description", name)
            parameters[name] = desc

            if param.get("required"):
                parts.append(f"{name}: {type_str}")
            else:
                default = param.get("default")
                if default is None:
                    default_str = "None"
                elif isinstance(default, str):
                    default_str = f'"{default}"'
                elif isinstance(default, bool):
                    default_str = str(default)
                else:
                    default_str = str(default)
                parts.append(f"{name}: {type_str} = {default_str}")

        sig = f"{func_name}({', '.join(parts)})"
        return sig, parameters

    def _describe_type(self, schema: Dict[str, Any], depth: int = 0) -> str:
        """Convert a JSON Schema type into an LLM-friendly type string."""
        if depth > 4:
            return "object"

        schema_type = schema.get("type", "string")

        # JSON Schema allows type to be a list, e.g. ["string", "null"].
        # Normalise to the first non-null type.
        if isinstance(schema_type, list):
            non_null = [t for t in schema_type if t != "null"]
            schema_type = non_null[0] if non_null else "string"

        if schema_type == "object":
            props = schema.get("properties", {})
            if props:
                req = set(schema.get("required", []))
                fields = []
                for fname, fprop in list(props.items())[:8]:
                    inner = self._describe_type(fprop, depth + 1)
                    opt = "" if fname in req else "?"
                    fields.append(f"{fname}{opt}: {inner}")
                return "{" + ", ".join(fields) + "}"
            return "object"

        if schema_type == "array":
            items = schema.get("items", {})
            if items:
                inner = self._describe_type(items, depth + 1)
                return f"array[{inner}]"
            return "array"

        if "enum" in schema:
            vals = schema["enum"][:6]
            return "string(" + "|".join(str(v) for v in vals) + ")"

        return _TYPE_MAP.get(schema_type, schema_type)

    # ── Doc builders ─────────────────────────────────────────────────────────

    def _build_summary(self, description: str) -> str:
        """Build a compact summary for the prefilter (~15 tokens)."""
        first_sentence = description.split(".")[0].strip()
        if len(first_sentence) > 80:
            first_sentence = first_sentence[:77] + "..."
        return first_sentence

    def _build_api_doc(
        self,
        func_name: str,
        method: str,
        path: str,
        description: str,
        signature: str,
        params_spec: List[Dict[str, Any]],
        response_hint: Optional[str] = None,
    ) -> str:
        """Build comprehensive API doc for code generation prompts."""
        lines = [
            f"# await {self.tool_name}.{signature}",
            f"# {method.upper()} {path} — {description}",
        ]

        # Response format hint — critical for correct field access
        if response_hint:
            lines.append(f"# Returns: {response_hint}")
        else:
            lines.append(f"# Returns: dict or str (response format not documented — print result to inspect)")

        # Add parameter hints (max 8)
        hints = []
        for p in params_spec[:8]:
            loc = p["in"]
            desc = p.get("description", "")
            req = " (required)" if p.get("required") else ""
            if desc:
                hints.append(f"#   {p['name']} [{loc}]{req}: {desc}")
        if hints:
            lines.extend(hints)

        return "\n".join(lines)

    # ── Name helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _sanitize_name(operation_id: str) -> str:
        """Convert an operationId into a clean Python function name.

        Examples:
            'getApiV2UsersList' → 'get_api_v2_users_list'
            'create-user'       → 'create_user'
            'listPets'          → 'list_pets'
        """
        # Insert underscore before uppercase runs (camelCase → snake_case)
        name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", operation_id)
        # Replace non-alphanumeric with underscore
        name = re.sub(r"[^a-zA-Z0-9]", "_", name)
        # Collapse multiple underscores, strip edges
        name = re.sub(r"_+", "_", name).strip("_").lower()
        return name or "unknown_operation"

    @staticmethod
    def _path_to_name(method: str, path: str) -> str:
        """Derive a function name from HTTP method + path when operationId is absent.

        Examples:
            ('get', '/users/{id}')       → 'get_users_by_id'
            ('post', '/orders')          → 'post_orders'
            ('delete', '/items/{itemId}')→ 'delete_items_by_item_id'
        """
        # Remove path parameter braces and convert to descriptive suffix
        clean = path.strip("/")
        parts = []
        for segment in clean.split("/"):
            if segment.startswith("{") and segment.endswith("}"):
                param = segment[1:-1]
                # camelCase → snake_case
                param = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", param).lower()
                parts.append(f"by_{param}")
            else:
                parts.append(segment)

        name = f"{method}_{'_'.join(parts)}"
        name = re.sub(r"[^a-zA-Z0-9]", "_", name)
        name = re.sub(r"_+", "_", name).strip("_").lower()
        return name or f"{method}_unknown"

    # ── Cache Management ─────────────────────────────────────────────────────

    def _cache_key(self) -> str:
        """Generate a stable cache key from spec source + tool name."""
        key_str = f"{self.tool_name}|{self.spec_source}"
        short_hash = hashlib.sha256(key_str.encode()).hexdigest()[:12]
        return f"{self.tool_name}_{short_hash}"

    def _save_cache(self) -> None:
        """Save compiled manifest to disk cache (no-op when cache=False)."""
        if not self.cache or not self.manifest:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self._cache_dir / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(self.manifest, f, indent=2)

    def clear_cache(self) -> None:
        """Delete the cached manifest."""
        import shutil
        if self._cache_dir.exists():
            shutil.rmtree(self._cache_dir)
