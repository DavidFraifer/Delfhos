"""
RPC Protocol — JSON-RPC-style message definitions for sandbox ↔ host communication.

Messages are newline-delimited JSON (NDJSON) over a Unix Domain Socket.
Each line is a complete JSON object terminated by ``\\n``.

Message flow
------------
Container → Host:
    tool_call       Request execution of a tool method (gmail.send, sql.query, …)
    print_output    Forward a print() call for real-time streaming
    execution_done  Signal that code execution finished (success or error)

Host → Container:
    execute         Send code + manifest to run
    tool_result     Return the result of a tool_call
    cancel          Ask container to abort execution
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------

def encode_message(msg: dict) -> bytes:
    """Serialize a message dict to an NDJSON line."""
    return json.dumps(msg, default=str).encode("utf-8") + b"\n"


def decode_message(line: bytes) -> dict:
    """Deserialize an NDJSON line to a message dict."""
    return json.loads(line.decode("utf-8").strip())


# ---------------------------------------------------------------------------
# Host → Container messages
# ---------------------------------------------------------------------------

def msg_execute(
    code: str,
    manifest: Dict[str, Any],
    request_id: Optional[str] = None,
) -> dict:
    """Tell the container to execute *code* with the given tool manifest."""
    return {
        "type": "execute",
        "id": request_id or uuid.uuid4().hex,
        "code": code,
        "manifest": manifest,
    }


def msg_tool_result(
    call_id: str,
    result: Any = None,
    error: Optional[str] = None,
) -> dict:
    """Return the result of a ``tool_call`` back to the container."""
    return {
        "type": "tool_result",
        "call_id": call_id,
        "result": result,
        "error": error,
    }


def msg_cancel() -> dict:
    """Ask the container to abort execution."""
    return {"type": "cancel"}


# ---------------------------------------------------------------------------
# Container → Host messages
# ---------------------------------------------------------------------------

def msg_tool_call(
    tool_name: str,
    method_name: str,
    kwargs: Dict[str, Any],
    call_id: Optional[str] = None,
) -> dict:
    """Request execution of ``tool_name.method_name(**kwargs)`` on the host."""
    return {
        "type": "tool_call",
        "call_id": call_id or uuid.uuid4().hex,
        "tool": tool_name,
        "method": method_name,
        "kwargs": kwargs,
    }


def msg_print_output(text: str) -> dict:
    """Forward printed output to the host for real-time streaming."""
    return {
        "type": "print_output",
        "text": text,
    }


def msg_execution_done(
    success: bool,
    result: Any = None,
    output: str = "",
    error: Optional[str] = None,
    execution_time: float = 0.0,
    output_files: Optional[Dict] = None,
) -> dict:
    """Signal that code execution has completed."""
    return {
        "type": "execution_done",
        "success": success,
        "result": result,
        "output": output,
        "error": error,
        "execution_time": execution_time,
        "output_files": output_files or {},
    }
