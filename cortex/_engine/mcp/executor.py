"""
MCP Runtime Executor

Bridges Delfhos's generated Python code with MCP's tools/call JSON-RPC.

When the LLM generates code like:
    result = await github.create_issue(owner="org", repo="app", title="Bug")

This executor:
  1. Receives the call via a delfhos.Tool instance
  2. Maps it to the MCP tool name
  3. Sends a JSON-RPC tools/call to the running MCP server
  4. Returns the formatted result
"""

import json
from typing import Any, Dict, List, Optional
from delfhos.errors import ToolDefinitionError


class MCPExecutor:
    """
    Thin bridge between delfhos Tool instances and the MCP JSON-RPC server.
    Each MCP tool becomes a real Tool object — this class just handles the
    transport (JSON-RPC call + result formatting).
    """

    def __init__(self, client, tool_name: str, compiled_tools: List[Dict[str, Any]]):
        """
        Args:
            client: Running MCPClient instance
            tool_name: Delfhos tool name (e.g., "github")
            compiled_tools: List of compiled tool dicts from MCPCompiler
        """
        self.client = client
        self.tool_name = tool_name
        self._tools = {t["mcp_name"]: t for t in compiled_tools}

    def call(self, mcp_tool_name: str, **kwargs) -> str:
        """Call an MCP tool via JSON-RPC and return formatted result."""
        result = self.client.call_tool(mcp_tool_name, kwargs)

        # Surface MCP-level errors so the orchestrator can retry
        if isinstance(result, dict) and result.get("isError"):
            content = result.get("content", [])
            error_text = " ".join(
                item.get("text", "") for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ).strip() or "MCP tool returned an error."
            # Preserve established tool error routing for orchestrator retries.
            from delfhos.tool import ToolException
            raise ToolException(error_text)

        return self._format_result(result)

    @staticmethod
    def _format_result(result: Any) -> str:
        """Format MCP tool result into a string for the agent."""
        if isinstance(result, dict):
            content = result.get("content", [])
            if content:
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            parts.append(item.get("text", ""))
                        elif item.get("type") == "image":
                            parts.append(f"[Image: {item.get('mimeType', 'image')}]")
                        else:
                            parts.append(json.dumps(item))
                    else:
                        parts.append(str(item))
                return "\n".join(parts)
            return json.dumps(result, indent=2)
        return str(result)


def build_mcp_tools(executor: MCPExecutor, tool_name: str) -> "MCPToolNamespace":
    """
    Build a namespace of real Tool instances from an MCPExecutor.

    Each MCP tool becomes a ``delfhos.Tool`` with:
      - auto-generated parameter schema (types + descriptions)
      - ``api_doc()`` output identical to custom @tool functions
      - input validation + ToolException error routing

    Returns an ``MCPToolNamespace`` — a lightweight object that exposes
    every MCP tool as an attribute (``github.create_issue``, etc.) and
    is itself callable() so ToolContainer's add_tool() accepts it.
    """
    from delfhos.tool import Tool, build_api_signature

    tools: Dict[str, Tool] = {}

    for mcp_name, tool_def in executor._tools.items():
        description = tool_def.get("description", f"Execute {mcp_name}")
        input_schema = tool_def.get("input_schema", {})
        properties = input_schema.get("properties", {})
        required = set(input_schema.get("required", []))

        # Build parameter dict in the same format as _extract_signature
        params: Dict[str, Any] = {}
        for prop_name, prop_schema in properties.items():
            from cortex._engine.mcp.compiler import MCPCompiler
            type_str = MCPCompiler._describe_json_type_static(prop_schema)
            entry: Dict[str, Any] = {"type": type_str}
            prop_desc = prop_schema.get("description")
            if prop_desc:
                entry["desc"] = prop_desc
            if prop_name in required:
                entry["required"] = True
            else:
                entry["required"] = False
                if "default" in prop_schema:
                    entry["default"] = prop_schema["default"]
                else:
                    entry["default"] = None
            params[prop_name] = entry

        # Capture mcp_name in closure
        def _make_func(name: str):
            async def _execute(**kwargs):
                kwargs.pop("desc", None)
                return executor.call(name, **kwargs)
            _execute.__name__ = name
            _execute.__doc__ = description
            return _execute

        tool = Tool(
            name=mcp_name,
            description=description,
            parameters=params if params else None,
            func=_make_func(mcp_name),
            _internal_use=True,
        )
        tools[mcp_name] = tool

    return MCPToolNamespace(tool_name, tools)


class MCPToolNamespace:
    """
    Lightweight attribute-access wrapper around a dict of Tool instances.

    Makes ``github.create_issue(...)`` work in LLM-generated code while
    keeping each method a real Tool object with validation and api_doc().
    """

    def __init__(self, name: str, tools: Dict[str, Any]):
        self.__name__ = name
        self._tools = tools

    def __call__(self, **kwargs):
        raise ToolDefinitionError(
            detail=f"Use specific methods like {self.__name__}.action_name() instead of calling the tool object directly."
        )

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(self._tools.keys())
            raise AttributeError(
                f"MCP server '{self.__name__}' has no tool '{name}'. "
                f"Available: {available}"
            )
        # Return tool.execute so await github.create_issue(...)  works
        return tool.execute

    def get_all_api_docs(self) -> str:
        """Concatenate api_doc() for every tool in this namespace."""
        return "\n\n".join(t.api_doc() for t in self._tools.values())
