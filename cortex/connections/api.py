"""
APITool Connection Class

Connect any REST API with an OpenAPI (Swagger) specification to Delfhos agents.

The public interface for auto-compiling REST APIs into native Delfhos tools.

Usage::

    from delfhos import Agent, APITool

    # From a public OpenAPI spec URL
    petstore = APITool(
        spec="https://petstore3.swagger.io/api/v3/openapi.json",
        allow=["list_pets", "get_pet_by_id"],
    )

    # From a local spec file with auth
    internal = APITool(
        spec="./openapi.yaml",
        base_url="https://api.internal.corp/v1",
        auth={"Authorization": "Bearer sk_..."},
        confirm=["create_order", "delete_order"],
    )

    agent = Agent(tools=[petstore, internal], llm="gemini-2.5-flash")
    agent.run("List all available pets and show their names")
"""

import re
import time
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import urlparse

from cortex._engine.connection import AuthType
from .base import BaseConnection, _PrettyInspectDict


def _log_connection(message: str, details: str) -> None:
    """Best-effort compile telemetry for API connection flows."""
    try:
        from cortex._engine.utils.console import console
        console.tool(message, details)
    except Exception:
        return


class _InspectDescriptor:
    """Descriptor allowing .inspect() to work on both APITool class and instances."""

    def __get__(self, obj, objtype=None):
        if obj is None:
            return objtype._class_inspect
        else:
            return lambda verbose=False: obj._do_inspect(verbose=verbose)


