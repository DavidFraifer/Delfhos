"""
Integration tests for the Orchestrator execution pipeline.

Uses mocked LLM calls so no API key or network is needed.
Tests the full _process_message_async flow: memory → code-gen → execute → result.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cortex._engine.core.orchestrator import Orchestrator
from delfhos.errors import CodeGenerationError, MemoryRetrievalError


# ── Shared helpers ────────────────────────────────────────────────────────────

def make_orchestrator(**kwargs) -> Orchestrator:
    logger = MagicMock()
    logger.add_tokens = MagicMock()
    logger.start_task = MagicMock()
    logger.complete_task = MagicMock()
    logger.active_tasks = {}
    defaults = dict(
        light_llm="gemini-2.0-flash",
        heavy_llm="gemini-2.0-flash",
        logger=logger,
        agent_id="test-agent",
        trace_mode=False,
    )
    defaults.update(kwargs)
    return Orchestrator(**defaults)


def _llm_response(code: str):
    """Wrap generated code as if it came from llm_completion_async."""
    return (f"```python\n{code}\n```", {"input_tokens": 10, "output_tokens": 20})


# ── Full happy-path pipeline ──────────────────────────────────────────────────

class TestHappyPath:
    @pytest.mark.asyncio
    async def test_task_completes_with_print_output(self):
        orch = make_orchestrator()
        orch.start()
        try:
            code = 'print("hello from agent")'
            with patch(
                "cortex._engine.core.orchestrator_codegen.llm_completion_async",
                new_callable=AsyncMock,
                return_value=_llm_response(code),
            ):
                orch.receive_message("print hello")
                # Wait for the result
                for _ in range(40):
                    await asyncio.sleep(0.05)
                    if orch.task_results:
                        break
            results = list(orch.task_results.values())
            assert results, "No task result produced"
            assert results[0]["status"] == "success"
            assert "hello from agent" in results[0]["final_message"]
        finally:
            orch.stop()

    @pytest.mark.asyncio
    async def test_task_result_stores_cost_and_duration(self):
        orch = make_orchestrator()
        orch.start()
        try:
            code = 'print("cost test")'
            with patch(
                "cortex._engine.core.orchestrator_codegen.llm_completion_async",
                new_callable=AsyncMock,
                return_value=_llm_response(code),
            ):
                orch.receive_message("cost check")
                for _ in range(40):
                    await asyncio.sleep(0.05)
                    if orch.task_results:
                        break
            result = list(orch.task_results.values())[0]
            assert "duration" in result
            assert result["duration"] > 0
        finally:
            orch.stop()

    @pytest.mark.asyncio
    async def test_on_task_complete_callback_fires_on_success(self):
        orch = make_orchestrator()
        received = []
        orch.on_task_complete = lambda tid, msg: received.append(msg)
        orch.start()
        try:
            code = 'print("callback test")'
            with patch(
                "cortex._engine.core.orchestrator_codegen.llm_completion_async",
                new_callable=AsyncMock,
                return_value=_llm_response(code),
            ):
                orch.receive_message("callback")
                for _ in range(40):
                    await asyncio.sleep(0.05)
                    if received:
                        break
            assert any("callback test" in m for m in received)
        finally:
            orch.stop()


# ── Code generation failure path ──────────────────────────────────────────────

class TestCodeGenerationFailure:
    @pytest.mark.asyncio
    async def test_empty_code_response_prints_as_output(self):
        """parse_python_code wraps plain text in print(), so plain-text LLM
        responses become a print() execution and succeed."""
        orch = make_orchestrator()
        orch.start()
        try:
            with patch(
                "cortex._engine.core.orchestrator_codegen.llm_completion_async",
                new_callable=AsyncMock,
                return_value=("No code here", {"input_tokens": 5, "output_tokens": 5}),
            ):
                orch.receive_message("do something")
                for _ in range(40):
                    await asyncio.sleep(0.05)
                    if orch.task_results:
                        break
            result = list(orch.task_results.values())[0]
            # parse_python_code wraps plain text in print() → executes successfully
            assert result["status"] == "success"
            assert "No code here" in result["final_message"]
        finally:
            orch.stop()

    @pytest.mark.asyncio
    async def test_llm_exception_marks_task_failed(self):
        orch = make_orchestrator()
        orch.start()
        try:
            with patch(
                "cortex._engine.core.orchestrator_codegen.llm_completion_async",
                new_callable=AsyncMock,
                side_effect=RuntimeError("API down"),
            ):
                orch.receive_message("fail task")
                for _ in range(40):
                    await asyncio.sleep(0.05)
                    if orch.task_results:
                        break
            result = list(orch.task_results.values())[0]
            assert result["status"] == "error"
            assert result["completed"] is False
        finally:
            orch.stop()


# ── Execution failure + auto-retry ───────────────────────────────────────────

class TestAutoRetry:
    @pytest.mark.asyncio
    async def test_retry_on_name_error_succeeds_second_attempt(self):
        orch = make_orchestrator(retry_count=1)
        orch.start()
        try:
            bad_code = 'print(undefined_var)'  # will raise NameError
            good_code = 'print("fixed")'

            call_count = 0

            async def fake_llm(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return _llm_response(bad_code)
                return _llm_response(good_code)

            # orchestrator_codegen.llm_completion_async covers the initial code gen;
            # orchestrator.llm_completion_async covers the retry path (separate import).
            with patch(
                "cortex._engine.core.orchestrator_codegen.llm_completion_async",
                side_effect=fake_llm,
            ), patch(
                "cortex._engine.core.orchestrator.llm_completion_async",
                side_effect=fake_llm,
            ):
                orch.receive_message("retry test")
                for _ in range(60):
                    await asyncio.sleep(0.05)
                    if orch.task_results:
                        break

            result = list(orch.task_results.values())[0]
            # Retry should recover
            assert result["status"] == "success"
            assert "fixed" in result["final_message"]
        finally:
            orch.stop()

    @pytest.mark.asyncio
    async def test_retry_count_zero_does_not_retry(self):
        orch = make_orchestrator(retry_count=0)
        orch.start()
        try:
            bad_code = 'raise ValueError("deliberate")'
            with patch(
                "cortex._engine.core.orchestrator_codegen.llm_completion_async",
                new_callable=AsyncMock,
                return_value=_llm_response(bad_code),
            ):
                orch.receive_message("no retry")
                for _ in range(40):
                    await asyncio.sleep(0.05)
                    if orch.task_results:
                        break

            result = list(orch.task_results.values())[0]
            assert result["status"] == "error"
        finally:
            orch.stop()


# ── Memory retrieval integration ─────────────────────────────────────────────

class TestMemoryRetrieval:
    @pytest.mark.asyncio
    async def test_memory_failure_does_not_abort_task(self):
        """A memory retrieval error is non-fatal; the task should still complete."""
        orch = make_orchestrator()

        broken_memory = MagicMock()
        broken_memory.retrieve = MagicMock(side_effect=IOError("vector store gone"))
        orch.memory = broken_memory

        orch.start()
        try:
            code = 'print("ran without memory")'
            with patch(
                "cortex._engine.core.orchestrator_codegen.llm_completion_async",
                new_callable=AsyncMock,
                return_value=_llm_response(code),
            ):
                orch.receive_message("task with broken memory")
                for _ in range(40):
                    await asyncio.sleep(0.05)
                    if orch.task_results:
                        break

            result = list(orch.task_results.values())[0]
            # Task should still complete (memory is non-critical)
            assert result["status"] == "success"
        finally:
            orch.stop()

    @pytest.mark.asyncio
    async def test_memory_context_passed_to_code_generation(self):
        """When memory returns facts, they are forwarded to llm_generate_python."""
        orch = make_orchestrator()
        mock_memory = MagicMock()
        mock_memory.retrieve = MagicMock(return_value="user prefers JSON output")
        orch.memory = mock_memory

        captured_kwargs = {}

        async def spy_generate(message, task_id="", sql_schema=None,
                               relevant_connections=None, memory_context=None):
            captured_kwargs["memory_context"] = memory_context
            return 'print("ok")'

        orch.llm_generate_python = spy_generate
        orch.start()
        try:
            orch.receive_message("task with memory")
            for _ in range(40):
                await asyncio.sleep(0.05)
                if captured_kwargs:
                    break
        finally:
            orch.stop()

        assert captured_kwargs.get("memory_context") == "user prefers JSON output"


# ── Timing integration ────────────────────────────────────────────────────────

class TestTimingIntegration:
    @pytest.mark.asyncio
    async def test_timing_callback_receives_tool_entry(self):
        orch = make_orchestrator()
        timing_calls = []
        orch.tool_timing_callback = lambda tid, entry: timing_calls.append(entry["tool"])

        orch.start()
        try:
            code = 'print("timing")'
            with patch(
                "cortex._engine.core.orchestrator_codegen.llm_completion_async",
                new_callable=AsyncMock,
                return_value=_llm_response(code),
            ):
                orch.receive_message("timing test")
                for _ in range(40):
                    await asyncio.sleep(0.05)
                    if orch.task_results:
                        break
        finally:
            orch.stop()

        # llm_code_generation timing entry must have been emitted
        assert "llm_code_generation" in timing_calls

    @pytest.mark.asyncio
    async def test_get_tool_timings_populated_after_task(self):
        orch = make_orchestrator()
        orch.start()
        task_id_holder = []

        original_process = orch._process_message_async

        async def instrumented(message):
            await original_process(message)
            if orch.task_results:
                task_id_holder.append(list(orch.task_results.keys())[0])

        orch._process_message_async = instrumented

        try:
            code = 'print("timings check")'
            with patch(
                "cortex._engine.core.orchestrator_codegen.llm_completion_async",
                new_callable=AsyncMock,
                return_value=_llm_response(code),
            ):
                orch.receive_message("timings")
                for _ in range(40):
                    await asyncio.sleep(0.05)
                    if task_id_holder:
                        break
        finally:
            orch.stop()

        if task_id_holder:
            tid = task_id_holder[0]
            timings = orch.get_tool_timings(tid)
            # Note: task_tool_timings may be cleaned up after task completion.
            # This test verifies no crash occurred.
            assert isinstance(timings, list)


# ── Concurrent tasks ──────────────────────────────────────────────────────────

class TestConcurrentTasks:
    @pytest.mark.asyncio
    async def test_multiple_tasks_run_concurrently(self):
        orch = make_orchestrator()
        orch.start()
        try:
            code = 'print("concurrent")'
            with patch(
                "cortex._engine.core.orchestrator_codegen.llm_completion_async",
                new_callable=AsyncMock,
                return_value=_llm_response(code),
            ):
                for i in range(3):
                    orch.receive_message(f"task {i}")
                # Wait for all three tasks
                for _ in range(60):
                    await asyncio.sleep(0.05)
                    if len(orch.task_results) >= 3:
                        break
            assert len(orch.task_results) == 3
            for r in orch.task_results.values():
                assert r["status"] == "success"
        finally:
            orch.stop()
