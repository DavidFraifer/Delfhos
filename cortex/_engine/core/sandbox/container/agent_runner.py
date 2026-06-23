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
import ast
import io
import sys
import textwrap
import time
import uuid
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# proxy_libraries is copied into the container alongside this file
from proxy_libraries import RPCClient, build_proxy_libraries


# ── Cell splitting (mirrors python_executor.split_into_cells) ──────────

@dataclass
class _Cell:
    """One executable unit = one top-level statement of the generated script."""
    source: str
    has_await: bool
    terminal: bool = False          # a top-level `return` → stop after this cell
    status: str = "pending"         # pending | ok | failed


_PARSE_WRAP = "async def __m__():\n"


class _RerunSignal(Exception):
    """Raised by rerun() in generated code to request a replanning pass.

    Mirrors python_executor._RerunSignal so Docker and local behave the same.
    """

    def __init__(self, context: str, remaining: str, carry: list):
        super().__init__("rerun requested")
        self.context = context
        self.remaining = remaining
        self.carry = carry


def _rerun(context: str = "", remaining: str = "", carry: list = None):
    if not isinstance(remaining, str) or not remaining.strip():
        raise ValueError(
            "rerun() requires a non-empty 'remaining' argument describing the work still left to do."
        )
    raise _RerunSignal(
        context=str(context),
        remaining=remaining.strip(),
        carry=list(carry) if carry else [],
    )


def _contains_await(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Await) for n in ast.walk(node))


def _live_vars(namespace: dict, protected: dict) -> list:
    """User-defined variable names currently in the namespace (for the host's
    rerun/retry prompts) — everything not part of the protected baseline."""
    return sorted(k for k in namespace if k not in protected and not k.startswith("_"))


def _split_into_cells(code: str) -> List[_Cell]:
    """Split a generated script into ordered cells (one per top-level statement).

    Wraps solely to parse so top-level ``await``/``return`` are legal, then
    recovers each statement's source. A top-level ``return X`` becomes
    ``__cell_result__ = (X)`` and marks the cell terminal. Raises SyntaxError
    for genuinely invalid code (handled by the caller).
    """
    src = code if code.endswith("\n") else code + "\n"
    wrapped = _PARSE_WRAP + textwrap.indent(src, "    ")
    func = ast.parse(wrapped).body[0]

    cells: List[_Cell] = []
    for node in func.body:
        if isinstance(node, ast.Return):
            value = (
                textwrap.dedent(ast.get_source_segment(wrapped, node.value))
                if node.value is not None else "None"
            )
            cells.append(_Cell(f"__cell_result__ = ({value})",
                               _contains_await(node), terminal=True))
        else:
            segment = ast.get_source_segment(wrapped, node)
            if segment is None:
                continue
            cells.append(_Cell(textwrap.dedent(segment), _contains_await(node)))
    return cells or [_Cell(code, _contains_await(func))]


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
    namespace["rerun"] = _rerun

    return namespace


# ── Code execution ────────────────────────────────────────────────────