class APITool(BaseConnection):
    """
    Connect any REST API with an OpenAPI 3.x specification to a Delfhos agent.

    Each endpoint in the spec becomes a callable tool action that the agent can
    use in generated Python code. Authentication, parameter mapping, and HTTP
    execution are handled automatically.

    Supported spec formats:
      - OpenAPI 3.x (JSON or YAML)
      - Loaded from URL or local file path

    Supported auth methods:
      - Header-based: ``auth={"Authorization": "Bearer ..."}``
      - Query param-based: ``auth_params={"api_key": "..."}``

    Args:
        spec:        URL or file path to an OpenAPI 3.x JSON/YAML specification.
        base_url:    Override for the API base URL. If omitted, extracted from
                     the spec's ``servers[0].url`` field.
        auth:        Dict of HTTP headers injected into every request
                     (e.g., ``{"Authorization": "Bearer sk_test_..."}``,
                     ``{"X-API-Key": "..."}``).
        auth_params: Dict of query parameters injected into every request
                     (e.g., ``{"api_key": "..."}``). Use this for APIs that
                     authenticate via URL params rather than headers.
        name:        Custom label for this connection (default: auto-derived from spec title).
        allow:       Restrict which endpoints are exposed to the agent.
                     Pass a list of function names as shown by ``APITool.inspect()``.
                     None means all endpoints are available.
        confirm:     Require human approval before executing listed endpoints.
                     True (all), False (none), or a list of function names.
        cache:       If True, reuse ``~/delfhos/api_cache/`` to skip
                     re-parsing the spec on subsequent runs.
                     Disabled by default to avoid stale schemas.

    Example::

        from delfhos import Agent, APITool

        api = APITool(
            spec="https://petstore3.swagger.io/api/v3/openapi.json",
            allow=["list_pets", "get_pet_by_id"],
            confirm=["add_pet"],
        )
        print(api.inspect())  # See compiled endpoints

        agent = Agent(tools=[api], llm="gemini-2.5-flash")
        agent.run("List all available pets")
    """

    TOOL_NAME = "api"
    ALLOWED_ACTIONS: Optional[List[str]] = None

    inspect = _InspectDescriptor()

    def __init__(
        self,
        spec: str,
        *,
        base_url: Optional[str] = None,
        auth: Optional[Dict[str, str]] = None,
        auth_params: Optional[Dict[str, str]] = None,
        name: Optional[str] = None,
        allow: Optional[Union[str, List[str]]] = None,
        confirm: Union[bool, List[str], None] = True,
        cache: bool = False,
    ):
        self.spec_source = spec
        self.base_url_override = base_url
        self.auth_headers = auth or {}
        self.auth_params = auth_params or {}
        self.cache = cache

        # Derive a tool name from the spec if no name provided
        self.api_tool_name = name or self._derive_name(spec)

        # Override class-level TOOL_NAME so Delfhos registries treat each
        # APITool instance as a distinct tool.
        self.TOOL_NAME = self.api_tool_name

        super().__init__(
            credentials={"auth_headers": self.auth_headers, "auth_params": self.auth_params},
            allow=allow,
            confirm=confirm,
            name=self.api_tool_name,
            auth_type=AuthType.BEARER_TOKEN if self.auth_headers else AuthType.API_KEY if self.auth_params else AuthType.NONE,
        )

    # ── Class-level inspect ──────────────────────────────────────────────────

    @classmethod
    def _class_inspect(
        cls,
        spec: str,
        verbose: bool = False,
        base_url: Optional[str] = None,
        cache: bool = False,
    ) -> dict:
        """Inspect API endpoints from a spec without creating a full connection.

        Args:
            spec:     URL or file path to the OpenAPI spec.
            verbose:  If True, include endpoint descriptions and parameter details.
            base_url: Override for the API base URL.
            cache:    If True, uses cached manifest if available.

        Returns:
            dict with API information and available endpoints.

        Example::

            print(APITool.inspect(spec="https://petstore3.swagger.io/api/v3/openapi.json"))
            print(APITool.inspect(spec="./openapi.yaml", verbose=True))
        """
        temp = cls(spec, base_url=base_url, cache=cache)
        return temp._do_inspect(verbose=verbose)

    # ── Instance inspect ─────────────────────────────────────────────────────

    def _do_inspect(self, verbose: bool = False) -> dict:
        """Build inspect output for this API connection."""
        from cortex._engine.api.compiler import OpenAPICompiler

        started = time.perf_counter()
        _log_connection("API INSPECT", f"{self.api_tool_name}: preparing manifest")

        compiler = OpenAPICompiler(
            tool_name=self.api_tool_name,
            spec_source=self.spec_source,
            base_url=self.base_url_override,
            cache=self.cache,
        )

        manifest = compiler.load_cache()
        if not manifest:
            _log_connection("API INSPECT", f"{self.api_tool_name}: cache miss, compiling spec")
            manifest = compiler.compile()
        else:
            _log_connection(
                "API INSPECT",
                f"{self.api_tool_name}: using cache ({len(manifest.get('tools', []))} endpoint(s))",
            )

        endpoints = []
        for tool in manifest.get("tools", []):
            endpoints.append({
                "name": tool["func_name"],
                "method": tool["method"],
                "path": tool["path"],
                "description": tool.get("description", ""),
            })

        api_info = {
            "title": manifest.get("api_title", "unknown"),
            "version": manifest.get("api_version", "unknown"),
            "base_url": manifest.get("base_url", ""),
            "spec_source": self.spec_source,
        }

        elapsed = time.perf_counter() - started
        _log_connection("API INSPECT", f"{self.api_tool_name}: ready in {elapsed:.2f}s")

        if not verbose:
            return _PrettyInspectDict({
                "tool": self.api_tool_name,
                "api": api_info,
                "methods": [e["name"] for e in endpoints],
                "total": len(endpoints),
                "auth_type": self.auth_type.value if hasattr(self, "auth_type") else None,
            })

        allowed = self.effective_allowed_actions()

        methods = []
        for ep in endpoints:
            methods.append({
                "name": ep["name"],
                "description": f"{ep['method']} {ep['path']} — {ep['description']}",
            })

        return _PrettyInspectDict({
            "tool": self.api_tool_name,
            "api": api_info,
            "allowed": allowed,
            "methods": methods,
            "total": len(endpoints),
            "auth_type": self.auth_type.value if hasattr(self, "auth_type") else None,
        })

    # ── Engine compilation (called by Agent._configure_tools) ────────────────

    def compile(self) -> None:
        """Parse the spec, compile endpoints, and register into the Delfhos engine.

        This is called internally by ``Agent._configure_tools()``.
        """
        from cortex._engine.api.compiler import OpenAPICompiler
        from cortex._engine.api.executor import APIExecutor, build_api_tools
        from cortex._engine.tools.tool_registry import TOOL_REGISTRY, COMPRESSED_API_DOCS, TOOL_ACTION_SUMMARIES
        from cortex._engine.tools.internal_tools import internal_tools

        started = time.perf_counter()
        _log_connection("API COMPILE", f"{self.api_tool_name}: start")

        compiler = OpenAPICompiler(
            tool_name=self.api_tool_name,
            spec_source=self.spec_source,
            base_url=self.base_url_override,
            cache=self.cache,
        )

        manifest = compiler.load_cache()
        if not manifest:
            # When allow= is set, compile all endpoints so the filter
            # can find them (otherwise MAX_ENDPOINTS may cut them off).
            max_ep = 0 if self.allow else None
            _log_connection("API COMPILE", f"{self.api_tool_name}: cache miss, compiling OpenAPI schema")
            manifest = compiler.compile(max_endpoints=max_ep)
        else:
            _log_connection(
                "API COMPILE",
                f"{self.api_tool_name}: cache hit ({len(manifest.get('tools', []))} endpoint(s))",
            )

        manifest_tools = manifest.get("tools", [])
        selected_tools = manifest_tools

        # Filter by allow= if set
        if self.allow is not None:
            normalized = {self._normalize_action_name(a) for a in self.allow}
            discovered = {t["func_name"] for t in manifest_tools}
            unknown = sorted(a for a in normalized if a not in discovered)
            if unknown:
                from delfhos.errors import ConnectionConfigurationError
                raise ConnectionConfigurationError(
                    tool_name=self.api_tool_name,
                    detail=(
                        f"Unknown API endpoints in allow=: {unknown}. "
                        f"Available endpoints: {sorted(discovered)}. "
                        f"Use APITool.inspect(spec=...) to see all endpoints."
                    ),
                )
            selected_tools = [t for t in manifest_tools if t["func_name"] in normalized]
            _log_connection(
                "API COMPILE",
                f"{self.api_tool_name}: allow filter kept {len(selected_tools)}/{len(manifest_tools)} endpoint(s)",
            )

        # 1. Register into TOOL_REGISTRY (for prefilter LLM)
        capability, summaries = compiler.get_capability(tools=selected_tools)
        TOOL_REGISTRY[self.api_tool_name] = capability
        TOOL_ACTION_SUMMARIES[self.api_tool_name] = summaries

        # 2. Register into COMPRESSED_API_DOCS (for code gen LLM)
        docs = compiler.get_api_docs(tools=selected_tools)
        COMPRESSED_API_DOCS.update(docs)

        # 3. Build executor and Tool namespace
        executor = APIExecutor(
            tool_name=self.api_tool_name,
            compiled_tools=selected_tools,
            auth_headers=self.auth_headers,
            auth_params=self.auth_params,
        )

        namespace = build_api_tools(executor, self.api_tool_name, allow=None)
        internal_tools[self.api_tool_name] = namespace
        elapsed = time.perf_counter() - started
        _log_connection(
            "API COMPILE",
            f"{self.api_tool_name}: registered {len(selected_tools)} endpoint(s) in {elapsed:.2f}s",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _derive_name(spec: str) -> str:
        """Derive a clean tool name from the spec source."""
        # URL → extract domain or last path segment
        if spec.startswith(("http://", "https://")):
            parsed = urlparse(spec)
            # Try to extract a meaningful name from the hostname
            hostname = parsed.hostname or ""
            # "petstore3.swagger.io" → "petstore3"
            # "api.stripe.com" → "stripe"
            parts = hostname.split(".")
            if len(parts) >= 2:
                candidate = parts[-2] if parts[0] in ("api", "www") else parts[0]
            else:
                candidate = parts[0] if parts else "api"
            candidate = re.sub(r"[^a-zA-Z0-9]", "_", candidate).lower()
            return candidate or "api"

        # Local file → use filename without extension
        from pathlib import Path
        stem = Path(spec).stem
        # "petstore_openapi" → "petstore_openapi"
        candidate = re.sub(r"[^a-zA-Z0-9]", "_", stem).lower()
        # Remove common suffixes that aren't informative (one pass only)
        for suffix in ("_openapi", "_swagger", "_spec", "_api"):
            if candidate.endswith(suffix) and len(candidate) > len(suffix):
                candidate = candidate[: -len(suffix)]
                break
        return candidate or "api"


__all__ = ["APITool"]
