"""
Unit tests for OrchestratorTimingMixin.

Tests timing-entry creation, completion matching, deduplication, and the
`track_tool_usage` / `get_tools_used` / `get_tool_timings` ledger.
All tests run without a real LLM or network call.
"""
import asyncio
import time
import pytest
from unittest.mock import MagicMock, AsyncMock

from cortex._engine.core.orchestrator import Orchestrator


# ── Fixture ───────────────────────────────────────────────────────────────────

def make_orchestrator() -> Orchestrator:
    """Minimal orchestrator with no real LLM or logger I/O."""
    logger = MagicMock()
    logger.add_tokens = MagicMock()
    orch = Orchestrator(
        light_llm="gemini-2.0-flash",
        heavy_llm="gemini-2.0-flash",
        logger=logger,
        agent_id="test-agent",
    )
    return orch


# ── track_tool_usage ──────────────────────────────────────────────────────────

class TestTrackToolUsage:
    def test_records_first_entry(self):
        orch = make_orchestrator()
        orch.track_tool_usage("task-1", "gmail", "gpt-4o")
        entries = orch.get_tools_used("task-1")
        assert len(entries) == 1
        assert entries[0]["tool"] == "gmail"
        assert entries[0]["model"] == "gpt-4o"

    def test_deduplicates_same_tool_model(self):
        orch = make_orchestrator()
        orch.track_tool_usage("task-1", "gmail", "gpt-4o")
        orch.track_tool_usage("task-1", "gmail", "gpt-4o")
        assert len(orch.get_tools_used("task-1")) == 1

    def test_different_model_creates_separate_entry(self):
        orch = make_orchestrator()
        orch.track_tool_usage("task-1", "gmail", "gpt-4o")
        orch.track_tool_usage("task-1", "gmail", "gemini-2.0-flash")
        assert len(orch.get_tools_used("task-1")) == 2

    def test_different_tools_create_separate_entries(self):
        orch = make_orchestrator()
        orch.track_tool_usage("task-1", "gmail", None)
        orch.track_tool_usage("task-1", "sheets", None)
        tools = {e["tool"] for e in orch.get_tools_used("task-1")}
        assert tools == {"gmail", "sheets"}

    def test_empty_tool_name_is_ignored(self):
        orch = make_orchestrator()
        orch.track_tool_usage("task-1", "", None)
        assert orch.get_tools_used("task-1") == []

    def test_returns_defensive_copies(self):
        orch = make_orchestrator()
        orch.track_tool_usage("task-1", "sql", None)
        entries = orch.get_tools_used("task-1")
        entries[0]["tool"] = "mutated"
        # Original must be untouched
        assert orch.task_tools_used["task-1"][0]["tool"] == "sql"

    def test_different_task_ids_are_independent(self):
        orch = make_orchestrator()
        orch.track_tool_usage("task-A", "gmail", None)
        orch.track_tool_usage("task-B", "sheets", None)
        assert orch.get_tools_used("task-A")[0]["tool"] == "gmail"
        assert orch.get_tools_used("task-B")[0]["tool"] == "sheets"
        assert orch.get_tools_used("task-C") == []


# ── _track_tool_timing_internal ───────────────────────────────────────────────