async def execute_code(
    code: str,
    namespace: dict,
    protected: dict,
    timeout: float = 300,
) -> Dict[str, Any]:
    """Execute agent code in the restricted namespace and return results.

    ``protected`` is the baseline name→value snapshot (builtins, tool libraries,
    special vars) captured once by main() before any user code ran; it is
    restored after every cell so user code can't clobber it, and is used to tell
    user variables apart from the baseline for ``live_vars``.
    """

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    # Re-bind print to this run's fresh buffer. The baseline `protected` snapshot
    # holds the *previous* print, so override it here — otherwise the per-cell
    # restore (`namespace.update(protected)`) would revert print mid-script and
    # later cells' output would be lost. Mirrors the local executor's ordering.
    def _capture_print(*args, **kwargs):
        kwargs.pop("file", None)
        kwargs.setdefault("flush", True)
        print(*args, file=stdout_buf, **kwargs)
    namespace["print"] = _capture_print
    protected = {**protected, "print": _capture_print}

    start = time.time()
    failed_index: Optional[int] = None
    cells: List[_Cell] = []

    try:
        cells = _split_into_cells(code)

        # Auto-call uncalled async entrypoints
        for entry in ("main", "run"):
            if f"async def {entry}" in code and f"await {entry}(" not in code:
                cells.append(_Cell(f"await {entry}()", True))
                break

        async def _run_cells() -> Any:
            nonlocal failed_index
            namespace.pop("__cell_result__", None)
            for i, cell in enumerate(cells):
                try:
                    compiled = compile(cell.source, f"<cell {i}>", "exec",
                                       flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                    coro = eval(compiled, namespace)   # coroutine iff top-level await
                    if coro is not None:
                        await coro
                    cell.status = "ok"
                except Exception:
                    cell.status = "failed"
                    failed_index = i
                    raise
                finally:
                    namespace.update(protected)
                if cell.terminal:
                    break
            return namespace.pop("__cell_result__", None)

        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            result = await asyncio.wait_for(_run_cells(), timeout=timeout)

        return {
            "success": True,
            "result": result,
            "output": stdout_buf.getvalue(),
            "error": None,
            "execution_time": time.time() - start,
            "live_vars": _live_vars(namespace, protected),
        }

    except asyncio.TimeoutError:
        return {
            "success": False,
            "result": None,
            "output": stdout_buf.getvalue(),
            "error": f"Execution timeout after {timeout}s",
            "execution_time": time.time() - start,
            "live_vars": _live_vars(namespace, protected),
        }
    except _RerunSignal as rs:
        return {
            "success": True,
            "rerun_requested": True,
            "rerun_context": rs.context,
            "rerun_remaining": rs.remaining,
            "rerun_carry": rs.carry,
            "result": None,
            "output": stdout_buf.getvalue(),
            "error": None,
            "execution_time": time.time() - start,
            "live_vars": _live_vars(namespace, protected),
        }
    except Exception as e:
        cell_fields: Dict[str, Any] = {}
        if failed_index is not None:
            cell_fields = {
                "failed_cell_index": failed_index,
                "cells_total": len(cells),
                "pending_source": "\n".join(c.source for c in cells[failed_index:]),
            }
        return {
            "success": False,
            "result": None,
            "output": stdout_buf.getvalue(),
            "error": f"{type(e).__name__}: {e}",
            "execution_time": time.time() - start,
            "live_vars": _live_vars(namespace, protected),
            **cell_fields,
        }


# ── Main entrypoint ──────────────────────────────────────────────────

def _install_packages(packages: list) -> Optional[str]:
    """Pip-install user-requested packages into /packages. Returns an error string
    on failure, or None on success."""
    if not packages:
        return None
    import subprocess as _sp
    install_dir = "/packages"
    res = _sp.run(
        [sys.executable, "-m", "pip", "install", "--target", install_dir,
         "--quiet", "--no-cache-dir"] + packages,
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        return f"Failed to install packages {packages}:\n{res.stderr}"
    if install_dir not in sys.path:
        sys.path.insert(0, install_dir)
    return None


async def main(endpoint: str) -> None:
    """Connect to host, then loop: receive an execute message, run it against the
    PERSISTENT namespace, report the result. Repeats until the host sends a
    ``close`` message (or the connection drops), so variables assigned in one
    execution survive into the next (rerun/retry) — parity with the local executor.
    """
    rpc = RPCClient(endpoint)
    await rpc.connect()

    namespace: Optional[dict] = None
    protected: dict = {}
    output_registry: dict = {}

    try:
        while True:
            msg = await rpc.next_execute()
            if msg is None or msg.get("type") == "close":
                break
            if msg.get("type") != "execute":
                await rpc.send_done(
                    success=False,
                    error=f"Expected 'execute' message, got '{msg.get('type')}'",
                )
                continue

            code = msg["code"]
            manifest = msg["manifest"]
            timeout = manifest.get("timeout", 300)

            # First execution: install packages, build libraries + namespace once,
            # then snapshot the protected baseline. Reused for every later pass.
            if namespace is None:
                err = _install_packages(manifest.get("packages_to_install", []))
                if err:
                    await rpc.send_done(success=False, error=err)
                    continue
                libraries = build_proxy_libraries(manifest.get("available_tools", []), rpc)
                namespace = _build_namespace(libraries, manifest, rpc, output_registry)
                protected = {k: namespace[k] for k in set(namespace.keys())}

            output_registry.clear()   # report only this execution's output files
            result = await execute_code(code, namespace, protected, timeout=timeout)
            await rpc.send_done(**result, output_files=dict(output_registry))

    except Exception as e:
        try:
            await rpc.send_done(success=False, error=f"Runner error: {e}")
        except Exception:
            pass
    finally:
        await rpc.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: agent_runner.py <host:port>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
