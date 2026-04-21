"""
Unit tests for pure functions in cortex._engine.tools.tool_registry.

No LLM, network, or file I/O required.
"""
import pytest
from unittest.mock import MagicMock

from cortex._engine.tools.tool_registry import (
    get_tool_capability,
    map_frontend_action_to_registry_action,
    _parse_prefilter_part,
    _append_connection_mapping,
    parse_prefilter_response,
    get_available_actions_for_connections,
    build_connection_context_for_prompt,
)


def _make_conn(connection_name: str, tool_name: str, allow=None, description: str = ""):
    """Build a minimal mock Connection for testing."""
    c = MagicMock()
    c.connection_name = connection_name
    c.tool_name = tool_name
    c.allow = allow
    c.metadata = {"description": description}
    return c


# ── get_tool_capability ────────────────────────────────────────────────────────

class TestGetToolCapability:
    def test_known_tool_returned(self):
        cap = get_tool_capability("gmail")
        assert cap is not None
        assert cap.tool_name == "gmail"

    def test_case_insensitive_lookup(self):
        assert get_tool_capability("GMAIL") is not None
        assert get_tool_capability("Gmail") is not None

    def test_unknown_tool_returns_none(self):
        assert get_tool_capability("nonexistent_tool_xyz") is None

    def test_sheets_tool_known(self):
        assert get_tool_capability("sheets") is not None

    def test_sql_tool_known(self):
        assert get_tool_capability("sql") is not None


# ── map_frontend_action_to_registry_action ────────────────────────────────────

class TestMapFrontendAction:
    def test_gmail_read(self):
        assert map_frontend_action_to_registry_action("gmail", "read") == "READ"

    def test_gmail_send(self):
        assert map_frontend_action_to_registry_action("gmail", "send emails") == "SEND"

    def test_sheets_write(self):
        assert map_frontend_action_to_registry_action("sheets", "write") == "WRITE"

    def test_sheets_create(self):
        assert map_frontend_action_to_registry_action("sheets", "create") == "CREATE"

    def test_docs_update(self):
        result = map_frontend_action_to_registry_action("docs", "edit")
        assert result == "UPDATE"

    def test_tool_name_case_insensitive(self):
        assert map_frontend_action_to_registry_action("GMAIL", "read") == "READ"

    def test_unknown_action_returns_none(self):
        assert map_frontend_action_to_registry_action("gmail", "teleport") is None

    def test_unknown_tool_returns_none(self):
        assert map_frontend_action_to_registry_action("fax_machine", "send") is None


# ── _parse_prefilter_part ──────────────────────────────────────────────────────

class TestParsePrefilterPart:
    def test_simple_tool_action(self):
        result = _parse_prefilter_part("gmail:READ")
        assert result == ("gmail", "READ")

    def test_action_uppercased(self):
        name, action = _parse_prefilter_part("gmail:read")
        assert action == "READ"

    def test_connection_name_with_colon(self):
        # Name with colons — split on LAST colon
        result = _parse_prefilter_part("Acme Corp DB:QUERY")
        assert result == ("Acme Corp DB", "QUERY")

    def test_no_colon_returns_none(self):
        assert _parse_prefilter_part("gmail_READ") is None

    def test_empty_name_returns_none(self):
        assert _parse_prefilter_part(":READ") is None

    def test_empty_action_returns_none(self):
        assert _parse_prefilter_part("gmail:") is None

    def test_whitespace_stripped(self):
        name, action = _parse_prefilter_part("  gmail  :  READ  ")
        assert name == "gmail"
        assert action == "READ"


# ── _append_connection_mapping ─────────────────────────────────────────────────

class TestAppendConnectionMapping:
    def test_first_entry_created(self):
        m = {}
        _append_connection_mapping(m, "gmail", "Work Gmail")
        assert m == {"gmail": ["Work Gmail"]}

    def test_second_connection_appended(self):
        m = {"gmail": ["Work Gmail"]}
        _append_connection_mapping(m, "gmail", "Personal Gmail")
        assert m["gmail"] == ["Work Gmail", "Personal Gmail"]

    def test_duplicate_not_added(self):
        m = {}
        _append_connection_mapping(m, "gmail", "Work Gmail")
        _append_connection_mapping(m, "gmail", "Work Gmail")
        assert m["gmail"] == ["Work Gmail"]

    def test_different_tools_independent(self):
        m = {}
        _append_connection_mapping(m, "gmail", "Work Gmail")
        _append_connection_mapping(m, "sql", "Sales DB")
        assert "Work Gmail" in m["gmail"]
        assert "Sales DB" in m["sql"]


# ── parse_prefilter_response ───────────────────────────────────────────────────

