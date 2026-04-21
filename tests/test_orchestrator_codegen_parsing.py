"""
Unit tests for the pure-parsing helpers in OrchestratorCodegenMixin.

All helpers tested here are deterministic string/index transforms —
no LLM, network, or filesystem I/O is needed.
"""
import pytest
from unittest.mock import MagicMock

from cortex._engine.core.orchestrator import Orchestrator


def make_orchestrator() -> Orchestrator:
    logger = MagicMock()
    logger.add_tokens = MagicMock()
    return Orchestrator(
        light_llm="gemini-2.0-flash",
        heavy_llm="gemini-2.0-flash",
        logger=logger,
        agent_id="test-agent",
    )


# ── _normalize_connection_filter_response ────────────────────────────────────

class TestNormalizeConnectionFilterResponse:
    def setup_method(self):
        self.orch = make_orchestrator()

    def test_strips_output_prefix(self):
        assert self.orch._normalize_connection_filter_response("OUTPUT: 1,2") == "1,2"

    def test_strips_connections_prefix(self):
        assert self.orch._normalize_connection_filter_response("CONNECTIONS: 3") == "3"

    def test_strips_selected_prefix(self):
        assert self.orch._normalize_connection_filter_response("SELECTED: 1") == "1"

    def test_uppercases_result(self):
        assert self.orch._normalize_connection_filter_response("none") == "NONE"

    def test_strips_whitespace(self):
        assert self.orch._normalize_connection_filter_response("  1, 2  ") == "1, 2"

    def test_empty_string_returns_empty(self):
        assert self.orch._normalize_connection_filter_response("") == ""

    def test_none_returns_empty(self):
        assert self.orch._normalize_connection_filter_response(None) == ""


# ── _compact_prefilter_memory_context ────────────────────────────────────────

class TestCompactPrefilterMemoryContext:
    def setup_method(self):
        self.orch = make_orchestrator()

    def test_returns_empty_for_none(self):
        assert self.orch._compact_prefilter_memory_context(None) == ""

    def test_returns_empty_for_empty_string(self):
        assert self.orch._compact_prefilter_memory_context("") == ""

    def test_returns_empty_for_non_string(self):
        assert self.orch._compact_prefilter_memory_context(42) == ""  # type: ignore[arg-type]

    def test_trims_to_max_lines(self):
        max_lines = self.orch.PREFILTER_MEMORY_MAX_LINES
        context = "\n".join(f"fact {i}" for i in range(max_lines + 10))
        result = self.orch._compact_prefilter_memory_context(context)
        assert result.count("\n") == max_lines - 1  # max_lines lines → max_lines-1 newlines

    def test_trims_to_max_chars_with_truncation_marker(self):
        long_line = "x" * (self.orch.PREFILTER_MEMORY_MAX_CHARS + 50)
        result = self.orch._compact_prefilter_memory_context(long_line)
        assert len(result) <= self.orch.PREFILTER_MEMORY_MAX_CHARS + len("\n... [truncated]")
        assert result.endswith("[truncated]")

    def test_short_context_returned_unchanged(self):
        ctx = "fact one\nfact two"
        assert self.orch._compact_prefilter_memory_context(ctx) == ctx

    def test_blank_lines_are_stripped(self):
        ctx = "fact one\n\n   \nfact two"
        result = self.orch._compact_prefilter_memory_context(ctx)
        assert result == "fact one\nfact two"


# ── _extract_selected_connection_indices ─────────────────────────────────────

class TestExtractSelectedConnectionIndices:
    def setup_method(self):
        self.orch = make_orchestrator()

    def test_single_index(self):
        assert self.orch._extract_selected_connection_indices("2", 5) == [2]

    def test_comma_separated_indices(self):
        assert self.orch._extract_selected_connection_indices("1,3,5", 5) == [1, 3, 5]

    def test_indices_out_of_range_are_excluded(self):
        assert self.orch._extract_selected_connection_indices("1,6", 5) == [1]

    def test_zero_index_excluded(self):
        assert self.orch._extract_selected_connection_indices("0,1", 3) == [1]

    def test_non_digit_parts_ignored(self):
        result = self.orch._extract_selected_connection_indices("gmail(1), sheets(2)", 5)
        # Should extract 1 and 2 from the digit sequences
        assert 1 in result
        assert 2 in result

    def test_empty_string_returns_empty(self):
        assert self.orch._extract_selected_connection_indices("", 3) == []

    def test_none_string_returns_empty(self):
        assert self.orch._extract_selected_connection_indices("NONE", 3) == []


# ── _parse_connection_filter_selection ───────────────────────────────────────

