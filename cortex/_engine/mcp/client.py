"""
MCP JSON-RPC Client

Low-level client that communicates with MCP servers via:
  - stdio transport (subprocess stdin/stdout)
  - SSE transport (HTTP Server-Sent Events)

Handles the MCP protocol lifecycle:
  initialize → tools/list → tools/call → shutdown
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional
from delfhos.errors import MCPConnectionError, ToolExecutionError


class MCPClient:
    """
    JSON-RPC 2.0 client for MCP servers.
    
    Supports two transports:
      - stdio: starts a subprocess and communicates via stdin/stdout
      - sse: connects to a remote HTTP endpoint (future)
    """

    def __init__(self, command: str, args: List[str] = None, env: Dict[str, str] = None):
        """
        Args:
            command: Full command to start the MCP server (e.g., "npx -y @modelcontextprotocol/server-github")
            args: Additional arguments to append to the command
            env: Environment variables to set for the subprocess
        """
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._read_buffer = ""
        self.server_info: Dict[str, Any] = {}
        self.protocol_version: str = ""

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the MCP server subprocess."""
        if self._process and self._process.poll() is None:
            return  # Already running

        # Build the full command
        cmd_parts = self.command.split()
        cmd_parts.extend(self.args)

        # Merge environment
        proc_env = os.environ.copy()
        proc_env.update(self.env)

        try:
            self._process = subprocess.Popen(
                cmd_parts,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=proc_env,
                bufsize=0,
            )
        except Exception as e:
            raise MCPConnectionError(
                server=self.command,
                detail=str(e)
            )

    def stop(self) -> None:
        """Gracefully shut down the MCP server."""
        if not self._process:
            return
        
        try:
            # Send shutdown notification
            self._send_notification("notifications/cancelled", {})
        except Exception:
            pass

        try:
            self._process.terminate()
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=2)
        finally:
            self._process = None

    def is_running(self) -> bool:
        """Check if the server process is alive."""
        return self._process is not None and self._process.poll() is None

    # ── JSON-RPC Transport ────────────────────────────────────────────────────

    def _next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _send_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a JSON-RPC request and wait for the response."""
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise MCPConnectionError(
                server=self.command,
                detail="MCP server not running. Call start() first."
            )

        request_id = self._next_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        # Write the request as a single JSON line
        request_bytes = (json.dumps(request) + "\n").encode("utf-8")
        self._process.stdin.write(request_bytes)
        self._process.stdin.flush()

        # Read the response (line-delimited JSON-RPC)
        response = self._read_response(request_id, timeout=30)
        
        if "error" in response:
            err = response["error"]
            raise ToolExecutionError(
                tool_name=self.command,
                detail=f"MCP error {err.get('code', '?')}: {err.get('message', 'Unknown error')}"
            )

        return response.get("result", {})

    def _send_notification(self, method: str, params: Dict[str, Any] = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or not self._process.stdin:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        notification_bytes = (json.dumps(notification) + "\n").encode("utf-8")
        self._process.stdin.write(notification_bytes)
        self._process.stdin.flush()

    def _read_response(self, expected_id: int, timeout: float = 30) -> Dict[str, Any]:
        """Read lines from stdout until we get a response matching expected_id."""
        deadline = time.time() + timeout
        
        while time.time() < deadline:
            line = self._read_line(timeout=max(0.1, deadline - time.time()))
            if line is None:
                continue
            
            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Skip notifications (no "id" field)
            if "id" not in msg:
                continue

            if msg.get("id") == expected_id:
                return msg

        raise MCPConnectionError(
            server=self.command,
            detail=f"MCP server did not respond within {timeout}s"
        )

    def _read_line(self, timeout: float = 1.0) -> Optional[str]:
        """Read a single line from stdout with timeout."""
        import select
        
        if not self._process or not self._process.stdout:
            return None

        # Use select for non-blocking read on the pipe
        try:
            ready, _, _ = select.select([self._process.stdout], [], [], timeout)
            if ready:
                line = self._process.stdout.readline()
                if line:
                    return line.decode("utf-8", errors="replace")
        except (ValueError, OSError):
            pass

        return None

    # ── MCP Protocol Methods ──────────────────────────────────────────────────

    def initialize(self) -> Dict[str, Any]:
        """
        Perform the MCP initialization handshake.
        
        Returns:
            Server capabilities and info.
        """
        result = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "delfhos",
                "version": "0.4.0"
            }
        })

        self.server_info = result.get("serverInfo", {})
        self.protocol_version = result.get("protocolVersion", "unknown")

        # Send initialized notification
        self._send_notification("notifications/initialized")

        return result

    def list_tools(self) -> List[Dict[str, Any]]:
        """
        Get the list of available tools from the MCP server.
        
        Returns:
            List of tool definitions with name, description, and inputSchema.
        """
        result = self._send_request("tools/list")
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: Dict[str, Any] = None) -> Any:
        """
        Execute a tool on the MCP server.
        
        Args:
            name: Tool name (as returned by tools/list)
            arguments: Tool arguments matching the inputSchema
            
        Returns:
            Tool execution result.
        """
        result = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments or {}
        })
        return result

    # ── Context Manager ───────────────────────────────────────────────────────

    def __enter__(self):
        self.start()
        self.initialize()
        return self

    def __exit__(self, *args):
        self.stop()
