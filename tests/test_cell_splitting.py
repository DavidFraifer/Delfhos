"""
Tests for Jupyter-style cell execution in python_executor.

Covers:
- split_into_cells: top-level statement splitting, await detection, multiline
  statements, top-level `return` rewrite, async-def bodies kept intact, fallback.
- execute(): a failing script keeps earlier (awaited) work, reports the failing
  cell index, and exposes pending_source = "only the work still left to do".
"""

import pytest
from unittest.mock import Mock

from cortex._engine.core.python_executor import (
    PythonExecutor,
    split_into_cells,
    _Cell,
)


# ── split_into_cells (pure) ───────────────────────────────────────────────────

class TestSplitIntoCells:
    def test_one_cell_per_top_level_statement(self):
        cells = split_into_cells("a = 1\nb = 2\nprint(a + b)")
        assert [c.source for c in cells] == ["a = 1", "b = 2", "print(a + b)"]
        assert all(c.has_await is False for c in cells)

    def test_await_detection(self):
        cells = split_into_cells("x = 1\ny = await tool(x)\nprint(y)")
        assert [c.has_await for c in cells] == [False, True, False]

    def test_multiline_statement_stays_one_cell(self):
        code = "total = (1 +\n         2 +\n         3)"
        cells = split_into_cells(code)
        assert len(cells) == 1
        # dedented but semantically identical
        assert "total = (1 +" in cells[0].source
        assert eval(cells[0].source.split("=", 1)[1]) == 6

    def test_async_def_body_is_not_split(self):
        code = "async def main():\n    a = 1\n    b = await tool()\n    return a + b"
        cells = split_into_cells(code)
        assert len(cells) == 1               # the whole def is one cell
        assert cells[0].source.startswith("async def main():")
        assert cells[0].terminal is False    # the return is inside the function

    def test_top_level_return_is_rewritten_and_terminal(self):
        cells = split_into_cells("x = 5\nreturn x * 2")
        assert cells[-1].terminal is True
        assert cells[-1].source == "__cell_result__ = (x * 2)"

    def test_top_level_bare_return(self):
        cells = split_into_cells("return")
        assert cells[0].source == "__cell_result__ = (None)"
        assert cells[0].terminal is True

    def test_syntax_error_propagates(self):
        with pytest.raises(SyntaxError):
            split_into_cells("def broken(:\n  pass")


# ── execute() checkpoint behaviour ────────────────────────────────────────────

def _make_executor():
    tm = Mock()
    tm.tools = {}
    tm.connection_to_tool = {}
    tm.get_tools = Mock(return_value={})
    tm.get_tool = Mock(return_value=None)
    tm.inspect = Mock(return_value={})
    tm.credentials_manager = Mock()
    tm.connections = {}
    return PythonExecutor(
        tool_manager=tm, task_id="t", agent_id="a",
        light_llm="l", heavy_llm="h",
    )


@pytest.mark.asyncio
async def test_top_level_return_becomes_result():
    ex = _make_executor()
    res = await ex.execute("value = 21\nreturn value * 2")
    assert res["success"] is True
    assert res["result"] == 42


@pytest.mark.asyncio
async def test_failure_reports_cell_and_pending_source():
    ex = _make_executor()
    code = "a = 1\nb = 2\nboom()\nc = 3"
    res = await ex.execute(code)
    assert res["success"] is False
    assert res["failed_cell_index"] == 2          # boom() is the 3rd statement
    assert res["cells_total"] == 4
    # pending = failed cell onward only; earlier statements are gone
    assert res["pending_source"] == "boom()\nc = 3"
    # earlier cells already applied to the shared namespace
    assert ex.namespace["a"] == 1 and ex.namespace["b"] == 2


@pytest.mark.asyncio
async def test_awaited_work_before_failure_runs_once_and_persists():
    """The core win: an awaited (expensive) call before the failure is NOT
    re-run, and its result is preserved for the retry."""
    ex = _make_executor()
    await ex.execute("calls = []")              # create namespace

    async def fake_tool():
        ex.namespace["calls"].append(1)
        return "fetched"

    ex.namespace["fake_tool"] = fake_tool

    res = await ex.execute("data = await fake_tool()\noops()")
    assert res["success"] is False
    assert res["failed_cell_index"] == 1
    assert "oops()" in res["pending_source"]
    assert ex.namespace["calls"] == [1]         # tool ran exactly once
    assert ex.namespace["data"] == "fetched"    # awaited result preserved


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
