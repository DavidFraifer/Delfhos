"""
Unit tests for OrchestratorSchedulerMixin.

Covers: start/stop lifecycle, receive_message thread-safety,
and the _cleanup_wait_times_if_needed LRU eviction.
No real LLM or network calls are made.
"""
import asyncio
import threading
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from cortex._engine.core.orchestrator import Orchestrator


def make_orchestrator() -> Orchestrator:
    logger = MagicMock()
    logger.add_tokens = MagicMock()
    logger.start_task = MagicMock()
    logger.complete_task = MagicMock()
    logger.active_tasks = {}
    return Orchestrator(
        light_llm="gemini-2.0-flash",
        heavy_llm="gemini-2.0-flash",
        logger=logger,
        agent_id="test-agent",
    )


# ── Lifecycle ─────────────────────────────────────────────────────────────────

class TestSchedulerLifecycle:
    def test_start_sets_running_flag(self):
        orch = make_orchestrator()
        orch.start()
        try:
            assert orch.running is True
        finally:
            orch.stop()

    def test_stop_clears_running_flag(self):
        orch = make_orchestrator()
        orch.start()
        orch.stop()
        assert orch.running is False

    def test_double_start_is_idempotent(self):
        orch = make_orchestrator()
        orch.start()
        orch.start()  # second call is a no-op
        try:
            assert orch.running is True
        finally:
            orch.stop()

    def test_scheduler_thread_is_daemon(self):
        orch = make_orchestrator()
        orch.start()
        try:
            assert orch.scheduler_thread is not None
            assert orch.scheduler_thread.daemon is True
        finally:
            orch.stop()

    def test_scheduler_ready_event_is_set_after_start(self):
        orch = make_orchestrator()
        orch.start()
        try:
            assert orch._scheduler_ready.is_set()
        finally:
            orch.stop()

    def test_async_queue_is_available_after_start(self):
        orch = make_orchestrator()
        orch.start()
        try:
            assert orch._async_queue is not None
            assert orch._scheduler_loop is not None
        finally:
            orch.stop()

    def test_loop_and_queue_cleared_after_stop(self):
        orch = make_orchestrator()
        orch.start()
        orch.stop()
        assert orch._scheduler_loop is None
        assert orch._async_queue is None


# ── receive_message ───────────────────────────────────────────────────────────

class TestReceiveMessage:
    def test_returns_true_when_running(self):
        orch = make_orchestrator()
        orch.start()
        try:
            result = orch.receive_message("hello")
            assert result is True
        finally:
            orch.stop()

    def test_returns_false_when_stopped(self):
        orch = make_orchestrator()
        result = orch.receive_message("hello")
        assert result is False

    def test_message_reaches_process_pipeline(self):
        """Messages enqueued via receive_message are processed by the scheduler."""
        orch = make_orchestrator()
        processed = threading.Event()

        async def fake_process(message):
            processed.set()

        orch._process_message_async = fake_process
        orch.start()
        try:
            orch.receive_message("test-task")
            processed.wait(timeout=2.0)
            assert processed.is_set(), "Message was not processed within 2 seconds"
        finally:
            orch.stop()

    def test_multiple_messages_are_all_processed(self):
        orch = make_orchestrator()
        seen = set()
        lock = threading.Lock()
        done = threading.Event()
        expected_count = 3

        async def fake_process(message):
            with lock:
                seen.add(message)
                if len(seen) >= expected_count:
                    done.set()

        orch._process_message_async = fake_process
        orch.start()
        try:
            for i in range(expected_count):
                orch.receive_message(f"task-{i}")
            done.wait(timeout=3.0)
            assert len(seen) == expected_count
        finally:
            orch.stop()


# ── _cleanup_wait_times_if_needed (also tested in timing tests, brief here) ──

class TestCleanupBehavior:
    def test_cleanup_runs_without_error_on_empty(self):
        orch = make_orchestrator()
        orch._cleanup_wait_times_if_needed()  # should not raise

    def test_cleanup_trims_over_limit(self):
        orch = make_orchestrator()
        limit = orch.MAX_WAIT_TIMES_ENTRIES
        for i in range(limit + 20):
            orch.wait_times[f"t{i:05d}"] = 0.0
        orch._cleanup_wait_times_if_needed()
        assert len(orch.wait_times) <= limit
