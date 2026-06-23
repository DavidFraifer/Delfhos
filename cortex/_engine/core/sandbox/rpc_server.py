"""
RPC Server — Host-side TCP server for the Docker sandbox.

Listens on a TCP loopback port, receives tool-call requests from the
container's proxy libraries (reaching the host via ``host.docker.internal``),
dispatches them to the real tool library instances running in the host
process, and streams results back.

TCP is used instead of Unix sockets because bind-mounting Unix sockets is
unreliable on macOS Docker Desktop (Errno 95 / Operation not supported).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine, Dict, Optional

from . import rpc_protocol as proto

logger = logging.getLogger(__name__)


class RPCServer:
    """
    Async TCP server that bridges container ↔ host tool calls.

    Lifecycle
    ---------
    1. ``await server.start()`` — binds a TCP port, starts listening
    2. Container connects and sends ``tool_call`` / ``print_output`` messages
    3. Server dispatches each ``tool_call`` to the matching tool library
    4. ``await server.stop()`` — shuts down

    Parameters
    ----------
    tool_libraries : dict[str, Any]
        The real host-side tool library instances (gmail, sql, …).
    on_print : callable | None
        Called with ``(text: str)`` for each ``print_output`` from the container.
    """

    def __init__(
        self,
        tool_libraries: Dict[str, Any],
        on_print: Optional[Callable[[str], None]] = None,
    ):
        self.tool_libraries = tool_libraries
        self.host = "127.0.0.1"
        self.port: int = 0
        self._on_print = on_print
        self._server: Optional[asyncio.AbstractServer] = None
        self._result_future: Optional[asyncio.Future] = None
        # Set by DockerSandbox before the container connects — the server
        # sends this as the first message when a client connects.
        self._pending_execute: Optional[dict] = None
        # The live container connection's writer, captured on connect, so the
        # host can send further execute messages over the same socket (the
        # container is kept alive across a task's rerun/retry passes).
        self._writer: Optional[asyncio.StreamWriter] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> int:
        """Start the server and return the bound TCP port."""
        self._result_future = asyncio.get_running_loop().create_future()
        self._server = await asyncio.start_server(
            self._handle_client, host=self.host, port=0
        )
        # Capture the OS-assigned port
        sock = self._server.sockets[0]
        self.port = sock.getsockname()[1]
        logger.debug("RPC server listening on %s:%d", self.host, self.port)
        return self.port

    async def wait_for_result(self) -> Dict[str, Any]:
        """Block until the container sends ``execution_done``."""
        if self._result_future is None:
            raise RuntimeError("Server not started")
        return await self._result_future

    def reset_result(self) -> None:
        """Arm a fresh result future before sending the next execute message."""
        self._result_future = asyncio.get_running_loop().create_future()

    async def send_execute(self, msg: dict) -> None:
        """Send a follow-up execute message to the already-connected container."""
        if self._writer is None:
            raise RuntimeError("No container connection to send execute to")
        self._writer.write(proto.encode_message(msg))
        await self._writer.drain()

    async def send_close(self) -> None:
        """Ask the container to exit its run loop (best-effort)."""
        if self._writer is None:
            return
        try:
            self._writer.write(proto.encode_message({"type": "close"}))
            await self._writer.drain()
        except Exception:
            pass

    async def stop(self) -> None:
        """Shut down the server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    # ------------------------------------------------------------------
    # Connection handler
    # ------------------------------------------------------------------

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle the container connection (kept alive across rerun/retry passes)."""
        logger.debug("Container connected")
        self._writer = writer
        try:
            # Send the pending (first) execute message if one is queued
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
                        done = {
                            "success": msg.get("success", False),
                            "result": msg.get("result"),
                            "output": msg.get("output", ""),
                            "error": msg.get("error"),
                            "execution_time": msg.get("execution_time", 0.0),
                            "output_files": msg.get("output_files", {}),
                        }
                        # Cell-checkpoint fields (present only on mid-script failure)
                        # and rerun fields (present only when code called rerun()),
                        # so the host retry/rerun paths match the non-sandbox executor.
                        for k in ("failed_cell_index", "cells_total", "pending_source",
                                  "rerun_requested", "rerun_context", "rerun_remaining",
                                  "rerun_carry", "live_vars"):
                            if msg.get(k) is not None:
                                done[k] = msg[k]
                        self._result_future.set_result(done)
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
