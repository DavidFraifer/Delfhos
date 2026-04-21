"""
Unit tests for the pure utility helpers in python_executor.py.

Covers: _safe_json_loads, safe_json_loads, format_table.
No LLM, network, or file I/O required.
"""
import pytest
from cortex._engine.core.python_executor import (
    _safe_json_loads,
    safe_json_loads,
    format_table,
)


# ── _safe_json_loads ──────────────────────────────────────────────────────────

class TestSafeJsonLoads:
    """Tests for the namespace-injected _safe_json_loads replacement."""

    def test_already_parsed_dict_returned_as_is(self):
        d = {"key": "value"}
        assert _safe_json_loads(d) is d

    def test_already_parsed_list_returned_as_is(self):
        lst = [1, 2, 3]
        assert _safe_json_loads(lst) is lst

    def test_valid_json_string_parsed(self):
        result = _safe_json_loads('{"a": 1}')
        assert result == {"a": 1}

    def test_empty_string_returns_none(self, capsys):
        result = _safe_json_loads("")
        assert result is None
        captured = capsys.readouterr()
        assert "Warning" in captured.out

    def test_whitespace_only_returns_none(self, capsys):
        result = _safe_json_loads("   ")
        assert result is None
        captured = capsys.readouterr()
        assert "Warning" in captured.out

    def test_invalid_json_string_raises(self):
        with pytest.raises(Exception):
            _safe_json_loads("{not valid json}")

    def test_nested_json_parsed(self):
        result = _safe_json_loads('{"nested": {"inner": [1, 2]}}')
        assert result["nested"]["inner"] == [1, 2]


# ── safe_json_loads ───────────────────────────────────────────────────────────

class TestSafeJsonLoadsPublic:
    """Tests for the public safe_json_loads helper used in agent-generated code."""

    def test_valid_json_returns_dict(self):
        result = safe_json_loads('{"key": "val"}')
        assert result == {"key": "val"}

    def test_valid_list_json(self):
        result = safe_json_loads("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_empty_string_returns_none(self, capsys):
        result = safe_json_loads("")
        assert result is None
        captured = capsys.readouterr()
        assert "Warning" in captured.out

    def test_none_input_returns_none(self, capsys):
        result = safe_json_loads(None)
        assert result is None

    def test_whitespace_only_returns_none(self, capsys):
        result = safe_json_loads("   \t\n")
        assert result is None

    def test_invalid_json_returns_none_with_warning(self, capsys):
        result = safe_json_loads("{bad json}")
        assert result is None
        captured = capsys.readouterr()
        assert "Warning" in captured.out

    def test_nested_objects_parsed(self):
        result = safe_json_loads('{"a": {"b": [1, 2, 3]}}')
        assert result["a"]["b"] == [1, 2, 3]

    def test_unicode_content(self):
        result = safe_json_loads('{"greeting": "héllo wörld"}')
        assert result["greeting"] == "héllo wörld"


# ── format_table ──────────────────────────────────────────────────────────────

class TestFormatTable:
    # ── empty / None ────────────────────────────────────────────────────────

    def test_empty_list_returns_no_data(self):
        assert format_table([]) == "*(No data)*"

    def test_none_returns_no_data(self):
        assert format_table(None) == "*(No data)*"

    def test_empty_dict_returns_no_data(self):
        # Empty dict is falsy — same as empty list
        assert format_table({}) == "*(No data)*"

    # ── list of dicts ────────────────────────────────────────────────────────

    def test_list_of_dicts_has_header_row(self):
        data = [{"name": "Alice", "age": 30}]
        result = format_table(data)
        assert "name" in result
        assert "age" in result

    def test_list_of_dicts_has_separator_row(self):
        data = [{"col": "val"}]
        result = format_table(data)
        assert "---" in result

    def test_list_of_dicts_values_present(self):
        data = [{"name": "Alice"}, {"name": "Bob"}]
        result = format_table(data)
        assert "Alice" in result
        assert "Bob" in result

    def test_list_of_dicts_pipe_in_value_escaped(self):
        data = [{"val": "a|b"}]
        result = format_table(data)
        assert "a\\|b" in result

    def test_list_of_dicts_newline_in_value_replaced(self):
        data = [{"val": "line1\nline2"}]
        result = format_table(data)
        # Newlines in cell values are replaced with spaces
        assert "line1 line2" in result

    def test_list_of_dicts_none_value_becomes_empty(self):
        data = [{"col": None}]
        result = format_table(data)
        lines = result.strip().split("\n")
        data_row = lines[2]  # header, separator, data
        assert data_row.strip() == "|  |"

    def test_large_list_truncated_at_100(self):
        data = [{"i": i} for i in range(150)]
        result = format_table(data)
        assert "150" in result  # truncation notice shows total
        assert "100" in result

    def test_title_prepended_when_given(self):
        data = [{"x": 1}]
        result = format_table(data, title="My Table")
        assert "**My Table**" in result

    def test_case_insensitive_dedup_keeps_first_key(self):
        # Two dicts with different key casing — first casing should win in header
        data = [{"Name": "Alice"}, {"name": "Bob"}]
        result = format_table(data)
        # Only one "Name" or "name" column header should appear
        header_line = result.split("\n")[0] if "\n" in result else result
        assert header_line.count("Name") + header_line.count("name") == 1

    # ── list of lists ────────────────────────────────────────────────────────

    def test_list_of_lists_first_row_is_header(self):
        data = [["Name", "Score"], ["Alice", 95], ["Bob", 87]]
        result = format_table(data)
        assert "Name" in result
        assert "Score" in result
        assert "Alice" in result

    def test_list_of_lists_with_custom_headers(self):
        data = [["Alice", 95], ["Bob", 87]]
        result = format_table(data, headers=["Name", "Score"])
        assert "Name" in result
        assert "Score" in result

    def test_list_of_lists_none_cell_becomes_empty(self):
        data = [["Col"], [None]]
        result = format_table(data)
        lines = result.strip().split("\n")
        assert lines[2].strip() == "|  |"

    def test_list_of_lists_truncated_at_100(self):
        header = ["n"]
        rows = [[i] for i in range(150)]
        data = [header] + rows
        result = format_table(data)
        assert "150" in result  # truncation note

    # ── single dict ──────────────────────────────────────────────────────────

    def test_single_dict_shows_key_value_headers(self):
        result = format_table({"total": 42, "count": 5})
        assert "Key" in result
        assert "Value" in result

    def test_single_dict_values_shown(self):
        result = format_table({"total": 42})
        assert "total" in result
        assert "42" in result

    def test_single_dict_pipe_escaped_in_key_and_value(self):
        result = format_table({"k|ey": "v|al"})
        assert "k\\|ey" in result
        assert "v\\|al" in result

    # ── list of scalars ──────────────────────────────────────────────────────

    def test_list_of_scalars_has_value_header(self):
        result = format_table([1, 2, 3])
        assert "Value" in result

    def test_list_of_scalars_values_present(self):
        result = format_table(["apple", "banana"])
        assert "apple" in result
        assert "banana" in result

    def test_list_of_scalars_none_becomes_empty(self):
        result = format_table([None])
        lines = result.strip().split("\n")
        assert lines[2].strip() == "|  |"

    # ── fallback ──────────────────────────────────────────────────────────────

    def test_non_supported_type_falls_back_to_str(self):
        result = format_table(42)  # type: ignore[arg-type]
        assert result == "42"
