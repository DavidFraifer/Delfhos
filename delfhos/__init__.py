"""
delfhos — Simple, fast, cost-effective AI agents.

Write autonomous agents in 5 lines of code. Delfhos handles tool integration,
code generation, execution, and error recovery.

Quick start::

    from delfhos import Agent, Gmail, Drive

    agent = Agent(
        tools=[Gmail(oauth_credentials="secrets.json"), Drive(oauth_credentials="secrets.json")],
        llm="gemini-3.1-flash-lite-preview"
    )
    agent.run("Forward today's reports to alice@co.com and archive old ones")

Custom tools::

    from delfhos import tool

    @tool
    def analyze_sentiment(text: str) -> str:
        \"\"\"Analyze sentiment of text.\"\"\"
        return "positive" if "good" in text.lower() else "negative"

    agent = Agent(tools=[analyze_sentiment, Gmail()], llm="gemini-3.1-flash-lite-preview")

Restrict tool access::

    gmail = Gmail(oauth_credentials="...", allow=["read"])  # Read-only
    agent = Agent(tools=[gmail], confirm=["write", "delete"])  # Require approval

Advanced (multiple LLMs, session memory)::

    from delfhos import Chat

    agent = Agent(
        tools=[...],
        light_llm="gemini-3.1-flash-lite-preview\",
        heavy_llm="gemini-3.1-pro\",
        chat=Chat(keep=5, summarize=True, persist=True),  # persist=True for cross-run memory
        verbose=True
    )

Key features:
  • Fast: Multi-step optimization with light/heavy LLM split.
  • Safe: Built-in approval workflow, action restrictions, sandboxed execution.
  • Transparent: See exactly what code the agent generated and why.
  • Flexible: @tool decorator, service integrations (Gmail, Drive, SQL, etc), REST API tools.
"""

# Suppress noisy TF warnings (may be triggered by transitive deps)
import os
from typing import TYPE_CHECKING
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

__version__ = "0.7.1"

# Tool system (no circular deps — delfhos.tool uses only stdlib)
from delfhos.tool import tool, ToolException, DelfhosToolWarning
from delfhos.errors import (
    DelfhosConfigError,
    ModelConfigurationError,
    AgentConfirmationError,
    MemorySetupError,
    MemoryRetrievalError,
    ToolExecutionError,
    EnvironmentKeyError,
    ToolDefinitionError,
    OptionalDependencyError,
    ConnectionConfigurationError,
    ConnectionFileNotFoundError,
    LLMExecutionError,
    CodeGenerationError,
    PrefilterError,
    SandboxExecutionError,
    SQLSchemaError,
    ConversationCompressionError,
    ApprovalRejectedError,
)

# Service tools
from delfhos.tools import (
    Gmail, SQL, Sheets, Drive, Calendar, Docs, WebSearch, APITool,
)

from delfhos.memory import Chat, Memory
from delfhos.llm_config import LLMConfig

if TYPE_CHECKING:
    # Static typing/IDE support: lets hover resolve Agent docs/signature.
    from cortex.cortex import Cortex as Agent


# Agent is lazily imported via __getattr__ below to avoid pulling in
# the full cortex engine (google.api_core, rich, etc.) on first import.

__all__ = [
    # Core
    "__version__",
    "Agent",
    "tool",
    "ToolException",
    "DelfhosToolWarning",
    "Chat",
    "Memory",
    "LLMConfig",
    # Service tools
    "Gmail",
    "SQL",
    "Sheets",
    "Drive",
    "Calendar",
    "Docs",
    "WebSearch",
    "APITool",
    # Errors
    "DelfhosConfigError",
    "ModelConfigurationError",
    "AgentConfirmationError",
    "MemorySetupError",
    "MemoryRetrievalError",
    "ToolExecutionError",
    "EnvironmentKeyError",
    "ToolDefinitionError",
    "OptionalDependencyError",
    "ConnectionConfigurationError",
    "ConnectionFileNotFoundError",
    "LLMExecutionError",
    "CodeGenerationError",
    "PrefilterError",
    "SandboxExecutionError",
    "SQLSchemaError",
    "ConversationCompressionError",
    "ApprovalRejectedError",
]


def __getattr__(name):
    """Lazy import for Agent to break circular dependency with cortex."""
    if name == "Agent":
        from cortex.cortex import Cortex
        # Cache it so subsequent accesses are fast
        globals()["Agent"] = Cortex
        return Cortex
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals().keys()) | {"Agent"})
