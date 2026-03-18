import asyncio
import sys

sys.path.insert(0, ".")

from delfhos import Calendar, Docs, Drive, Gmail, SQL, Sheets, WebSearch
from delfhos.sandbox import MockDatabase, MockEmail
from cortex._engine.mcp import executor as mcp_executor
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


def test_dynamic_action_mapping_for_mcp_like_tools():
    # Simulate dynamically-registered MCP actions in the summaries table.
    TOOL_ACTION_SUMMARIES["github"] = {
        "CREATE_ISSUE": "Create issue",
        "LIST_REPOSITORIES": "List repos",
    }

    assert map_frontend_action_to_registry_action("github", "CREATE_ISSUE") == "CREATE_ISSUE"
    assert map_frontend_action_to_registry_action("github", "create-issue") == "CREATE_ISSUE"
    assert map_frontend_action_to_registry_action("github", "list repositories") == "LIST_REPOSITORIES"


def test_native_inspect_matches_mcp_style_structure_and_printing():
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


def test_mcp_namespace_blocks_disallowed_actions():
    class FakeClient:
        def call_tool(self, name, args):
            return {"content": [{"type": "text", "text": f"ok {name}"}]}

    compiled_tools = [
        {
            "mcp_name": "create_issue",
            "description": "Create issue",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "mcp_name": "list_repositories",
            "description": "List repositories",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
    ]

    ex = mcp_executor.MCPExecutor(FakeClient(), "github", compiled_tools)
    ns = mcp_executor.build_mcp_tools(ex, "github", allow={"list_repositories"})

    # Allowed action should work.
    result = asyncio.run(ns.list_repositories())
    assert "ok list_repositories" in result

    # Disallowed action should surface as a permission failure.
    try:
        _ = ns.create_issue
        assert False, "Expected disallowed MCP action to fail"
    except Exception as e:
        code = getattr(e, "code", None)
        assert code == "TOL-007" or "TOL-007" in str(e) or isinstance(e, AttributeError)
