"""
OpenAPI Runtime Executor

Bridges Delfhos's generated Python code with real HTTP API calls.

When the LLM generates code like:
    result = await petstore.list_pets(limit=10)

This executor:
  1. Receives the call via a delfhos.Tool instance
  2. Maps it to the compiled operation (method, path, params)
  3. Builds an HTTP request (path params, query params, JSON body)
  4. Sends it via httpx
  5. Returns the parsed JSON (or text) response
"""

import json
import re
from typing import Any, Dict, List, Optional, Set
from delfhos.errors import ToolDefinitionError


class APIExecutor:
    """
    Thin bridge between delfhos Tool instances and real REST API endpoints.

    Each compiled operation becomes a callable Tool — this class handles
    building the HTTP request and returning the response.
    """

    def __init__(
        self,
        tool_name: str,
        compiled_tools: List[Dict[str, Any]],
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, str]] = None,
        path_params: Optional[Dict[str, str]] = None,
        sample: bool = False,
        compiler: Optional[Any] = None,
    ):
        """
        Args:
            tool_name:     Delfhos tool name (e.g., "petstore")
            compiled_tools: List of compiled tool dicts from OpenAPICompiler
            headers:       Headers injected into every request (e.g., {"Authorization": "Bearer ..."})
            params:        Query params injected into every request (e.g., {"api_key": "..."})
            path_params:   Path parameters injected into every request URL
                           (e.g., {"globalCompanyId": "myco"}).  Substituted into
                           URL templates like ``/api/{globalCompanyId}/...``.
            sample:        If True, capture response schemas in the background after each call.
            compiler:      OpenAPICompiler instance for saving sampled schemas.
        """
        self.tool_name = tool_name
        self._tools = {t["func_name"]: t for t in compiled_tools}
        self._headers = headers or {}
        self._params = params or {}
        self._path_params = path_params or {}
        self._sample = sample
        self._compiler = compiler

        # Validate that no header/param/path_param value is None — catches missing env vars early
        for k, v in self._headers.items():
            if v is None:
                raise ToolDefinitionError(
                    detail=(
                        f"APITool '{tool_name}': header '{k}' is None. "
                        f"Check that the environment variable holding the API key is set."
                    )
                )
        for k, v in self._params.items():
            if v is None:
                raise ToolDefinitionError(
                    detail=(
                        f"APITool '{tool_name}': param '{k}' is None. "
                        f"Check that the environment variable holding the API key is set."
                    )
                )
        for k, v in self._path_params.items():
            if v is None:
                raise ToolDefinitionError(
                    detail=(
                        f"APITool '{tool_name}': path_param '{k}' is None. "
                        f"Check that the environment variable holding the value is set."
                    )
                )

    def call(self, func_name: str, **kwargs) -> str:
        """Execute an API call and return formatted result."""
        import httpx

        tool_def = self._tools.get(func_name)
        if not tool_def:
            available = ", ".join(self._tools.keys())
            from delfhos.tool import ToolException
            raise ToolException(
                f"API '{self.tool_name}' has no endpoint '{func_name}'. "
                f"Available: {available}"
            )

        method = tool_def["method"]
        path_template = tool_def["path"]
        base_url = tool_def["base_url"]
        params_spec = tool_def.get("params_spec", [])

        # Classify which kwargs go where
        path_params = dict(self._path_params)  # Pre-seed with auto-injected path params
        query_params = dict(self._params)
        body_params = {}
        header_params = dict(self._headers)

        param_locations = {p["name"]: p["in"] for p in params_spec}

        for key, value in kwargs.items():
            if key == "desc":
                # Tool description param used by Delfhos approval system, not sent to API
                continue
            location = param_locations.get(key, "query")
            if location == "path":
                path_params[key] = value
            elif location == "header":
                header_params[key] = str(value)
            elif location == "body":
                body_params[key] = value
            else:
                # Default: query param
                if value is not None:
                    query_params[key] = value

        # Build URL with path parameters (use re.sub for exact matches only)
        # Normalise URL-encoded braces (%7B / %7D) that some specs use
        from urllib.parse import unquote
        path = unquote(path_template)
        for param_name, param_value in path_params.items():
            from urllib.parse import quote
            safe_value = quote(str(param_value), safe="")
            path = re.sub(
                r"\{" + re.escape(param_name) + r"\}",
                safe_value,
                path,
            )

        url = f"{base_url}{path}"

        # Build request
        request_kwargs: Dict[str, Any] = {
            "method": method,
            "url": url,
            "headers": header_params,
            "timeout": 30,
            "follow_redirects": True,
        }

        if query_params:
            request_kwargs["params"] = query_params

        if body_params and method in ("POST", "PUT", "PATCH"):
            # If there's a single "body" key, send it directly
            if len(body_params) == 1 and "body" in body_params:
                body_val = body_params["body"]
                if isinstance(body_val, (dict, list)):
                    request_kwargs["json"] = body_val
                else:
                    request_kwargs["content"] = str(body_val)
                    request_kwargs["headers"]["Content-Type"] = "text/plain"
            else:
                request_kwargs["json"] = body_params

        try:
            with httpx.Client() as client:
                response = client.request(**request_kwargs)
                response.raise_for_status()
                result = self._format_response(response)

                # Background schema sampling — zero cost, zero latency impact
                if self._sample and self._compiler and isinstance(result, (dict, list)):
                    import threading
                    status_code = response.status_code
                    threading.Thread(
                        target=self._sample_schema,
                        args=(func_name, status_code, result),
                        daemon=True,
                    ).start()

                return result
        except httpx.HTTPStatusError as exc:
            from delfhos.tool import ToolException
            body = exc.response.text[:500]
            raise ToolException(
                f"API error {exc.response.status_code} on {method} {url}: {body}"
            )
        except httpx.RequestError as exc:
            from delfhos.tool import ToolException
            raise ToolException(f"Request failed for {method} {url}: {exc}")

    def _sample_schema(self, func_name: str, status_code: int, response_data: Any) -> None:
        """Save inferred response schema in the background (best-effort)."""
        try:
            self._compiler.save_sampled_schema(func_name, status_code, response_data)
        except Exception:
            pass  # Silent — never block or fail the API call

    @staticmethod
    def _format_response(response):
        """Return the parsed response object for the agent.

        JSON responses are returned as native Python dicts/lists so that
        LLM-generated code can use them directly (no json.loads() needed).
        Non-JSON responses are returned as plain text strings.

        JSON detection uses two passes:
        1. Content-Type header says "application/json" → parse immediately.
        2. Fallback: body starts with { or [ → attempt JSON parse regardless
           of content-type (handles APIs that omit or mislabel the header).
        """
        content_type = response.headers.get("content-type", "")

        if "application/json" in content_type:
            try:
                return response.json()
            except (json.JSONDecodeError, ValueError):
                pass

        text = response.text
        if not text.strip():
            return {"status": response.status_code, "body": None}

        # Fallback JSON detection: try to parse if body looks like JSON.
        # This handles APIs that return application/octet-stream, text/plain,
        # or any other non-JSON content-type with a JSON body.
        stripped = text.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(text)
            except (json.JSONDecodeError, ValueError):
                pass

        # Truncate very large non-JSON responses to avoid blowing up context
        if len(text) > 50_000:
            return text[:50_000] + "\n... (truncated)"
        return text


