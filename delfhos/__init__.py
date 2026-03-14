"""
delfhos — AI agent SDK.

The Agent class is the entry point. Give it tools and describe what you
want in plain English — Delfhos takes care of the rest.

Usage::

    from delfhos import Agent, tool
    from delfhos.tools import Gmail, SQL

    @tool
    def my_func(x: str) -> str:
        return x.upper()

    gmail = Gmail(oauth_credentials="client_secrets.json")
    db    = SQL(url="postgresql://user:pass@host/mydb")

    agent = Agent(tools=[my_func, gmail, db])
    agent.run("How many users signed up this week? Email a summary to the team.")
    agent.stop()
"""

# Suppress noisy TF warnings (may be triggered by transitive deps)
import os
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

# Tool system (no circular deps — delfhos.tool uses only stdlib)
from delfhos.tool import tool, ToolException, DelfhosToolWarning

# Service tools
from delfhos.tools import (
    Gmail, SQL, Sheets, Drive, Calendar, Docs, WebSearch, MCP,
)

from delfhos.memory import Chat, Memory

__all__ = [
    # Core
    "Agent",
    "tool",
    "ToolException",
    "DelfhosToolWarning",
    "Chat",
    "Memory",
    # Service tools
    "Gmail",
    "SQL",
    "Sheets",
    "Drive",
    "Calendar",
    "Docs",
    "WebSearch",
    "MCP",
]


def __getattr__(name):
    """Lazy import for Agent to break circular dependency with cortex."""
    if name == "Agent":
        from cortex.cortex import Cortex
        # Cache it so subsequent accesses are fast
        globals()["Agent"] = Cortex
        return Cortex
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
