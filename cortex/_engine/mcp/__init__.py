"""
MCP (Model Context Protocol) integration for Delfhos.

Provides a native compiler that transforms any MCP server into a Delfhos tool:
  1. client.py   — JSON-RPC protocol client (stdio + SSE transports)
  2. compiler.py — Schema → Delfhos tool_docs/registry compiler + cache
  3. executor.py — Runtime bridge that forwards tool calls via JSON-RPC
"""

from .client import MCPClient
from .compiler import MCPCompiler
from .executor import MCPExecutor, MCPToolNamespace, build_mcp_tools
