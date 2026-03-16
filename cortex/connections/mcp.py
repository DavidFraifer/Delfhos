"""
MCP Connection Class

The public interface for integrating any Model Context Protocol server.
Supports shorthand resolution:
  MCP("server-github") -> "npx -y @modelcontextprotocol/server-github"
"""

from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from cortex._engine.connection import AuthType
from .base import BaseConnection


class MCP(BaseConnection):
    """
    Connects to ANY Model Context Protocol (MCP) server, turning it into a native Delfhos tool.
    
    Accepts 4 formats for the server string:
      1. Short name:    MCP("server-github") -> resolves to official @modelcontextprotocol package
      2. Scoped npm:    MCP("@anthropic/server-x") -> resolves to npx command
      3. Full command:  MCP("npx -y custom-server") -> runs as-is
      4. Remote URL:    MCP("https://mcp.remote.com/sse") -> connects via SSE
    """
    
    # TOOL_NAME is overridden dynamically per instance
    TOOL_NAME = "mcp"
    ALLOWED_ACTIONS: Optional[List[str]] = None

    @staticmethod
    def _normalize_action(value: str) -> str:
        return str(value).strip().lower().replace("-", "_")

    def __init__(
        self,
        server: str,
        *,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        name: Optional[str] = None,
        allowed: Optional[Union[str, List[str]]] = None,
        cache: bool = True,
    ):
        """
        Args:
            server: Short name, scoped package, full command, or SSE URL.
            args: Additional command line arguments for the server.
            env: Environment variables (e.g., API keys).
            headers: HTTP headers for SSE connections.
            name: Custom name for this connection in Delfhos (defaults to auto-derived).
            actions: (Not typically used for MCP) List of allowed action names.
            cache: If True, uses ~/.delfhos/mcp_cache/ to skip introspection on next run.
        """
        self.raw_server = server
        self.command_or_url = self._resolve_server(server)
        self.args = args or []
        self.env = env or {}
        self.headers = headers or {}
        self.cache = cache
        
        # Determine base tool name
        self.mcp_tool_name = name or self._derive_name(server)
        
        # Override the class-level TOOL_NAME for this instance so Delfhos registries
        # treat e.g., "github" and "slack" as distinct tools, not just "mcp".
        self.TOOL_NAME = self.mcp_tool_name

        super().__init__(
            credentials={"env": self.env, "headers": self.headers},
            allowed=allowed,
            name=self.mcp_tool_name,
            auth_type=AuthType.NONE,  # Handled via env/headers transparently
        )

    @classmethod
    def discover_actions(
        cls,
        server: str,
        *,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        name: Optional[str] = None,
        cache: bool = True,
    ) -> List[str]:
        """
        Discover MCP actions before creating/running an Agent.

        The manifest is automatically cached (~/.delfhos/mcp_cache/) for faster runs.
        """
        probe = cls(
            server,
            args=args,
            env=env,
            headers=headers,
            name=name,
            cache=cache,
        )

        from cortex._engine.mcp.client import MCPClient
        from cortex._engine.mcp.compiler import MCPCompiler

        compiler = MCPCompiler(
            tool_name=probe.mcp_tool_name,
            command=probe.command_or_url,
            args=probe.args,
            env_keys=list(probe.env.keys()),
        )

        if not probe.cache:
            compiler.clear_cache()

        # Always compile cache for discover_actions
        manifest = compiler.load_cache()
        if not manifest:
            client = MCPClient(probe.command_or_url, args=probe.args, env=probe.env)
            try:
                client.start()
                server_info = client.initialize()
                tools_list = client.list_tools()
                manifest = compiler.compile(tools_list, server_info)
            finally:
                client.stop()
        return [str(t.get("mcp_name", "")).strip() for t in manifest.get("tools", []) if t.get("mcp_name")]

    def get_available_actions(self) -> List[str]:
        """Instance helper for discovering available MCP actions."""
        return self.discover_actions(
            self.raw_server,
            args=self.args,
            env=self.env,
            headers=self.headers,
            name=self.mcp_tool_name,
            cache=self.cache,
        )

    def _resolve_server(self, server: str) -> str:
        """Resolve short names into full execution commands."""
        server = server.strip()
        
        # URL (SSE transport)
        if server.startswith(("http://", "https://")):
            return server
            
        # Full command already specified
        if " " in server or server.startswith("npx") or server.startswith("python"):
            return server
            
        # Scoped npm package: "@anthropic/server-x"
        if server.startswith("@"):
            return f"npx -y {server}"
            
        # Short name: "server-github" -> official package
        if server.startswith("server-"):
            return f"npx -y @modelcontextprotocol/{server}"
            
        # Bare name: "github" -> assume official package
        return f"npx -y @modelcontextprotocol/server-{server}"

    def _derive_name(self, server: str) -> str:
        """Derive a clean tool name from the server string."""
        # Custom exact command -> generic fallback if no name provided
        if " " in server:
            return "mcp_tool"
            
        # URL -> extract hostname
        if server.startswith(("http://", "https://")):
            parsed = urlparse(server)
            return parsed.hostname.replace(".", "_") if parsed.hostname else "mcp_remote"
            
        # Package path -> extract base name
        base = server.split("/")[-1]
        
        # Remove "server-" prefix for cleaner naming
        if base.startswith("server-"):
            base = base[len("server-"):]
            
        # Sanitize for Python identifier safety
        base = base.replace("-", "_").lower()
        return base or "mcp_tool"

    def compile(self) -> None:
        """
        Start the server, pull schemas, compile them into Delfhos format,
        and dynamically register them into the engine.
        
        This is called internally by Agent._configure_tools().
        """
        from cortex._engine.mcp.client import MCPClient
        from cortex._engine.mcp.compiler import MCPCompiler
        from cortex._engine.mcp.executor import MCPExecutor, build_mcp_tools
        from cortex._engine.tools.tool_registry import TOOL_REGISTRY, COMPRESSED_API_DOCS, TOOL_ACTION_SUMMARIES
        from cortex._engine.tools.internal_tools import internal_tools

        compiler = MCPCompiler(
            tool_name=self.mcp_tool_name,
            command=self.command_or_url,
            args=self.args,
            env_keys=list(self.env.keys())
        )

        if not self.cache:
            compiler.clear_cache()

        manifest = compiler.load_cache()
        client = None

        if not manifest:
            # First run: Introspect the server
            client = MCPClient(self.command_or_url, args=self.args, env=self.env)
            client.start()
            server_info = client.initialize()
            tools_list = client.list_tools()
            
            # Compile and save cache
            manifest = compiler.compile(tools_list, server_info)

        # 1. Register into TOOL_REGISTRY (for Prefilter LLM capability listing)
        capability, summaries = compiler.get_capability()
        TOOL_REGISTRY[self.mcp_tool_name] = capability
        TOOL_ACTION_SUMMARIES[self.mcp_tool_name] = summaries

        # 2. Register into COMPRESSED_API_DOCS (for Code Gen LLM injected API docs)
        docs = compiler.get_api_docs()
        COMPRESSED_API_DOCS.update(docs)

        # 3. Build Tool instances and register namespace into internal_tools
        if not client:
            client = MCPClient(self.command_or_url, args=self.args, env=self.env)
            client.start()
            client.initialize()
            
        executor = MCPExecutor(client, self.mcp_tool_name, manifest["tools"])
        allowed_actions = None
        if self.allowed is not None:
            normalized = {self._normalize_action(a) for a in self.allowed}
            discovered = {self._normalize_action(t.get("mcp_name", "")) for t in manifest.get("tools", []) if t.get("mcp_name")}
            disallowed_requested = sorted(a for a in normalized if a not in discovered)
            if disallowed_requested:
                from delfhos.errors import ConnectionConfigurationError
                raise ConnectionConfigurationError(
                    tool_name=self.mcp_tool_name,
                    detail=(
                        "Unsupported MCP actions requested: "
                        f"{disallowed_requested}. Available actions: {sorted(discovered)}"
                    ),
                )
            allowed_actions = normalized
        namespace = build_mcp_tools(executor, self.mcp_tool_name, allowed=allowed_actions)
        internal_tools[self.mcp_tool_name] = namespace
        
        # Keep client reference so we can shut it down later
        self._mcp_client = client

    def inspect(self, verbose: str = "regular") -> str | dict:
        """
        Return available MCP actions.
        
        Args:
            verbose: "minimal" (just action names), "regular" (with descriptions),
                    or "full" (include allowed/available info)
        
        Returns:
            str if verbose is "minimal" or "regular", dict for "full"
        """
        from cortex._engine.mcp.compiler import MCPCompiler
        from cortex._engine.mcp.client import MCPClient
        
        compiler = MCPCompiler(
            tool_name=self.mcp_tool_name,
            command=self.command_or_url,
            args=self.args,
            env_keys=list(self.env.keys()),
        )
        
        manifest = compiler.load_cache()
        if not manifest:
            client = MCPClient(self.command_or_url, args=self.args, env=self.env)
            try:
                client.start()
                server_info = client.initialize()
                tools_list = client.list_tools()
                manifest = compiler.compile(tools_list, server_info)
            finally:
                client.stop()
        
        available_actions = []
        for tool in manifest.get("tools", []):
            mcp_name = tool.get("mcp_name", "")
            available_actions.append(mcp_name)
        
        if verbose == "minimal":
            return ", ".join(available_actions)
        
        elif verbose == "regular":
            lines = [f"\n📋 MCP Server: {self.mcp_tool_name}", "=" * 70]
            for tool in manifest.get("tools", []):
                mcp_name = tool.get("mcp_name", "")
                description = tool.get("description", "")
                lines.append(f"  • {mcp_name}")
                lines.append(f"    └─ {description[:60]}{'...' if len(description) > 60 else ''}")
            
            lines.extend(["", "=" * 70, f"Total: {len(available_actions)} actions", ""])
            return "\n".join(lines)
        
        else:  # full
            return {
                "server": self.mcp_tool_name,
                "available": available_actions,
                "allowed": self.effective_allowed_actions(),
                "total": len(available_actions),
                "auth_type": self.auth_type.value if hasattr(self, 'auth_type') else None
            }

    def close(self):
        """Shut down the MCP server when closing the connection."""
        if hasattr(self, '_mcp_client') and self._mcp_client:
            self._mcp_client.stop()


