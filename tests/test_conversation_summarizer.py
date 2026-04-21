"""
Unit tests for ConversationSummarizer and related helpers.

LLM calls are mocked — no network or API key required.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cortex._engine.core.conversation_summarizer import (
    ConversationSummarizer,
    summarize_conversation,
    _run_coro_sync,
)


def _make_summarizer(**kwargs) -> ConversationSummarizer:
    logger = MagicMock()
    logger.add_tokens = MagicMock()
    defaults = dict(
        light_llm="gemini-2.0-flash",
        agent_id="test-agent",
        logger=logger,
    )
    defaults.update(kwargs)
    return ConversationSummarizer(**defaults)


# ── _format_conversation ──────────────────────────────────────────────────────

class TestFormatConversation:
    def setup_method(self):
        self.s = _make_summarizer()

    def test_user_role_labelled(self):
        conv = [{"role": "user", "content": "Hello"}]
        result = self.s._format_conversation(conv)
        assert result == "USER: Hello"

    def test_assistant_role_labelled(self):
        conv = [{"role": "assistant", "content": "Hi there"}]
        result = self.s._format_conversation(conv)
        assert result == "ASSISTANT: Hi there"

    def test_system_role_labelled(self):
        conv = [{"role": "system", "content": "You are helpful"}]
        result = self.s._format_conversation(conv)
        assert result == "SYSTEM: You are helpful"

    def test_unknown_role_uppercased(self):
        conv = [{"role": "function", "content": "result"}]
        result = self.s._format_conversation(conv)
        assert result.startswith("FUNCTION:")

    def test_multiple_messages_joined_with_blank_lines(self):
        conv = [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "A"},
        ]
        result = self.s._format_conversation(conv)
        assert "\n\n" in result
        assert "USER: Q" in result
        assert "ASSISTANT: A" in result

    def test_empty_conversation(self):
        assert self.s._format_conversation([]) == ""

    def test_missing_content_defaults_to_empty(self):
        conv = [{"role": "user"}]
        result = self.s._format_conversation(conv)
        assert result == "USER: "


# ── _get_last_user_message ─────────────────────────────────────────────────────

class TestGetLastUserMessage:
    def setup_method(self):
        self.s = _make_summarizer()

    def test_returns_last_user_message(self):
        conv = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
        assert self.s._get_last_user_message(conv) == "second"

    def test_no_user_messages_returns_last_message(self):
        conv = [{"role": "assistant", "content": "only assistant"}]
        assert self.s._get_last_user_message(conv) == "only assistant"

    def test_empty_conversation_returns_empty(self):
        assert self.s._get_last_user_message([]) == ""

    def test_skips_intermediate_assistant_messages(self):
        conv = [
            {"role": "user", "content": "task one"},
            {"role": "assistant", "content": "done"},
            {"role": "assistant", "content": "done 2"},
        ]
        assert self.s._get_last_user_message(conv) == "task one"


# ── summarize_conversation (async) ────────────────────────────────────────────

class TestSummarizeConversationAsync:
    @pytest.mark.asyncio
    async def test_empty_conversation_returns_empty(self):
        s = _make_summarizer()
        result = await s.summarize_conversation([])
        assert result == ""

    @pytest.mark.asyncio
    async def test_single_user_message_returned_directly(self):
        """Single user message skips the LLM — returned verbatim."""
        s = _make_summarizer()
        conv = [{"role": "user", "content": "Send me the weekly report"}]
        result = await s.summarize_conversation(conv)
        assert result == "Send me the weekly report"

    @pytest.mark.asyncio
    async def test_multi_turn_uses_llm(self):
        s = _make_summarizer()
        conv = [
            {"role": "user", "content": "What were my last invoices?"},
            {"role": "assistant", "content": "You had 3 invoices."},
            {"role": "user", "content": "Send them to accounting@co.com"},
        ]
        with patch(
            "cortex._engine.core.conversation_summarizer.llm_completion_async",
            new_callable=AsyncMock,
            return_value=("Forward last 3 invoices to accounting@co.com", {"input_tokens": 30, "output_tokens": 10}),
        ):
            result = await s.summarize_conversation(conv)
        assert "accounting" in result

    @pytest.mark.asyncio
    async def test_max_history_limits_context(self):
        """Only the last max_history messages are sent to the LLM."""
        s = _make_summarizer()
        # 20 messages: first 18 are old, last 2 are recent
        conv = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"} for i in range(20)]

        captured_prompt = {}

        async def fake_llm(prompt, model, **kwargs):
            captured_prompt["prompt"] = prompt
            return ("task summary", {"input_tokens": 5, "output_tokens": 5})

        with patch(
            "cortex._engine.core.conversation_summarizer.llm_completion_async",
            side_effect=fake_llm,
        ):
            await s.summarize_conversation(conv, max_history=4)

        # Only last 4 messages should appear in prompt
        prompt_text = captured_prompt["prompt"]
        assert "msg 0" not in prompt_text  # old messages excluded
        assert "msg 19" in prompt_text     # recent messages included

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_last_user_message(self):
        """If the LLM raises, summarizer returns the last user message."""
        s = _make_summarizer()
        conv = [
            {"role": "user", "content": "first ask"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "follow-up"},
        ]
        with patch(
            "cortex._engine.core.conversation_summarizer.llm_completion_async",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API down"),
        ):
            result = await s.summarize_conversation(conv)
        assert result == "follow-up"

    @pytest.mark.asyncio
    async def test_tokens_logged_when_logger_and_task_id_provided(self):
        logger = MagicMock()
        logger.add_tokens = MagicMock()
        s = _make_summarizer(logger=logger)
        conv = [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "A"},
            {"role": "user", "content": "follow up"},
        ]
        with patch(
            "cortex._engine.core.conversation_summarizer.llm_completion_async",
            new_callable=AsyncMock,
            return_value=("summarized task", {"input_tokens": 20, "output_tokens": 8}),
        ):
            await s.summarize_conversation(conv, task_id="task-abc")
        logger.add_tokens.assert_called_once()
        call_kwargs = logger.add_tokens.call_args
        assert "task-abc" in call_kwargs[0]  # first positional arg is task_id


# ── summarize_conversation (standalone function) ──────────────────────────────

class TestStandaloneSummarizeConversation:
    def test_single_message_returns_content(self):
        conv = [{"role": "user", "content": "Do X"}]
        result = summarize_conversation(conv, light_llm="gemini-2.0-flash")
        assert result == "Do X"

    def test_empty_conversation_returns_empty(self):
        result = summarize_conversation([], light_llm="gemini-2.0-flash")
        assert result == ""

    def test_multi_turn_calls_llm(self):
        conv = [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "A"},
            {"role": "user", "content": "follow up"},
        ]
        with patch(
            "cortex._engine.core.conversation_summarizer.llm_completion_async",
            new_callable=AsyncMock,
            return_value=("summarized", {"input_tokens": 5, "output_tokens": 5}),
        ):
            result = summarize_conversation(conv, light_llm="gemini-2.0-flash")
        assert result == "summarized"


# ── _run_coro_sync ────────────────────────────────────────────────────────────

class TestRunCoroSync:
    def test_runs_coroutine_outside_event_loop(self):
        async def coro():
            return 42

        result = _run_coro_sync(coro())
        assert result == 42

    def test_propagates_exception_from_coroutine(self):
        async def coro():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            _run_coro_sync(coro())

    def test_returns_none_when_coroutine_returns_none(self):
        async def coro():
            return None

        assert _run_coro_sync(coro()) is None
