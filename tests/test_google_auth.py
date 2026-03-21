"""
Tests for cortex.google_auth — scope mapping and credential resolution.

Run:  python -m pytest tests/test_google_auth.py -v
"""

import sys
import os
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cortex.google_auth import actions_to_scopes, scopes_to_actions, resolve_google_credentials, SCOPE_MAP


# ─── actions_to_scopes tests ────────────────────────────────────────────────


class TestActionsToScopes:
    """Test the action → scope mapping logic."""

    def test_gmail_read_gives_readonly(self):
        scopes = actions_to_scopes("gmail", ["read"])
        assert scopes == ["https://www.googleapis.com/auth/gmail.readonly"]

    def test_gmail_send_gives_send_scope(self):
        scopes = actions_to_scopes("gmail", ["send"])
        assert scopes == ["https://www.googleapis.com/auth/gmail.send"]

    def test_gmail_read_and_send_gives_both(self):
        scopes = actions_to_scopes("gmail", ["read", "send"])
        assert "https://www.googleapis.com/auth/gmail.readonly" in scopes
        assert "https://www.googleapis.com/auth/gmail.send" in scopes
        assert len(scopes) == 2

    def test_gmail_all_actions_gives_union_of_action_scopes(self):
        scopes = actions_to_scopes("gmail", None)
        assert "https://www.googleapis.com/auth/gmail.readonly" in scopes
        assert "https://www.googleapis.com/auth/gmail.send" in scopes

    def test_sheets_read_gives_readonly(self):
        scopes = actions_to_scopes("sheets", ["read"])
        assert scopes == ["https://www.googleapis.com/auth/spreadsheets.readonly"]

    def test_sheets_write_gives_full(self):
        scopes = actions_to_scopes("sheets", ["write"])
        assert "https://www.googleapis.com/auth/spreadsheets" in scopes
        assert "https://www.googleapis.com/auth/drive" in scopes
        assert len(scopes) == 2

    def test_drive_readonly_actions(self):
        scopes = actions_to_scopes("drive", ["search", "get"])
        assert scopes == ["https://www.googleapis.com/auth/drive.readonly"]

    def test_drive_write_actions(self):
        scopes = actions_to_scopes("drive", ["create", "delete"])
        assert scopes == ["https://www.googleapis.com/auth/drive"]

    def test_drive_mixed_actions_includes_both(self):
        scopes = actions_to_scopes("drive", ["search", "create"])
        assert "https://www.googleapis.com/auth/drive.readonly" in scopes
        assert "https://www.googleapis.com/auth/drive" in scopes

    def test_calendar_read_gives_readonly(self):
        scopes = actions_to_scopes("calendar", ["list"])
        assert scopes == ["https://www.googleapis.com/auth/calendar.readonly"]

    def test_calendar_write_gives_full(self):
        scopes = actions_to_scopes("calendar", ["create"])
        assert scopes == ["https://www.googleapis.com/auth/calendar"]

    def test_docs_read_gives_readonly(self):
        scopes = actions_to_scopes("docs", ["read"])
        assert scopes == ["https://www.googleapis.com/auth/documents.readonly"]

    def test_docs_create_includes_drive(self):
        scopes = actions_to_scopes("docs", ["create"])
        assert "https://www.googleapis.com/auth/documents" in scopes
        assert "https://www.googleapis.com/auth/drive" in scopes

    def test_unknown_tool_returns_empty(self):
        scopes = actions_to_scopes("nosuch", ["read"])
        assert scopes == []

    def test_unknown_action_raises(self):
        with pytest.raises(Exception, match="Unknown action"):
            actions_to_scopes("gmail", ["nonexistent"])

    def test_case_insensitive_tool(self):
        scopes = actions_to_scopes("GMAIL", ["read"])
        assert scopes == ["https://www.googleapis.com/auth/gmail.readonly"]

    def test_case_insensitive_actions(self):
        scopes = actions_to_scopes("gmail", ["READ"])
        assert scopes == ["https://www.googleapis.com/auth/gmail.readonly"]

    def test_scopes_are_deduplicated(self):
        # "write" and "create" for sheets give the same scope
        scopes = actions_to_scopes("sheets", ["write", "create"])
        assert "https://www.googleapis.com/auth/spreadsheets" in scopes
        assert "https://www.googleapis.com/auth/drive" in scopes
        assert len(scopes) == 2

    def test_all_tools_have_wildcard(self):
        """Every tool in the SCOPE_MAP should have a '*' fallback entry."""
        for tool_name, tool_scopes in SCOPE_MAP.items():
            assert "*" in tool_scopes, f"{tool_name} missing '*' fallback in SCOPE_MAP"


# ─── resolve_google_credentials tests ────────────────────────────────────────


class TestResolveCredentials:
    """Test credential resolution priority and error handling."""

    def test_no_auth_raises_configuration_error(self):
        with pytest.raises(Exception, match="No authentication provided"):
            resolve_google_credentials(tool_name="gmail")

    def test_missing_sa_file_raises_connection_file_not_found(self):
        with pytest.raises(Exception, match="Service account file not found"):
            resolve_google_credentials(
                tool_name="gmail",
                service_account="/nonexistent/path/sa.json",
            )

    def test_missing_oauth_file_raises_connection_file_not_found(self):
        with pytest.raises(Exception, match="OAuth client secrets file not found"):
            resolve_google_credentials(
                tool_name="gmail",
                oauth_credentials="/nonexistent/path/client.json",
            )


class TestScopesToActions:
    def test_drive_full_scope_implies_read_actions(self):
        actions = scopes_to_actions("drive", ["https://www.googleapis.com/auth/drive"])
        assert "search" in actions
        assert "get" in actions
        assert "create" in actions

    def test_requested_actions_are_not_expanded(self):
        actions = scopes_to_actions(
            "drive",
            ["https://www.googleapis.com/auth/drive"],
            requested_actions=["list_permissions"],
        )
        assert actions == ["list_permissions"]
