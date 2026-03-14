"""
Simple real-agent example with MCP + confirm policy.

What this demonstrates:
- Real Agent execution
- MCP tool connection (filesystem server)
- confirm=["write"] policy on the connection
- on_confirm callback for approval decisions

Run:
    PYTHONPATH=. .venv/bin/python examples/real_agent_confirm_simple.py

Requirements:
- LLM API keys configured for your environment
- Node.js with npx available (for MCP server-filesystem)
"""

import json
import sys
from delfhos import Agent
from delfhos.tools import MCP


async def on_confirm(request) -> bool:
    """Interactive approval callback used by the agent.

    This callback shape is bool-first and async-friendly.
    """
    live_out = getattr(sys, "__stdout__", sys.stdout)

    def _live_print(message: str = ""):
        live_out.write(f"{message}\n")
        live_out.flush()

    _live_print("\n=== APPROVAL REQUEST ===")
    _live_print(f"Task: {request.task_id}")
    _live_print(f"Message: {request.message}")

    # Try to show useful context if present.
    try:
        ctx = json.loads(request.context) if request.context else {}
        if isinstance(ctx, dict):
            _live_print(f"Action: {ctx.get('action', 'unknown')}")
            _live_print(f"Tool: {ctx.get('tool', 'unknown')}.{ctx.get('method', 'unknown')}")
    except Exception:
        pass

    live_out.write("Approve this action? [y/N]: ")
    live_out.flush()
    answer = input().strip().lower()
    approved = answer in {"y", "yes"}
    return approved


def main():
    # Real MCP tool: local filesystem server.
    # confirm=["write", "delete"] means read-like calls run directly,
    # write-like calls require approval.
    files = MCP(
        "server-filesystem",
        args=["."],
        cache=True,
        confirm=["write", "delete"],
    )

    agent = Agent(
        tools=[files],
        on_confirm=on_confirm,
    )

    task = (
        "Use only filesystem MCP tool methods (filesystem.list_directory and "
        "filesystem.write_file). Do not import os or any other modules. "
        "List python files in the current directory, then create a file named "
        "mcp_confirm_demo.txt with one short line confirming the test run."
    )

    print("\n--- Running real agent confirm demo ---")
    print(task)

    try:
        agent.run(task, timeout=180)
    finally:
        agent.stop()


if __name__ == "__main__":
    main()
