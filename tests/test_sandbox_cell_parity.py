"""
Parity tests: the in-container agent_runner uses the same cell-execution model
as the non-sandbox python_executor, and the cell-checkpoint fields survive the
RPC round trip back to the host.

agent_runner imports `proxy_libraries` (a container-local module), so we add the
container directory to sys.path before importing it.
"""

import json
import os
import sys

import pytest

_CONTAINER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "cortex", "_engine", "core", "sandbox", "container",
)
sys.path.insert(0, _CONTAINER_DIR)

import agent_runner as R                                  # noqa: E402
from cortex._engine.core.python_executor import split_into_cells as host_split  # noqa: E402


# ── split parity ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", [
    "a = 1\nb = 2\nprint(a + b)",
    "x = 1\ny = await tool(x)\nprint(y)",
    "total = (1 +\n         2 + 3)",
    "async def main():\n    r = await tool()\n    return r",
    "v = 5\nreturn v * 2",
])
def test_split_matches_host(code):
    host = [(c.source, c.has_await, c.terminal) for c in host_split(code)]
    cont = [(c.source, c.has_await, c.terminal) for c in R._split_into_cells(code)]
    assert host == cont


# ── execute_code behaviour parity ─────────────────────────────────────────────

async def _exec(code, ns):
    """Run execute_code with the protected baseline = the namespace as given."""
    return await R.execute_code(code, ns, dict(ns))


@pytest.mark.asyncio
async def test_top_level_return_becomes_result():
    res = await _exec("value = 21\nreturn value * 2", {"print": print})
    assert res["success"] is True
    assert res["result"] == 42


@pytest.mark.asyncio
async def test_failure_reports_cell_fields_and_runs_awaited_once():
    calls = []

    async def tool():
        calls.append(1)
        return "fetched"

    ns = {"print": print, "tool": tool}
    res = await _exec("data = await tool()\nboom()", ns)

    assert res["success"] is False
    assert res["failed_cell_index"] == 1
    assert res["cells_total"] == 2
    assert "boom()" in res["pending_source"]
    assert calls == [1]                 # awaited work ran exactly once
    assert ns["data"] == "fetched"      # its result preserved in the namespace
    assert "data" in res["live_vars"]   # reported to the host for retry/rerun


@pytest.mark.asyncio
async def test_success_path_carries_no_cell_fields():
    res = await _exec("z = 1\nprint(z)", {"print": print})
    assert res["success"] is True
    assert "failed_cell_index" not in res
    assert "pending_source" not in res
    assert res["live_vars"] == ["z"]


# ── rerun() parity ────────────────────────────────────────────────────────────

def test_build_namespace_injects_rerun():
    from unittest.mock import Mock
    ns = R._build_namespace({}, {}, Mock(), {})
    assert "rerun" in ns and callable(ns["rerun"])


@pytest.mark.asyncio
async def test_rerun_signal_propagates_as_result():
    ns = {"print": print, "rerun": R._rerun}
    code = 'x = 5\nprint("did work")\nrerun(context="found 5", remaining="finish the rest")'
    res = await _exec(code, ns)
    assert res["success"] is True
    assert res["rerun_requested"] is True
    assert res["rerun_context"] == "found 5"
    assert res["rerun_remaining"] == "finish the rest"
    assert res["rerun_carry"] == []
    assert "did work" in res["output"]


@pytest.mark.asyncio
async def test_rerun_requires_remaining():
    ns = {"print": print, "rerun": R._rerun}
    res = await _exec('rerun(context="x")', ns)   # missing remaining → ValueError
    assert res["success"] is False
    assert "ValueError" in res["error"]
    assert "rerun_requested" not in res


# ── RPC propagation: container -> host ────────────────────────────────────────

class _FakeWriter:
    def __init__(self):
        self.buf = b""

    def write(self, data):
        self.buf += data

    async def drain(self):
        pass


@pytest.mark.asyncio
async def test_send_done_includes_cell_fields_only_when_present():
    from proxy_libraries import RPCClient

    # failure result with cell fields → present on the wire
    client = RPCClient("localhost:1")
    client._writer = _FakeWriter()
    failure = {
        "success": False, "result": None, "output": "", "error": "NameError: boom",
        "execution_time": 0.0, "failed_cell_index": 1, "cells_total": 2,
        "pending_source": "boom()",
    }
    await client.send_done(**failure, output_files={})
    msg = json.loads(client._writer.buf.decode())
    assert msg["failed_cell_index"] == 1
    assert msg["pending_source"] == "boom()"

    # success result → no cell fields leak onto the wire
    client2 = RPCClient("localhost:1")
    client2._writer = _FakeWriter()
    await client2.send_done(success=True, result=None, output="ok", output_files={})
    msg2 = json.loads(client2._writer.buf.decode())
    assert "failed_cell_index" not in msg2
    assert "pending_source" not in msg2


@pytest.mark.asyncio
async def test_send_done_propagates_rerun_fields():
    from proxy_libraries import RPCClient

    client = RPCClient("localhost:1")
    client._writer = _FakeWriter()
    rerun_result = {
        "success": True, "result": None, "output": "did work",
        "execution_time": 0.0, "rerun_requested": True,
        "rerun_context": "found 5", "rerun_remaining": "finish", "rerun_carry": [],
    }
    await client.send_done(**rerun_result, output_files={})
    msg = json.loads(client._writer.buf.decode())
    assert msg["rerun_requested"] is True
    assert msg["rerun_context"] == "found 5"
    assert msg["rerun_remaining"] == "finish"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
