"""Test MCP compiler compatibility with the tool system."""
import sys
sys.path.insert(0, ".")

from cortex._engine.mcp.compiler import MCPCompiler
from cortex._engine.mcp import executor as _executor_mod


def test_type_names_are_llm_friendly():
    print("=== LLM-friendly type names ===")
    from cortex._engine.mcp.compiler import _TYPE_MAP
    assert _TYPE_MAP["string"] == "string"
    assert _TYPE_MAP["integer"] == "integer"
    assert _TYPE_MAP["object"] == "object"
    assert _TYPE_MAP["array"] == "array"
    print("  _TYPE_MAP OK")


def test_nested_object_expansion():
    print("\n=== Nested object expansion ===")
    c = MCPCompiler("github", "npx mcp-github")
    tool_schema = {
        "name": "create_issue",
        "description": "Create a GitHub issue",
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repo owner"},
                "repo": {"type": "string", "description": "Repo name"},
                "title": {"type": "string", "description": "Issue title"},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Label list",
                },
                "assignee": {
                    "type": "object",
                    "description": "Assignee info",
                    "properties": {
                        "login": {"type": "string"},
                        "id": {"type": "integer"},
                    },
                    "required": ["login"],
                },
            },
            "required": ["owner", "repo", "title"],
        },
    }

    result = c._compile_tool(tool_schema)
    sig = result["python_signature"]
    doc = result["api_doc"]

    print(f"  signature: {sig}")
    print(f"  api_doc:\n{doc}")

    # labels should be array[string], not just "array" or "list"
    assert "array[string]" in sig, f"Expected array[string] in sig: {sig}"
    # assignee should expand to {login: string, id?: integer}
    assert "login: string" in sig, f"Expected login: string in sig: {sig}"
    assert "id?: integer" in sig, f"Expected id?: integer in sig: {sig}"
    # api_doc should use "# await" style
    assert "# await github.create_issue(" in doc
    print("  All assertions passed")


def test_api_doc_format_consistent():
    print("\n=== API doc format matches build_api_signature style ===")
    c = MCPCompiler("mytool", "npx mytool")
    tool_schema = {
        "name": "do_thing",
        "description": "Does a thing",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The name"},
            },
            "required": ["name"],
        },
    }
    result = c._compile_tool(tool_schema)
    doc = result["api_doc"]
    print(f"  doc: {doc!r}")
    # Should start with "# await " like build_api_signature output
    assert doc.startswith("# await mytool.do_thing("), f"Unexpected format: {doc}"
    # Should have description on second line starting with "# "
    lines = doc.splitlines()
    assert lines[1] == "# Does a thing"
    print("  Format OK")


def test_mcp_error_raises_tool_exception():
    print("\n=== MCP errors route through ToolException ===")
    from delfhos.tool import ToolException

    class FakeClient:
        def call_tool(self, name, args):
            return {
                "isError": True,
                "content": [{"type": "text", "text": "Repository not found"}],
            }

    compiled_tools = [{"mcp_name": "create_issue", "input_schema": {}}]
    ex = _executor_mod.MCPExecutor(FakeClient(), "github", compiled_tools)

    try:
        ex.call("create_issue", owner="x", repo="y", title="z")
        assert False, "Should have raised ToolException"
    except ToolException as e:
        print(f"  ToolException raised: {e}")
        assert "Repository not found" in str(e)
    print("  ToolException routing OK")


def test_build_mcp_tools_creates_tool_instances():
    print("\n=== build_mcp_tools creates real Tool instances ===")
    from delfhos.tool import Tool

    class FakeClient:
        def call_tool(self, name, args):
            return {"content": [{"type": "text", "text": f"result for {name}"}]}

    compiled_tools = [
        {
            "mcp_name": "create_issue",
            "description": "Create a GitHub issue",
            "input_schema": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Repo owner"},
                    "repo": {"type": "string", "description": "Repo name"},
                    "title": {"type": "string", "description": "Issue title"},
                },
                "required": ["owner", "repo", "title"],
            },
        },
        {
            "mcp_name": "list_repos",
            "description": "List repositories",
            "input_schema": {
                "type": "object",
                "properties": {
                    "org": {"type": "string", "description": "Organization name"},
                },
                "required": ["org"],
            },
        },
    ]

    ex = _executor_mod.MCPExecutor(FakeClient(), "github", compiled_tools)
    ns = _executor_mod.build_mcp_tools(ex, "github")

    # Each tool should be a real Tool instance
    assert isinstance(ns._tools["create_issue"], Tool)
    assert isinstance(ns._tools["list_repos"], Tool)

    # api_doc should use the unified format
    doc = ns._tools["create_issue"].api_doc()
    print(f"  create_issue api_doc: {doc}")
    assert "# await create_issue(" in doc
    assert "owner: string" in doc
    assert "title: string" in doc

    # Namespace attribute access should return tool.execute
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        ns.create_issue(owner="myorg", repo="myrepo", title="Bug")
    )
    print(f"  execute result: {result}")
    assert "result for create_issue" in result

    # get_all_api_docs should concatenate all
    all_docs = ns.get_all_api_docs()
    assert "create_issue" in all_docs
    assert "list_repos" in all_docs
    print("  Tool instances OK")


if __name__ == "__main__":
    test_type_names_are_llm_friendly()
    test_nested_object_expansion()
    test_api_doc_format_consistent()
    test_mcp_error_raises_tool_exception()
    test_build_mcp_tools_creates_tool_instances()
    print("\n✅ ALL MCP TESTS PASSED")
