"""
RPC Server — Host-side Unix-socket server for the Docker sandbox.

Listens on a Unix Domain Socket, receives tool-call requests from the
container's proxy libraries, dispatches them to the real tool library
instances running in the host process, and streams results back.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from typing import Any, Callable, Coroutine, Dict, Optional

from . import rpc_protocol as proto

logger = logging.getLogger(__name__)


class RPCServer:
    """
    Async Unix-socket server that bridges container ↔ host tool calls.

    Lifecycle
    ---------
    1. ``await server.start()`` — creates socket, starts listening
    2. Container connects and sends ``tool_call`` / ``print_output`` messages
    3. Server dispatches each ``tool_call`` to ``tool_dispatch_fn``
    4. ``await server.stop()`` — shuts down and removes socket file

    Parameters
    ----------
    tool_libraries : dict[str, Any]
        The real host-side tool library instances (gmail, sql, …).
    socket_path : str | None
        Where to bind the Unix socket.  ``None`` → auto temp path.
    on_print : callable | None
        Called with ``(text: str)`` for each ``print_output`` from the container.
    """

    def __init__(
        self,
        tool_libraries: Dict[str, Any],
        socket_path: Optional[str] = None,
        on_print: Optional[Callable[[str], None]] = None,
    ):
        self.tool_libraries = tool_libraries
        self.socket_path = socket_path or os.path.join(
            tempfile.mkdtemp(prefix="delfhos_rpc_"), "sandbox.sock"
        )
        self._on_print = on_print
        self._server: Optional[asyncio.AbstractServer] = None
        self._result_future: Optional[asyncio.Future] = None
        # Set by DockerSandbox before the container connects — the server
        # sends this as the first message when a client connects.
        self._pending_execute: Optional[dict] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> str:
        """Start the server and return the socket path."""
        # Ensure parent dir exists
        os.makedirs(os.path.dirname(self.socket_path), exist_ok=True)
        # Remove stale socket if present
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        self._result_future = asyncio.get_running_loop().create_future()
        self._server = await asyncio.start_unix_server(
            self._handle_client, path=self.socket_path
        )
        # Allow container user to connect
        os.chmod(self.socket_path, 0o777)
        logger.debug("RPC server listening on %s", self.socket_path)
        return self.socket_path

    async def wait_for_result(self) -> Dict[str, Any]:
        """Block until the container sends ``execution_done``."""
        if self._result_future is None:
            raise RuntimeError("Server not started")
        return await self._result_future

    async def stop(self) -> None:
        """Shut down the server and clean up the socket file."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        # Try to remove the temp directory
        parent = os.path.dirname(self.socket_path)
        try:
            os.rmdir(parent)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Connection handler
    # ------------------------------------------------------------------

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single container connection (one per execution)."""
        logger.debug("Container connected")
        try:
            # Send the pending execute message if one is queued
            if self._pending_execute is not None:
                writer.write(proto.encode_message(self._pending_execute))
                await writer.drain()
                self._pending_execute = None

            while True:
                line = await reader.readline()
                if not line:
                    break  # EOF — container disconnected

                try:
                    msg = proto.decode_message(line)
                except json.JSONDecodeError:
                    logger.warning("Malformed message from container: %r", line[:200])
                    continue

                msg_type = msg.get("type")

                if msg_type == "tool_call":
                    await self._handle_tool_call(msg, writer)
                elif msg_type == "print_output":
                    if self._on_print:
                        self._on_print(msg.get("text", ""))
                elif msg_type == "execution_done":
                    if self._result_future and not self._result_future.done():
                        self._result_future.set_result({
                            "success": msg.get("success", False),
                            "result": msg.get("result"),
                            "output": msg.get("output", ""),
                            "error": msg.get("error"),
                            "execution_time": msg.get("execution_time", 0.0),
                            "output_files": msg.get("output_files", {}),
                        })
                else:
                    logger.warning("Unknown message type from container: %s", msg_type)

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error in RPC client handler")
            if self._result_future and not self._result_future.done():
                self._result_future.set_result({
                    "success": False,
                    "result": None,
                    "output": "",
                    "error": "RPC server handler crashed",
                    "execution_time": 0.0,
                })
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Tool call dispatch
    # ------------------------------------------------------------------

    async def _handle_tool_call(self, msg: dict, writer: asyncio.StreamWriter) -> None:
        """
        Dispatch a tool call to the real host-side library and reply.

        The container sends::

            {"type":"tool_call", "call_id":"abc", "tool":"gmail",
             "method":"send", "kwargs":{"to":"…", "subject":"…"}}

        We look up ``self.tool_libraries["gmail"]``, call its ``.send(**kwargs)``,
        and write back a ``tool_result`` message.
        """
        call_id = msg.get("call_id", "?")
        tool_name = msg.get("tool", "")
        method_name = msg.get("method", "")
        kwargs = msg.get("kwargs", {})

        library = self.tool_libraries.get(tool_name)
        if library is None:
            reply = proto.msg_tool_result(
                call_id=call_id,
                error=f"Tool '{tool_name}' is not available",
            )
            writer.write(proto.encode_message(reply))
            await writer.drain()
            return

        method = getattr(library, method_name, None)
        if method is None:
            reply = proto.msg_tool_result(
                call_id=call_id,
                error=f"Tool '{tool_name}' has no method '{method_name}'",
            )
            writer.write(proto.encode_message(reply))
            await writer.drain()
            return

        try:
            if asyncio.iscoroutinefunction(method):
                result = await method(**kwargs)
            else:
                result = method(**kwargs)

            # Ensure the result is JSON-serialisable
            try:
                json.dumps(result, default=str)
            except (TypeError, ValueError):
                result = str(result)

            reply = proto.msg_tool_result(call_id=call_id, result=result)
        except Exception as e:
            reply = proto.msg_tool_result(call_id=call_id, error=str(e))

        writer.write(proto.encode_message(reply))
        await writer.drain()
