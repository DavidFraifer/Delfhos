"""Type stubs for delfhos.tools.mcp — MCP server integration."""

from typing import Any, Dict, List, Optional, Union

class MCP:
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
        cache: If True, reuse ~/delfhos/mcp_cache/ to skip introspection on next run.
    """
    TOOL_NAME: str
    ALLOWED_ACTIONS: Optional[List[str]]
    raw_server: str
    command_or_url: str
    args: List[str]
    env: Dict[str, str]
    headers: Dict[str, str]
    cache: bool
    mcp_tool_name: str

    def __init__(
        self,
        server: str,
        *,
        args: Optional[List[str]] = ...,
        env: Optional[Dict[str, str]] = ...,
        headers: Optional[Dict[str, str]] = ...,
        name: Optional[str] = ...,
        allow: Optional[Union[str, List[str]]] = ...,
        confirm: Union[bool, List[str], None] = ...,
        cache: bool = ...,
    ) -> None: ...

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
        ...

    def inspect(self, verbose: bool = False) -> dict:
        """
        List available actions on this MCP server.

        Works on both class and instance:
          - MCP.inspect(server="server-filesystem") — class-style
          - mcp.inspect() or mcp.inspect(verbose=True) — instance-style

        Args:
            verbose: If True, returns detailed method descriptions.

        Returns:
            dict with server information and available actions.
            Includes `connection_setup` with args/env/headers formats and
            authentication examples, plus `required_env_keys` when known.

        Example::

            # Class-style inspection
            print(MCP.inspect(server="server-filesystem"))

            # Instance-style inspection
            mcp = MCP("server-github", env={"GITHUB_TOKEN": "..."})
            print(mcp.inspect(verbose=True))
        """
        ...

    def get_available_actions(self) -> List[str]:
        """Instance helper for discovering available MCP actions."""
        ...

    def effective_allowed_actions(self) -> Union[List[str], str]:
        """Return the effective action policy: "all" or list of allowed actions."""
        ...

    def compile(self) -> None:
        """Start the server, pull schemas, compile into Delfhos format, and register tools."""
        ...

    def close(self) -> None:
        """Shut down the MCP server when closing the connection."""
        ...

__all__ = ["MCP"]
