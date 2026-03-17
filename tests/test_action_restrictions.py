import asyncio
import sys

sys.path.insert(0, ".")

from delfhos import Calendar, Docs, Drive, Gmail, SQL, Sheets, WebSearch
from cortex._engine.mcp import executor as mcp_executor
from cortex._engine.tools.tool_registry import map_frontend_action_to_registry_action, TOOL_ACTION_SUMMARIES


def test_native_allowed_actions_are_discoverable():
    assert Gmail.allowed_actions() == ["read", "send"]
    assert SQL.allowed_actions() == ["schema", "query", "write"]
    assert Sheets.allowed_actions() == ["read", "write", "create", "format", "chart", "batch"]
    assert Drive.allowed_actions() == ["search", "get", "create", "update", "delete", "list_permissions", "share", "unshare"]
    assert Docs.allowed_actions() == ["read", "create", "update", "format", "delete"]
    assert Calendar.allowed_actions() == ["list", "create", "update", "delete"]
    assert WebSearch.allowed_actions() == ["search"]


def test_dynamic_action_mapping_for_mcp_like_tools():
    # Simulate dynamically-registered MCP actions in the summaries table.
    TOOL_ACTION_SUMMARIES["github"] = {
        "CREATE_ISSUE": "Create issue",
        "LIST_REPOSITORIES": "List repos",
    }

    assert map_frontend_action_to_registry_action("github", "CREATE_ISSUE") == "CREATE_ISSUE"
    assert map_frontend_action_to_registry_action("github", "create-issue") == "CREATE_ISSUE"
    assert map_frontend_action_to_registry_action("github", "list repositories") == "LIST_REPOSITORIES"


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