class TestTrackToolTimingInternal:
    def test_starting_entry_has_none_duration(self):
        orch = make_orchestrator()
        entry = orch._track_tool_timing_internal("t1", "prefilter", None, None, "desc", is_starting=True)
        assert entry is not None
        assert entry["duration"] is None
        assert entry["status"] == "running"
        assert entry["tool"] == "prefilter"

    def test_completion_updates_matching_starting_entry(self):
        orch = make_orchestrator()
        orch._track_tool_timing_internal("t1", "prefilter", None, None, "desc", is_starting=True)
        orch._track_tool_timing_internal("t1", "prefilter", 1.5, "model-x", "desc", is_starting=False)

        entries = orch.get_tool_timings("t1")
        assert len(entries) == 1
        assert entries[0]["duration"] == 1.5
        assert entries[0]["status"] == "success"
        assert entries[0]["model"] == "model-x"

    def test_orphan_completion_creates_new_entry(self):
        orch = make_orchestrator()
        # No starting entry — orphan completion
        entry = orch._track_tool_timing_internal("t1", "sql_schema", 2.0, None, "fetching", is_starting=False)
        assert entry is not None
        assert entry["duration"] == 2.0
        entries = orch.get_tool_timings("t1")
        assert len(entries) == 1

    def test_duplicate_completion_within_1s_is_suppressed(self):
        orch = make_orchestrator()
        # First entry
        orch._track_tool_timing_internal("t1", "sql_schema", 2.0, None, "fetching", is_starting=False)
        # Near-duplicate within 1s (same tool, description, similar duration)
        result = orch._track_tool_timing_internal("t1", "sql_schema", 2.05, None, "fetching", is_starting=False)
        # Duplicate should return None to suppress callback
        assert result is None
        assert len(orch.get_tool_timings("t1")) == 1

    def test_metadata_stored_on_starting_entry(self):
        orch = make_orchestrator()
        meta = {"_tool_action": "SEND", "_tool_trace_args": {"to": "alice@co.com"}}
        entry = orch._track_tool_timing_internal("t1", "gmail", None, None, "sending email", is_starting=True, metadata=meta)
        assert entry["ui_metadata"]["_tool_action"] == "SEND"

    def test_wait_time_stored_on_completion_entry(self):
        orch = make_orchestrator()
        orch._track_tool_timing_internal("t1", "awaiting_approval", None, None, "Approval", is_starting=True)
        entry = orch._track_tool_timing_internal("t1", "awaiting_approval", 30.0, None, "Approval", is_starting=False, wait_time=30.0)
        assert entry["wait_time"] == 30.0

    def test_multiple_tools_same_task(self):
        orch = make_orchestrator()
        orch._track_tool_timing_internal("t1", "prefilter", None, None, "A", is_starting=True)
        orch._track_tool_timing_internal("t1", "prefilter", 0.3, None, "A", is_starting=False)
        orch._track_tool_timing_internal("t1", "llm_code_generation", None, None, "B", is_starting=True)
        orch._track_tool_timing_internal("t1", "llm_code_generation", 2.1, None, "B", is_starting=False)
        entries = orch.get_tool_timings("t1")
        assert len(entries) == 2


# ── track_tool_timing_async callback ─────────────────────────────────────────

class TestTrackToolTimingAsyncCallback:
    def test_async_callback_is_awaited(self):
        orch = make_orchestrator()
        received = []

        async def cb(task_id, entry):
            received.append((task_id, entry["tool"]))

        orch.tool_timing_callback = cb

        async def run():
            await orch.track_tool_timing_async("t1", "prefilter", 0.5, None, "desc")

        asyncio.run(run())
        assert ("t1", "prefilter") in received

    def test_sync_callback_is_called(self):
        orch = make_orchestrator()
        received = []
        orch.tool_timing_callback = lambda tid, entry: received.append(entry["tool"])
        orch.track_tool_timing("t1", "prefilter", 0.5, None, "desc")
        assert "prefilter" in received

    def test_bad_callback_does_not_raise(self):
        orch = make_orchestrator()

        def bad_cb(tid, entry):
            raise RuntimeError("callback boom")

        orch.tool_timing_callback = bad_cb
        # Should not propagate the exception
        orch.track_tool_timing("t1", "prefilter", 0.5, None, "desc")


# ── _cleanup_wait_times_if_needed ─────────────────────────────────────────────

class TestCleanupWaitTimes:
    def test_no_cleanup_below_limit(self):
        orch = make_orchestrator()
        for i in range(10):
            orch.wait_times[f"task-{i}"] = float(i)
        orch._cleanup_wait_times_if_needed()
        assert len(orch.wait_times) == 10

    def test_cleanup_trims_to_half_when_over_limit(self):
        orch = make_orchestrator()
        limit = orch.MAX_WAIT_TIMES_ENTRIES
        for i in range(limit + 10):
            orch.wait_times[f"task-{i:04d}"] = 0.0
        orch._cleanup_wait_times_if_needed()
        assert len(orch.wait_times) <= limit

    def test_cleanup_keeps_most_recent_keys(self):
        orch = make_orchestrator()
        limit = orch.MAX_WAIT_TIMES_ENTRIES
        keys = [f"task-{i:04d}" for i in range(limit + 5)]
        for k in keys:
            orch.wait_times[k] = 0.0
        orch._cleanup_wait_times_if_needed()
        # The last inserted keys (alphabetically highest) should survive
        assert "task-" + f"{limit + 4:04d}" in orch.wait_times
