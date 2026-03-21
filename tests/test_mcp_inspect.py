"""Tests for MCP inspect() connection setup guidance."""

from cortex.connections.mcp import MCP
from cortex._engine.mcp.compiler import MCPCompiler


def test_mcp_inspect_includes_connection_setup_non_verbose():
    original_load_cache = MCPCompiler.load_cache

    def _fake_load_cache(self):
        return {
            "tools": [
                {"mcp_name": "read_file", "description": "Read a file"},
                {"mcp_name": "write_file", "description": "Write a file"},
            ]
        }

    MCPCompiler.load_cache = _fake_load_cache
    try:
        mcp = MCP(
            "server-filesystem",
            args=["."],
            env={"API_TOKEN": "secret"},
            headers={"Authorization": "Bearer abc"},
            cache=True,
        )
        result = mcp.inspect(verbose=False)

        assert "connection_setup" in result
        setup = result["connection_setup"]

        assert setup["required_env_keys"] == []
        assert setup["args_format"] == ["<arg1>", "<arg2>", "--flag=value"]
        assert "ENV_VAR_NAME" in setup["env_format"]
        assert "Authorization" in setup["headers_format"]

        used = setup["used_in_this_connection"]
        assert used["args"] == ["."]
        assert used["env"]["API_TOKEN"] == "secret"
        assert used["headers"]["Authorization"] == "Bearer abc"
    finally:
        MCPCompiler.load_cache = original_load_cache


def test_mcp_inspect_includes_auth_examples_verbose():
    original_load_cache = MCPCompiler.load_cache

    def _fake_load_cache(self):
        return {
            "tools": [
                {"mcp_name": "create_issue", "description": "Create a GitHub issue"},
            ]
        }

    MCPCompiler.load_cache = _fake_load_cache
    try:
        mcp = MCP("server-github", env={"GITHUB_TOKEN": "ghp_test"}, cache=True)
        result = mcp.inspect(verbose=True)

        assert "connection_setup" in result
        setup = result["connection_setup"]
        assert setup["authentication"]["type"] == "env_or_headers"
        assert "GITHUB_TOKEN" in setup["required_env_keys"]

        examples = setup.get("examples", [])
        assert len(examples) >= 3
        assert any("GITHUB_TOKEN" in ex.get("python", "") for ex in examples)
        assert any("Authorization" in ex.get("python", "") for ex in examples)
    finally:
        MCPCompiler.load_cache = original_load_cache
