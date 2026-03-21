"""
MCP Connection Class

The public interface for integrating any Model Context Protocol server.
Supports shorthand resolution:
  MCP("server-github") -> "npx -y @modelcontextprotocol/server-github"
"""

import json
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from cortex._engine.connection import AuthType
from .base import BaseConnection, _PrettyInspectDict


class _InspectDescriptor:
    """Descriptor allowing .inspect() to work on both MCP class and instances."""
    
    def __get__(self, obj, objtype=None):
        if obj is None:
            # Called on class: MCP.inspect(server="...")
            return objtype._class_inspect
        else:
            # Called on instance: mcp_instance.inspect()
            return lambda verbose=False: obj._do_inspect(verbose=verbose)


class MCP(BaseConnection):
    """
    Connect to any Model Context Protocol (MCP) server and use it as a native Delfhos tool.
    
    Example (GitHub integration):
        github_tool = MCP("server-github", env={"GITHUB_TOKEN": "..."})
        agent = Agent(tools=[github_tool], llm="gemini-3.1-flash-lite-preview")
        agent.run("Create a new issue in my org/repo with title 'Bug: ...'")
    
    Server formats supported:
      1. Short name:      MCP("server-github") — resolves to official @modelcontextprotocol pkg
      2. Scoped npm:      MCP("@org/server-foo") — runs via npx
      3. Full command:    MCP("npx -y custom-server --arg=value") — executes as-is
      4. Remote SSE URL:  MCP("https://mcp.example.com/sse") — connects via HTTP
    
    Args:
        server: Server identifier (short name, npm package, full command, or URL).
        args: Extra CLI arguments appended to the server command.
        env: Environment variables (e.g., {"GITHUB_TOKEN": "...", "DB_URL": "..."}).
        headers: HTTP headers for SSE connections (e.g., {"Authorization": "Bearer ..."})
        name: Custom label for this connection (default: auto-derived from server name).
        allow: Restrict which server actions are exposed to the agent (e.g., ["search", "read"]).
        confirm: Require human approval before executing listed actions (e.g., ["create_issue", "delete_file"]).
                 Use the same action names shown by MCP.inspect().
        cache: If True, reuse ~/delfhos/mcp_cache/ to skip introspection on next run.
    """
    
    # TOOL_NAME is overridden dynamically per instance
    TOOL_NAME = "mcp"
    ALLOWED_ACTIONS: Optional[List[str]] = None
    _KNOWN_REQUIRED_ENV_KEYS = {
        "server-github": ["GITHUB_TOKEN"],
        "github": ["GITHUB_TOKEN"],
        "server-gitlab": ["GITLAB_TOKEN"],
        "gitlab": ["GITLAB_TOKEN"],
        "server-notion": ["NOTION_API_KEY"],
        "notion": ["NOTION_API_KEY"],
        "server-slack": ["SLACK_BOT_TOKEN"],
        "slack": ["SLACK_BOT_TOKEN"],
        "server-linear": ["LINEAR_API_KEY"],
        "linear": ["LINEAR_API_KEY"],
        "server-jira": ["JIRA_API_TOKEN"],
        "jira": ["JIRA_API_TOKEN"],
        "server-google-drive": ["GOOGLE_API_KEY"],
        "server-openai": ["OPENAI_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
        "server-anthropic": ["ANTHROPIC_API_KEY"],
        "anthropic": ["ANTHROPIC_API_KEY"],
    }

    @staticmethod
    def _normalize_action(value: str) -> str:
        return str(value).strip().lower().replace("-", "_")

    def _detect_required_env_keys(self) -> List[str]:
        """Best-effort detection of required env keys for known MCP servers."""
        identity = f"{self.raw_server} {self.command_or_url} {self.mcp_tool_name}".lower()
        for marker, keys in self._KNOWN_REQUIRED_ENV_KEYS.items():
            if marker in identity:
                return list(keys)
        return []

    @classmethod
    def _class_inspect(cls, server: str, verbose: bool = False, env: Optional[Dict[str, str]] = None, headers: Optional[Dict[str, str]] = None, args: Optional[List[str]] = None, cache: bool = True) -> dict:
        """
        Inspect MCP actions using class-style calls.
        
        Args:
            server: MCP server identifier (short name, npm package, command, or URL).
            verbose: If False (default), returns available method names.
                     If True, returns detailed method descriptions.
            env: Environment variables (e.g., API keys).
            headers: HTTP headers for SSE connections.
            args: Command line arguments for the server.
            cache: If True, uses cached manifest if available.
        
        Returns:
            dict with server information and available actions
        
        Example::
        
            print(MCP.inspect(server="server-filesystem"))  # See filesystem actions
            print(MCP.inspect(server="server-filesystem", verbose=True))
            print(MCP.inspect(server="server-github", env={"GITHUB_TOKEN": "..."}))  # GitHub actions
        """
        temp = cls(server, env=env or {}, headers=headers or {}, args=args or [], cache=cache)
        return temp._do_inspect(verbose=verbose)
    
    inspect = _InspectDescriptor()

    def __init__(
        self,
        server: str,
        *,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        name: Optional[str] = None,
        allow: Optional[Union[str, List[str]]] = None,
        confirm: Union[bool, List[str], None] = True,
        cache: bool = True,
    ):
        """
        Args:
            server: Short name, scoped package, full command, or SSE URL.
            args: Additional command line arguments for the server.
            env: Environment variables (e.g., API keys).
            headers: HTTP headers for SSE connections.
            name: Custom name for this connection in Delfhos (defaults to auto-derived).
            allow: List of allowed action names exposed to the agent.
            confirm: List of action names requiring human approval (use names from MCP.inspect()).
            cache: If True, uses ~/delfhos/mcp_cache/ to skip introspection on next run.
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
            allow=allow,
            confirm=confirm,
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

        The manifest is automatically cached (~/delfhos/mcp_cache/) for faster runs.
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
        if self.allow is not None:
            normalized = {self._normalize_action(a) for a in self.allow}
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
        namespace = build_mcp_tools(executor, self.mcp_tool_name, allow=allowed_actions)
        internal_tools[self.mcp_tool_name] = namespace
        
        # Keep client reference so we can shut it down later
        self._mcp_client = client

    def _do_inspect(self, verbose: bool = False) -> dict:
        """
        Private helper for inspecting this MCP server instance.
        
        Use mcp.inspect() instead (available on both class and instance).
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

        connection_setup = {
            "server_input": {
                "value": self.raw_server,
                "resolved": self.command_or_url,
            },
            "required_env_keys": self._detect_required_env_keys(),
            "args_format": ["<arg1>", "<arg2>", "--flag=value"],
            "env_format": {"ENV_VAR_NAME": "value"},
            "headers_format": {"Header-Name": "value", "Authorization": "Bearer <TOKEN>"},
            "authentication": {
                "type": "env_or_headers",
                "description": "MCP auth is passed via env vars or HTTP headers depending on server requirements.",
            },
            "used_in_this_connection": {
                "args": list(self.args),
                "env": dict(self.env),
                "headers": dict(self.headers),
            },
        }
        
        if not verbose:
            return _PrettyInspectDict(
                {
                    "server": self.mcp_tool_name,
                    "methods": available_actions,
                    "total": len(available_actions),
                    "auth_type": self.auth_type.value if hasattr(self, 'auth_type') else None,
                    "connection_setup": connection_setup,
                }
            )

        allow_actions = self.effective_allowed_actions()
        methods = []
        for tool in manifest.get("tools", []):
            methods.append(
                {
                    "name": tool.get("mcp_name", ""),
                    "description": tool.get("description", ""),
                }
            )

        return _PrettyInspectDict(
            {
                "server": self.mcp_tool_name,
                "allowed": allow_actions,
                "methods": methods,
                "total": len(available_actions),
                "auth_type": self.auth_type.value if hasattr(self, 'auth_type') else None,
                "connection_setup": {
                    **connection_setup,
                    "examples": [
                        {
                            "use_case": "Local filesystem MCP",
                            "python": 'MCP("server-filesystem", args=["."])',
                        },
                        {
                            "use_case": "GitHub MCP with token in env",
                            "python": 'MCP("server-github", env={"GITHUB_TOKEN": "ghp_..."})',
                        },
                        {
                            "use_case": "Remote SSE MCP with bearer token",
                            "python": 'MCP("https://example.com/sse", headers={"Authorization": "Bearer <TOKEN>"})',
                        },
                    ],
                },
            }
        )

    def close(self):
        """Shut down the MCP server when closing the connection."""
        if hasattr(self, '_mcp_client') and self._mcp_client:
            self._mcp_client.stop()