class TestParseConnectionFilterSelection:
    def setup_method(self):
        self.orch = make_orchestrator()
        self.connections = _make_connections(["gmail", "sheets", "sql"])

    def test_selects_valid_connections(self):
        result = self.orch._parse_connection_filter_selection("1,3", self.connections)
        names = [c.connection_name for c in result]
        assert names == ["gmail", "sql"]

    def test_none_response_returns_empty_list(self):
        result = self.orch._parse_connection_filter_selection("NONE", self.connections)
        assert result == []

    def test_empty_response_returns_empty_list(self):
        result = self.orch._parse_connection_filter_selection("", self.connections)
        assert result == []

    def test_out_of_range_index_returns_empty_list(self):
        result = self.orch._parse_connection_filter_selection("99", self.connections)
        assert result == []

    def test_no_valid_numbers_returns_empty_list(self):
        result = self.orch._parse_connection_filter_selection("abc", self.connections)
        assert result == []

    def test_strips_prefixes_before_parsing(self):
        result = self.orch._parse_connection_filter_selection("OUTPUT: 2", self.connections)
        assert len(result) == 1
        assert result[0].connection_name == "sheets"


def _make_connections(names: list):
    """Build mock connection objects with connection_name attribute."""
    conns = []
    for name in names:
        c = MagicMock()
        c.connection_name = name
        c.tool_name = name
        conns.append(c)
    return conns


# ── Orchestrator._build_final_message ────────────────────────────────────────

class TestBuildFinalMessage:
    def test_success_prefers_output_over_result(self):
        result = {"success": True, "output": "Hello", "result": "World"}
        msg, status = Orchestrator._build_final_message(result)
        assert msg == "Hello"
        assert status == "success"

    def test_success_uses_result_when_no_output(self):
        result = {"success": True, "output": "", "result": "Done"}
        msg, status = Orchestrator._build_final_message(result)
        assert msg == "Done"
        assert status == "success"

    def test_success_default_message_when_both_empty(self):
        result = {"success": True, "output": "", "result": ""}
        msg, status = Orchestrator._build_final_message(result)
        assert "completed" in msg.lower()
        assert status == "success"

    def test_failure_includes_error_message(self):
        result = {"success": False, "error": "NameError: x not defined", "output": ""}
        msg, status = Orchestrator._build_final_message(result)
        assert "NameError" in msg
        assert status == "error"

    def test_failure_appends_output_when_present(self):
        result = {"success": False, "error": "RuntimeError", "output": "partial output"}
        msg, status = Orchestrator._build_final_message(result)
        assert "partial output" in msg
        assert status == "error"

    def test_tool_not_found_adds_tip(self):
        result = {"success": False, "error": "Tool not found: gmail", "output": ""}
        msg, status = Orchestrator._build_final_message(result)
        assert "Tip:" in msg or "configured" in msg.lower()

    def test_output_equal_to_result_no_duplication(self):
        result = {"success": True, "output": "same", "result": "same"}
        msg, status = Orchestrator._build_final_message(result)
        assert msg == "same"
        assert msg.count("same") == 1


# ── Orchestrator._merge_outputs ───────────────────────────────────────────────

class TestMergeOutputs:
    def test_successful_retry_returns_new_output_only(self):
        out = Orchestrator._merge_outputs("partial", "complete result", True, "")
        assert out == "complete result"

    def test_failed_retry_with_both_outputs_concatenates(self):
        out = Orchestrator._merge_outputs("partial", "retry failed", False, "")
        assert "partial" in out
        assert "retry failed" in out
        assert "Auto-Retry" in out

    def test_failed_retry_no_original_uses_new(self):
        out = Orchestrator._merge_outputs("", "retry output", False, "")
        assert out == "retry output"

    def test_warning_prefix_is_prepended(self):
        out = Orchestrator._merge_outputs("original", "new", True, "disallowed action")
        assert out.startswith("WARNING:")

    def test_no_warning_prefix_when_empty(self):
        out = Orchestrator._merge_outputs("original", "new", True, "")
        assert not out.startswith("WARNING")


# ── Orchestrator._unpack_message ──────────────────────────────────────────────

class TestUnpackMessage:
    def test_plain_string_generates_task_id(self):
        task_id, payload = Orchestrator._unpack_message("do something")
        assert payload == "do something"
        assert len(task_id) > 0  # UUID generated

    def test_wrapped_dict_uses_provided_task_id(self):
        task_id, payload = Orchestrator._unpack_message({"task_id": "abc-123", "payload": "do X"})
        assert task_id == "abc-123"
        assert payload == "do X"

    def test_dict_without_task_id_generates_new_id(self):
        task_id, payload = Orchestrator._unpack_message({"payload": "do Y"})
        assert payload == {"payload": "do Y"}  # treated as plain payload
        assert len(task_id) > 0
