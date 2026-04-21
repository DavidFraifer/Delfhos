#!/usr/bin/env python3
"""
Agent Runner — Container entrypoint for executing sandboxed agent code.

This script runs *inside* the Docker container.  It:

1. Connects to the host via Unix socket (RPC bridge)
2. Reads the ``execute`` message (code + manifest)
3. Builds a restricted namespace with proxy tool libraries
4. Wraps and ``exec()`` s the agent code
5. Sends the result back via ``execution_done``

Usage::

    python agent_runner.py /path/to/sandbox.sock
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import time
import uuid
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any, Dict

# proxy_libraries is copied into the container alongside this file
from proxy_libraries import RPCClient, build_proxy_libraries


# ── Safe builtins (mirrors python_executor.py) ────────────────────────

def _make_add_to_output_files(registry: dict) -> "Callable":
    """Return an add_to_output_files function that writes to /output/."""
    import json as _j
    import os as _o

    def add_to_output_files(name: str, content) -> str:
        """Save content as a file. Returns the container path (/output/<filename>)."""
        has_ext = "." in _o.path.basename(name)
        if isinstance(content, (dict, list)):
            ext = "" if has_ext else ".json"
            data = _j.dumps(content, indent=2, default=str).encode("utf-8")
        elif isinstance(content, bytes):
            ext = ""
            data = content
        elif isinstance(content, str):
            ext = "" if has_ext else ".txt"
            data = content.encode("utf-8")
        else:
            ext = "" if has_ext else ".txt"
            data = str(content).encode("utf-8")
        filename = name + ext
        path = f"/output/{filename}"
        with open(path, "wb") as f:
            f.write(data)
        registry[name] = filename
        print(f"[output] '{name}' saved → {filename}")
        return path

    return add_to_output_files


def _build_namespace(
    libraries: Dict[str, Any],
    manifest: Dict[str, Any],
    rpc_client: RPCClient,
    output_registry: dict,
) -> dict:
    """Build a restricted execution namespace with proxy tool libraries."""

    import json as _json
    import re as _re
    import datetime as _datetime
    import time as _time
    import math as _math
    import statistics as _statistics

    _original_json_loads = _json.loads

    def _safe_json_loads(obj, *args, **kwargs):
        if isinstance(obj, (dict, list)):
            return obj
        if isinstance(obj, str) and not obj.strip():
            return None
        return _original_json_loads(obj, *args, **kwargs)

    _json.loads = _safe_json_loads  # type: ignore[assignment]

    def _blocked_input(*args, **kwargs):
        raise RuntimeError("input() is not available in this environment.")

    # Capture buffer — replaced per-execution in execute_code()
    _stdout_buf = io.StringIO()

    def _make_print(buf: io.StringIO):
        """Return a print function that writes to *buf* and forwards to host."""
        async def _send():
            text = buf.getvalue()
            if text:
                try:
                    await rpc_client.send_print(text)
                except Exception:
                    pass

        def _print(*args, **kwargs):
            kwargs.pop("file", None)
            kwargs.setdefault("flush", True)
            print(*args, file=buf, **kwargs)
        return _print

    allowed_import_roots = set(manifest.get("allowed_imports", [
        "asyncio", "datetime", "json", "math", "pathlib", "re", "statistics", "time",
    ]))

    def _safe_import(name, *args, **kwargs):
        root = name.split(".", 1)[0]
        if root not in allowed_import_roots:
            raise RuntimeError(f"Import of module '{name}' is not allowed in this environment")
        return __import__(name, *args, **kwargs)

    namespace = {
        # Safe builtins
        "print": _make_print(_stdout_buf),
        "int": int, "float": float, "bool": bool, "str": str,
        "list": list, "dict": dict, "tuple": tuple, "set": set,
        "len": len, "sum": sum, "min": min, "max": max, "abs": abs,
        "round": round, "any": any, "all": all,
        "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
        "sorted": sorted, "reversed": reversed, "next": next, "iter": iter,
        "isinstance": isinstance, "issubclass": issubclass,
        "hasattr": hasattr, "getattr": getattr, "setattr": setattr,
        "callable": callable, "repr": repr, "format": format,
        "chr": chr, "ord": ord, "hash": hash, "id": id,
        "type": type, "object": object, "super": super,
        "bytes": bytes, "bytearray": bytearray, "frozenset": frozenset,
        "range": range,
        # Safe stdlib
        "json": _json, "asyncio": asyncio,
        "datetime": _datetime, "time": _time,
        "re": _re, "math": _math, "statistics": _statistics,
        "__import__": _safe_import,
        "Path": Path,
        # Exceptions
        "Exception": Exception, "ValueError": ValueError,
        "KeyError": KeyError, "TypeError": TypeError,
        "AttributeError": AttributeError, "IndexError": IndexError,
        "RuntimeError": RuntimeError, "StopIteration": StopIteration,
        "NotImplementedError": NotImplementedError,
        "ZeroDivisionError": ZeroDivisionError,
        "FileNotFoundError": FileNotFoundError,
        "OverflowError": OverflowError, "NameError": NameError,
        # Constants
        "None": None, "True": True, "False": False,
        "locals": locals,
        "input": _blocked_input,
        # Context
        "ctx": manifest.get("agent_context", {}),
        "task_id": manifest.get("task_id", ""),
    }

    # Restricted builtins snapshot
    _restricted = dict(namespace)
    namespace["__builtins__"] = _restricted

    # Inject proxy tool libraries
    namespace.update(libraries)
    namespace["__name__"] = "__agent_execution__"
    namespace["__file__"] = "agent_script.py"
    namespace["add_to_output_files"] = _make_add_to_output_files(output_registry)

    return namespace


# ── Code execution ────────────────────────────────────────────────────

async def execute_code(
    code: str,
    namespace: dict,
    timeout: float = 300,
) -> Dict[str, Any]:
    """Execute agent code in the restricted namespace and return results."""

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    # Re-bind print to fresh buffer
    def _capture_print(*args, **kwargs):
        kwargs.pop("file", None)
        kwargs.setdefault("flush", True)
        print(*args, file=stdout_buf, **kwargs)
    namespace["print"] = _capture_print

    start = time.time()

    try:
        code_to_wrap = code.rstrip() + "\n"

        # Auto-call uncalled async entrypoints
        if "async def main" in code_to_wrap and "await main(" not in code_to_wrap:
            code_to_wrap += "\nawait main()\n"
        elif "async def run" in code_to_wrap and "await run(" not in code_to_wrap:
            code_to_wrap += "\nawait run()\n"

        _baseline_keys = set(namespace.keys())

        def __export_locals__(l):
            namespace.update({
                k: v for k, v in l.items()
                if not k.startswith("_") and k not in _baseline_keys
            })
        namespace["__export_locals__"] = __export_locals__
        code_to_wrap += "\n__export_locals__(locals())\n"

        indent = "    "
        indented = "\n".join(
            indent + line if line.strip() else line
            for line in code_to_wrap.split("\n")
        )
        wrapped = f"async def __agent_task__():\n{indented}"

        compiled = compile(wrapped, "<string>", "exec")

        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(compiled, namespace)
            async_func = namespace.get("__agent_task__")
            if async_func:
                result = await asyncio.wait_for(async_func(), timeout=timeout)
            else:
                raise RuntimeError("Failed to create async task function")

        return {
            "success": True,
            "result": result,
            "output": stdout_buf.getvalue(),
            "error": None,
            "execution_time": time.time() - start,
        }

    except asyncio.TimeoutError:
        return {
            "success": False,
            "result": None,
            "output": stdout_buf.getvalue(),
            "error": f"Execution timeout after {timeout}s",
            "execution_time": time.time() - start,
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "result": None,
            "output": stdout_buf.getvalue(),
            "error": f"{type(e).__name__}: {e}",
            "execution_time": time.time() - start,
        }


# ── Main entrypoint ──────────────────────────────────────────────────

async def main(socket_path: str) -> None:
    """Connect to host, receive code, execute, report result."""
    rpc = RPCClient(socket_path)
    await rpc.connect()

    try:
        # Read the execute message from the host
        line = await rpc._reader.readline()
        if not line:
            return
        msg = json.loads(line.decode("utf-8").strip())

        if msg.get("type") != "execute":
            await rpc.send_done(
                success=False,
                error=f"Expected 'execute' message, got '{msg.get('type')}'",
            )
            return

        code = msg["code"]
        manifest = msg["manifest"]
        timeout = manifest.get("timeout", 300)

        # Build proxy libraries
        libraries = build_proxy_libraries(
            manifest.get("available_tools", []),
            rpc,
        )

        # Registry: name -> filename (populated by add_to_output_files)
        output_registry: dict = {}

        # Build namespace
        namespace = _build_namespace(libraries, manifest, rpc, output_registry)

        # Execute
        result = await execute_code(code, namespace, timeout=timeout)

        # Send result back, including any output files
        await rpc.send_done(**result, output_files=output_registry)

    except Exception as e:
        try:
            await rpc.send_done(success=False, error=f"Runner error: {e}")
        except Exception:
            pass
    finally:
        await rpc.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: agent_runner.py <socket_path>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
