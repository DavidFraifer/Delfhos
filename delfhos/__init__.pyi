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
"""

from typing import Any, Callable, Dict, List, Optional, Union

from delfhos.memory import Chat as Chat, Memory as Memory
from delfhos.tool import (
    DelfhosToolWarning as DelfhosToolWarning,
    ToolException as ToolException,
    tool as tool,
)
from delfhos.tools import (
    Calendar as Calendar,
    Docs as Docs,
    Drive as Drive,
    Gmail as Gmail,
    SQL as SQL,
    Sheets as Sheets,
    WebSearch as WebSearch,
)

class _Response:
    """Unified response object for agent run execution."""
    text: str
    status: bool
    error: Optional[str]
    cost_usd: Optional[float]
    duration_ms: int
    trace: Any

class Agent:
    """
    AI agent that executes tasks by generating and running Python code against your tools.

    Cortex orchestrates a multi-step workflow:
      1. Prefilter: Choose relevant tools for the task.
      2. Generate: Create optimized Python code using an LLM.
      3. Execute: Run code in a sandbox against real services.
      4. Iterate: Get feedback and refine until the goal succeeds.

    Quick example:
        agent = Agent(tools=[Gmail(), Drive()], llm="gemini-3.1-flash-lite-preview")
        agent.run("Archive unread emails and summarize to alice@co.com")

    Advanced example with web search:
        agent = Agent(
            tools=[
                WebSearch(llm="gemini-3.1-flash-lite-preview"),
                SQL(url="postgresql://..."),
                Sheets(...)
            ],
            light_llm="gemini-3.1-flash-lite-preview",
            heavy_llm="gemini-3.1-pro",
            chat=Chat(keep=5, summarize=True),
            system_prompt="You are a data analyst. Be thorough.",
            confirm=["write", "delete"],
            on_confirm=lambda brief: input(f"Approve {brief}? ").lower() == "y"
        )

    WebSearch Tip: Request specific formats in your query for structured results:
        agent.run("Find mortgage rate. Ask WebSearch to return ONLY the percentage.")
        agent.run("Top 3 AI trends. Request: Format as 1. trend, 2. trend, 3. trend")

    Args:
        tools: Service tools (Gmail, Drive, SQL, APITool, WebSearch, etc) or @tool functions.
               Note: WebSearch(llm="model") requires an explicit model (Gemini or OpenAI/GPT).
        llm: Single LLM for all ops (simple). Use either llm OR (light_llm + heavy_llm).
        light_llm: Fast LLM for prefiltering (advanced; requires heavy_llm).
        heavy_llm: Stronger LLM for code generation (advanced; requires light_llm).
        code_llm: Model used for Python code generation. Defaults to heavy_llm.
        vision_llm: Model used for image analysis and multimodal tasks. Defaults to heavy_llm.
        chat: Chat(keep=10, summarize=False) for session memory (set Chat.summarizer_llm for compression).
        memory: Persistent memory across sessions (e.g., SQL database).
        system_prompt: Context/role injected into every LLM call.
        on_confirm: Approval callback fn(brief) -> bool. If set, enables human-in-the-loop.
                    Per-tool approval: set confirm= on each tool, e.g. Gmail(confirm=["send"]).
        verbose: If True, print detailed execution traces.
        enable_prefilter: If True, pre-filter tools before code generation (default: False).
        providers: API key overrides {"google": "...", "openai": "...", etc}.
    """

    def __init__(
        self,
        tools: Optional[List[Union[Any, Callable]]] = None,
        chat: Optional[Chat] = None,
        memory: Optional[Memory] = None,
        llm: Optional[str] = None,
        light_llm: Optional[str] = None,
        heavy_llm: Optional[str] = None,
        code_llm: Optional[str] = None,
        vision_llm: Optional[str] = None,
        system_prompt: Optional[str] = None,
        on_confirm: Optional[Callable] = None,
        providers: Optional[Dict[str, str]] = None,
        verbose: bool = False,
        enable_prefilter: bool = False,
    ) -> None:
        """Initialize an Agent with tools and language models.

        Args:
            tools: List of Service tools (Gmail, Drive, SQL, APITool, etc), @tool functions, or Connections.
            llm: Single LLM for all operations (e.g., "gemini-3.1-flash-lite-preview").
                 Shorthand for: light_llm=llm, heavy_llm=llm.
            light_llm: (Advanced) Fast LLM for prefiltering/lightweight tasks (requires heavy_llm).
            heavy_llm: (Advanced) Powerful LLM for code generation (requires light_llm).
            code_llm: Model used specifically for Python code generation. Defaults to heavy_llm.
            vision_llm: Model used for image analysis and multimodal tasks. Defaults to heavy_llm.
            chat: Chat(keep=10, summarize=True) — session memory & auto-summarization (set Chat.summarizer_llm for compression).
            memory: Persistent memory for facts/context (e.g., persisted embeddings).
            system_prompt: Custom instructions injected into every LLM call.
            on_confirm: Approval callback fn(brief) -> bool for custom approval UI.
                        Approval policies live on each tool: Gmail(confirm=["send"]).
            verbose: If True, print detailed execution traces and debugging info.
            providers: Override API keys {"google": "...", "openai": "...", etc}.

        Example::

            # Simple (single LLM)
            agent = Agent(
                tools=[Gmail(), Drive()],
                llm="gemini-3.1-flash-lite-preview"
            )
            agent.run("Forward today's reports to alice@co.com")

            # Advanced (multiple LLMs + per-tool approval)
            agent = Agent(
                tools=[
                    SQL(url="...", confirm=["write"]),       # confirm before writes
                    Gmail(oauth_credentials="...", confirm=["send"]),  # confirm before sending
                ],
                light_llm="gemini-3.1-flash-lite-preview",
                heavy_llm="gemini-3.1-pro",
                code_llm="gemini-3.1-pro",        # override for code generation
                vision_llm="gemini-3.1-pro-vision",  # override for image analysis
                chat=Chat(summarizer_llm="gemini-3.1-flash-lite-preview"),  # auto-summarizes
                verbose=True
            )
        """
        ...

    # ─── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> "Agent":
        """Start the agent. Returns self for fluent chaining: agent.start().run(...)"""
        ...

    def stop(self) -> None:
        """Clean up resources before exiting."""
        ...

    # ─── Task execution ──────────────────────────────────────────────

    def run_async(self, task: str) -> None:
        """
        Submit a task for execution in the background. Does not wait for completion.

        The agent:
          1. Filters which connections are relevant for the task.
          2. Generates Python code using the LLM.
          3. Executes the code in a background thread.

        Args:
            task: Natural language task description.
        """
        ...

    def run(self, task: str, timeout: float = 60.0) -> _Response:
        """
        Submit a task and block until it completes (or timeout is reached).

        Args:
            task:    Natural language task description.
            timeout: Maximum seconds to wait (default: 60).

        Returns:
            Response object containing the final result, cost, and metadata.
        """
        ...

    def run_chat(self, timeout: float = 120.0) -> None:
        """
        Start an interactive synchronous chat loop in the terminal.

        The method takes no task argument. You type each message in the console.
        
        Requires:
            Agent must be created with chat=Chat(...) parameter.
            
        Raises:
            ValueError: If Chat was not provided when creating the Agent.
            
        Example:
            agent = Agent(
                tools=[...],
                llm="gemini-3.1-flash-lite-preview",
                chat=Chat(summarizer_llm="gemini-3.1-flash-lite-preview")
            )
            agent.run_chat()
        """
        ...

    async def arun(self, task: str, timeout: float = 60.0) -> _Response:
        """
        Submit a task asynchronously and wait for its completion.

        Args:
            task:    Natural language task description.
            timeout: Maximum seconds to wait (default: 60).

        Returns:
            Response object containing the final result, cost, and metadata.
        """
        ...

    # ─── Human approval ──────────────────────────────────────────────

    def get_pending_approvals(self) -> list:
        """Get all approval requests waiting for human decision."""
        ...

    def approve(self, request_id: str, response: str = "Approved") -> bool:
        """Approve a pending action request."""
        ...

    def reject(self, request_id: str, reason: str = "Rejected") -> bool:
        """Reject a pending action request."""
        ...

    # ─── Inspection ──────────────────────────────────────────────────

    def info(self) -> Dict[str, Any]:
        """Return current agent state: running tasks, tools, models, etc."""
        ...

    def get_llm_config_string(self) -> str:
        """Get the LLM configuration string for display."""
        ...

    @property
    def usage(self) -> Any:
        """Token usage statistics across the agent lifecycle."""
        ...

    @property
    def memory(self) -> Optional[Memory]:
        """Returns the attached Memory instance, if any."""
        ...

    @property
    def chat(self) -> Optional[Chat]:
        """Returns the attached Chat instance."""
        ...

    @property
    def agent_id(self) -> str:
        """Unique identifier for this agent instance."""
        ...

    # ─── Context manager support ─────────────────────────────────────

    def __enter__(self) -> "Agent": ...
    def __exit__(self, *_: Any) -> None: ...
    async def __aenter__(self) -> "Agent": ...
    async def __aexit__(self, *_: Any) -> None: ...
    def __str__(self) -> str: ...


__all__ = [
    "Agent",
    "tool",
    "ToolException",
    "DelfhosToolWarning",
    "Chat",
    "Memory",
    "Gmail",
    "SQL",
    "Sheets",
    "Drive",
    "Calendar",
    "Docs",
    "WebSearch",
]