def build_api_tools(
    executor: APIExecutor,
    tool_name: str,
    allow: Optional[Set[str]] = None,
) -> "APIToolNamespace":
    """Build a namespace of Tool instances from an APIExecutor.

    Each API operation becomes a ``delfhos.Tool`` with auto-generated
    parameter schema. Returns an ``APIToolNamespace`` so LLM-generated
    code can do ``api.list_pets(limit=10)``.
    """
    from delfhos.tool import Tool
    from cortex._engine.api.compiler import OpenAPICompiler

    tools: Dict[str, Tool] = {}

    for func_name, tool_def in executor._tools.items():
        if allow is not None and func_name not in allow:
            continue

        description = tool_def.get("description", f"Call {func_name}")
        params_spec = tool_def.get("params_spec", [])

        # Build parameter dict in Tool format
        params: Dict[str, Any] = {}
        for p in params_spec:
            entry: Dict[str, Any] = {"type": p["type"]}
            if p.get("description"):
                entry["desc"] = p["description"]
            entry["required"] = p.get("required", False)
            if not entry["required"] and "default" in p:
                entry["default"] = p["default"]
            params[p["name"]] = entry

        # Capture func_name in closure
        def _make_func(name: str):
            async def _execute(**kwargs):
                import asyncio as _asyncio
                kwargs.pop("desc", None)
                return await _asyncio.to_thread(executor.call, name, **kwargs)
            _execute.__name__ = name
            _execute.__doc__ = description
            return _execute

        tool = Tool(
            name=func_name,
            description=description,
            parameters=params if params else None,
            func=_make_func(func_name),
            _internal_use=True,
            handle_error=None,  # Let API errors propagate so the orchestrator sees the real error
        )
        tools[func_name] = tool

    return APIToolNamespace(tool_name, tools)


class APIToolNamespace:
    """
    Lightweight attribute-access wrapper around a dict of Tool instances.

    Makes ``petstore.list_pets(...)`` work in LLM-generated code while
    keeping each method a real Tool object with validation and api_doc().
    """

    def __init__(self, name: str, tools: Dict[str, Any]):
        self.__name__ = name
        self._tools = tools

    def __call__(self, **kwargs):
        raise ToolDefinitionError(
            detail=(
                f"Use specific methods like {self.__name__}.action_name() "
                f"instead of calling the tool object directly."
            ),
        )

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(self._tools.keys())
            raise AttributeError(
                f"API '{self.__name__}' has no endpoint '{name}'. "
                f"Available: {available}"
            )
        return tool.execute

    def get_all_api_docs(self) -> str:
        """Concatenate api_doc() for every tool in this namespace."""
        return "\n\n".join(t.api_doc() for t in self._tools.values())
