"""
Proxy Libraries — Container-side stubs that forward tool calls to the host via RPC.

These objects live *inside* the Docker container and are injected into the
agent code's namespace in place of the real tool libraries.  Every method
call is serialised to JSON and sent over the Unix socket to the host-side
``RPCServer``, which dispatches it to the real library.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, Optional


class RPCClient:
    """
    Async client that talks to the host-side ``RPCServer`` over a Unix socket.

    Used by :class:`ProxyToolLibrary` to forward tool calls.
    """

    def __init__(self, socket_path: str):
        self._socket_path = socket_path
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._listen_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(
            self._socket_path
        )
        self._listen_task = asyncio.create_task(self._listen_loop())

    async def close(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    async def call(self, tool_name: str, method_name: str, kwargs: Dict[str, Any]) -> Any:
        """Send a tool_call and wait for the host to reply with tool_result."""
        call_id = uuid.uuid4().hex
        msg = {
            "type": "tool_call",
            "call_id": call_id,
            "tool": tool_name,
            "method": method_name,
            "kwargs": kwargs,
        }
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[call_id] = future

        self._writer.write(json.dumps(msg, default=str).encode("utf-8") + b"\n")
        await self._writer.drain()

        result_msg = await future
        if result_msg.get("error"):
            raise RuntimeError(result_msg["error"])
        return result_msg.get("result")

    async def send_print(self, text: str) -> None:
        """Forward a print() call to the host."""
        msg = {"type": "print_output", "text": text}
        self._writer.write(json.dumps(msg).encode("utf-8") + b"\n")
        await self._writer.drain()

    async def send_done(
        self,
        success: bool,
        result: Any = None,
        output: str = "",
        error: Optional[str] = None,
        execution_time: float = 0.0,
        output_files: Optional[dict] = None,
    ) -> None:
        """Signal execution completion to the host."""
        msg = {
            "type": "execution_done",
            "success": success,
            "result": result,
            "output": output,
            "error": error,
            "execution_time": execution_time,
            "output_files": output_files or {},
        }
        # Best-effort serialisation of result
        try:
            line = json.dumps(msg, default=str).encode("utf-8") + b"\n"
        except (TypeError, ValueError):
            msg["result"] = str(result)
            line = json.dumps(msg, default=str).encode("utf-8") + b"\n"
        self._writer.write(line)
        await self._writer.drain()

    # ------------------------------------------------------------------

    async def _listen_loop(self) -> None:
        """Read messages from the host and resolve pending futures."""
        while True:
            line = await self._reader.readline()
            if not line:
                break
            try:
                msg = json.loads(line.decode("utf-8").strip())
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            if msg_type == "tool_result":
                call_id = msg.get("call_id")
                future = self._pending.pop(call_id, None)
                if future and not future.done():
                    future.set_result(msg)
            elif msg_type == "cancel":
                # Host asked us to stop — raise in all pending calls
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(asyncio.CancelledError())
                self._pending.clear()
                break


class ProxyToolLibrary:
    """
    Drop-in replacement for a host-side tool library (e.g. GmailLibrary).

    Every attribute access returns an async callable that serialises the
    call to JSON and sends it over the RPC bridge.
    """

    def __init__(self, tool_name: str, rpc_client: RPCClient):
        self._tool_name = tool_name
        self._rpc = rpc_client

    def __getattr__(self, method_name: str):
        if method_name.startswith("_"):
            raise AttributeError(method_name)

        async def _proxy(**kwargs):
            return await self._rpc.call(self._tool_name, method_name, kwargs)

        _proxy.__name__ = f"{self._tool_name}.{method_name}"
        _proxy.__qualname__ = _proxy.__name__
        return _proxy


def build_proxy_libraries(
    available_tools: list[str],
    rpc_client: RPCClient,
) -> Dict[str, ProxyToolLibrary]:
    """Create a proxy library for each tool listed in the manifest."""
    return {name: ProxyToolLibrary(name, rpc_client) for name in available_tools}
