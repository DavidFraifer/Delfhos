"""
Unit tests for cortex._engine.tools.classification.

All helpers are pure functions — no LLM, network, or filesystem I/O.
"""
import pytest
from cortex._engine.tools.classification import (
    _tokenize,
    _classify_from_name,
    _classify_from_description,
    classify_tool,
    is_delete_tool,
)


# ── _tokenize ─────────────────────────────────────────────────────────────────

class TestTokenize:
    def test_snake_case_splits(self):
        assert _tokenize("get_invoice") == ["get", "invoice"]

    def test_kebab_case_splits(self):
        assert _tokenize("send-email") == ["send", "email"]

    def test_camel_case_splits(self):
        assert _tokenize("createTask") == ["create", "task"]

    def test_mixed_case_splits(self):
        assert _tokenize("getUser_profile") == ["get", "user", "profile"]

    def test_lowercases_all_tokens(self):
        tokens = _tokenize("DeleteItem")
        assert all(t == t.lower() for t in tokens)

    def test_empty_string_returns_empty(self):
        assert _tokenize("") == []

    def test_single_word(self):
        assert _tokenize("create") == ["create"]


# ── _classify_from_name ───────────────────────────────────────────────────────

class TestClassifyFromName:
    def test_read_verb_is_read(self):
        assert _classify_from_name("get_invoice") == "read"

    def test_write_verb_is_write(self):
        assert _classify_from_name("create_document") == "write"

    def test_send_verb_is_write(self):
        assert _classify_from_name("send_email") == "write"

    def test_delete_verb_is_write(self):
        assert _classify_from_name("delete_row") == "write"

    def test_list_verb_is_read(self):
        assert _classify_from_name("list_users") == "read"

    def test_fetch_verb_is_read(self):
        assert _classify_from_name("fetch_data") == "read"

    def test_unknown_verb_returns_unknown(self):
        assert _classify_from_name("process_data") == "unknown"

    def test_camel_case_tool_name(self):
        assert _classify_from_name("updateRecord") == "write"

    def test_empty_string_returns_unknown(self):
        assert _classify_from_name("") == "unknown"


# ── _classify_from_description ────────────────────────────────────────────────

class TestClassifyFromDescription:
    def test_write_signal_in_description(self):
        result = _classify_from_description("Creates a new invoice in the system")
        assert result == "write"

    def test_read_signal_in_description(self):
        result = _classify_from_description("Retrieves all invoices for the user")
        assert result == "read"

    def test_more_write_signals_wins(self):
        result = _classify_from_description("Creates and saves a document, then deletes old ones")
        assert result == "write"

    def test_more_read_signals_wins(self):
        result = _classify_from_description("Fetches and lists all records and retrieves metadata")
        assert result == "read"

    def test_empty_description_returns_unknown(self):
        assert _classify_from_description("") == "unknown"

    def test_none_description_returns_unknown(self):
        assert _classify_from_description(None) == "unknown"

    def test_no_known_signals_returns_unknown(self):
        assert _classify_from_description("Processes the data pipeline") == "unknown"

    def test_description_case_insensitive(self):
        assert _classify_from_description("CREATES a new record") == "write"


# ── classify_tool ─────────────────────────────────────────────────────────────

class TestClassifyTool:
    def test_name_read_verb_wins_quickly(self):
        assert classify_tool("get_user") == "read"

    def test_name_write_verb_wins_quickly(self):
        assert classify_tool("send_message") == "write"

    def test_falls_back_to_description_when_name_unknown(self):
        # "process" is not a known verb, so description drives classification
        result = classify_tool("process_data", "Retrieves and lists all matching records")
        assert result == "read"

    def test_falls_back_to_write_when_both_unknown(self):
        # When genuinely ambiguous, defaults to write (safe side)
        result = classify_tool("execute_pipeline", "Runs the processing pipeline")
        assert result == "write"

    def test_description_write_beats_unknown_name(self):
        result = classify_tool("handle_request", "Creates and saves a new entry")
        assert result == "write"

    def test_no_description_defaults_to_write_on_ambiguity(self):
        assert classify_tool("pipeline") == "write"

    def test_known_read_verb_ignores_description(self):
        # name-based classification wins; description is not consulted
        assert classify_tool("search_users", "Sends notifications") == "read"

    def test_update_verb_is_write(self):
        assert classify_tool("update_profile") == "write"

    def test_insert_verb_is_write(self):
        assert classify_tool("insert_record") == "write"

    def test_query_verb_is_read(self):
        assert classify_tool("query_database") == "read"


# ── is_delete_tool ────────────────────────────────────────────────────────────

class TestIsDeleteTool:
    def test_delete_prefix_is_true(self):
        assert is_delete_tool("delete_email") is True

    def test_remove_prefix_is_true(self):
        assert is_delete_tool("remove_contact") is True

    def test_purge_prefix_is_true(self):
        assert is_delete_tool("purge_cache") is True

    def test_drop_prefix_is_true(self):
        assert is_delete_tool("drop_table") is True

    def test_archive_prefix_is_true(self):
        assert is_delete_tool("archive_invoice") is True

    def test_read_tool_is_false(self):
        assert is_delete_tool("get_user") is False

    def test_write_non_delete_is_false(self):
        assert is_delete_tool("send_email") is False

    def test_description_contains_permanently(self):
        assert is_delete_tool("clear_all", "Permanently removes all entries") is True

    def test_description_contains_cannot_be_undone(self):
        assert is_delete_tool("bulk_action", "This action cannot be undone") is True

    def test_description_contains_irreversible(self):
        assert is_delete_tool("cleanup", "This is irreversible once started") is True

    def test_no_signals_returns_false(self):
        assert is_delete_tool("create_record", "Creates a new record") is False

    def test_empty_name_and_description(self):
        assert is_delete_tool("", "") is False

    def test_camel_case_delete_prefix(self):
        assert is_delete_tool("deleteRecord") is True
