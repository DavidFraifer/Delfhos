import sys

sys.path.insert(0, ".")

from delfhos import Calendar, Docs, Drive, Gmail, SQL, Sheets, WebSearch
from delfhos.sandbox import MockDatabase, MockEmail
from cortex._engine.tools.tool_registry import map_frontend_action_to_registry_action, TOOL_ACTION_SUMMARIES


def test_native_methods_are_discoverable_via_inspect_only():
    assert not hasattr(Gmail, "allowed_actions")
    assert not hasattr(SQL, "allowed_actions")
    assert not hasattr(Sheets, "allowed_actions")
    assert not hasattr(Drive, "allowed_actions")
    assert not hasattr(Docs, "allowed_actions")
    assert not hasattr(Calendar, "allowed_actions")
    assert not hasattr(WebSearch, "allowed_actions")

    # Native method discovery should flow through inspect().
    ws = WebSearch()
    assert ws.inspect()["methods"] == ["search"]


def test_sandbox_mock_tools_are_discoverable_via_class_inspect():
    mock_email = MockEmail.inspect()
    assert mock_email["tool"] == "gmail"
    assert mock_email["methods"] == ["read", "send"]

    mock_db = MockDatabase.inspect()
    assert mock_db["tool"] == "sql"
    assert mock_db["methods"] == ["schema", "query", "write"]


def test_dynamic_action_mapping_for_dynamic_tools():
    # Simulate dynamically-registered actions in the summaries table (e.g., APITool).
    TOOL_ACTION_SUMMARIES["petstore"] = {
        "LIST_PETS": "List pets",
        "CREATE_PET": "Create pet",
    }

    assert map_frontend_action_to_registry_action("petstore", "LIST_PETS") == "LIST_PETS"
    assert map_frontend_action_to_registry_action("petstore", "list-pets") == "LIST_PETS"
    assert map_frontend_action_to_registry_action("petstore", "create pet") == "CREATE_PET"


def test_native_inspect_structure_and_printing():
    ws = WebSearch()

    compact = ws.inspect()
    assert compact["tool"] == "websearch"
    assert compact["methods"] == ["search"]
    assert compact["total"] == 1
    assert "📋 Tool: websearch" in str(compact)

    detailed = ws.inspect(verbose=True)
    assert detailed["tool"] == "websearch"
    assert detailed["allowed"] == "all"
    assert isinstance(detailed["methods"], list)
    assert detailed["methods"][0]["name"] == "search"
    assert "Search the web" in detailed["methods"][0]["description"]