class TestParsePrefilterResponse:
    def test_builtin_tool_parsed(self):
        actions, conn_map = parse_prefilter_response("llm:CALL")
        assert "llm:CALL" in actions
        assert conn_map == {}

    def test_files_builtin_parsed(self):
        actions, _ = parse_prefilter_response("files:READ")
        assert "files:READ" in actions

    def test_connection_name_resolved_to_tool(self):
        conn = _make_conn("Work Gmail", "gmail")
        actions, conn_map = parse_prefilter_response("Work Gmail:READ", connections=[conn])
        assert "gmail:READ" in actions
        assert "Work Gmail" in conn_map.get("gmail", [])

    def test_multiple_actions_parsed(self):
        conn = _make_conn("Work Gmail", "gmail")
        actions, _ = parse_prefilter_response("llm:CALL, Work Gmail:READ", connections=[conn])
        assert len(actions) == 2

    def test_empty_response_returns_empty(self):
        actions, conn_map = parse_prefilter_response("")
        assert actions == []
        assert conn_map == {}

    def test_no_colon_part_skipped(self):
        actions, _ = parse_prefilter_response("gmail_READ")
        assert actions == []

    def test_fallback_when_connection_not_found(self):
        # Unknown connection name falls back to treating name as tool name
        actions, _ = parse_prefilter_response("unknowntool:QUERY")
        assert "unknowntool:QUERY" in actions

    def test_two_connections_same_tool_both_mapped(self):
        c1 = _make_conn("Work Gmail", "gmail")
        c2 = _make_conn("Personal Gmail", "gmail")
        actions, conn_map = parse_prefilter_response(
            "Work Gmail:READ, Personal Gmail:SEND", connections=[c1, c2]
        )
        assert conn_map["gmail"] == ["Work Gmail", "Personal Gmail"]


# ── get_available_actions_for_connections ──────────────────────────────────────

class TestGetAvailableActionsForConnections:
    def test_no_restrictions_adds_all_tool_actions(self):
        conn = _make_conn("Work Gmail", "gmail", allow=None)
        result = get_available_actions_for_connections([conn])
        assert "READ" in result.get("gmail", set())
        assert "SEND" in result.get("gmail", set())

    def test_allow_restriction_limits_actions(self):
        conn = _make_conn("ReadOnly Gmail", "gmail", allow=["read"])
        result = get_available_actions_for_connections([conn])
        gmail_actions = result.get("gmail", set())
        assert "READ" in gmail_actions
        assert "SEND" not in gmail_actions

    def test_builtins_always_included(self):
        result = get_available_actions_for_connections([])
        assert "llm" in result
        assert "files" in result

    def test_custom_tools_given_execute_action(self):
        result = get_available_actions_for_connections(
            [], custom_tools={"my_script": object()}
        )
        assert result.get("my_script") == {"EXECUTE"}

    def test_empty_connections_returns_builtins_only(self):
        result = get_available_actions_for_connections([])
        assert set(result.keys()) >= {"llm", "files"}

    def test_multiple_connections_different_tools(self):
        c1 = _make_conn("Work Gmail", "gmail", allow=None)
        c2 = _make_conn("Sales DB", "sql", allow=None)
        result = get_available_actions_for_connections([c1, c2])
        assert "gmail" in result
        assert "sql" in result

    def test_connection_without_tool_name_skipped(self):
        c = MagicMock()
        c.tool_name = None
        c.allow = None
        result = get_available_actions_for_connections([c])
        # Only builtins should be present — no crash
        assert "llm" in result


# ── build_connection_context_for_prompt ───────────────────────────────────────

class TestBuildConnectionContextForPrompt:
    def test_empty_map_returns_empty_string(self):
        assert build_connection_context_for_prompt({}, []) == ""

    def test_single_connection_shows_tool_and_name(self):
        conn = _make_conn("Work Gmail", "gmail")
        result = build_connection_context_for_prompt(
            {"gmail": ["Work Gmail"]}, [conn]
        )
        assert "gmail" in result
        assert "Work Gmail" in result

    def test_description_included_when_present(self):
        conn = _make_conn("Sales DB", "sql", description="Contains sales data")
        result = build_connection_context_for_prompt(
            {"sql": ["Sales DB"]}, [conn]
        )
        assert "Contains sales data" in result

    def test_multiple_connections_same_tool_triggers_multi_hint(self):
        c1 = _make_conn("Work Gmail", "gmail")
        c2 = _make_conn("Personal Gmail", "gmail")
        result = build_connection_context_for_prompt(
            {"gmail": ["Work Gmail", "Personal Gmail"]}, [c1, c2]
        )
        assert "Multiple connections" in result

    def test_single_connection_shows_auto_detect_tip(self):
        conn = _make_conn("Work Gmail", "gmail")
        result = build_connection_context_for_prompt(
            {"gmail": ["Work Gmail"]}, [conn]
        )
        assert "auto" in result.lower()

    def test_unknown_connection_name_shows_no_description(self):
        # Connection listed in map but not in the connections list
        result = build_connection_context_for_prompt(
            {"gmail": ["Ghost Gmail"]}, []
        )
        assert "Ghost Gmail" in result  # still shown
