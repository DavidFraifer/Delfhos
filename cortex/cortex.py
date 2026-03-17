"""
Cortex — The AI agent engine.

Cortex orchestrates task execution: it filters which tools are needed,
generates Python code using an LLM, and executes it against real services.

Quick start:
    from cortex import Cortex
    from delfhos.tools import Gmail, SQL

    gmail = Gmail(oauth_credentials="secrets.json")
    db    = SQL(url="postgresql://user:pass@host/mydb")

    agent = Cortex(tools=[gmail, db])
    agent.run("How many active users signed up this week? Email a summary to the team.")
    agent.stop()

That's it.
"""

import time
from typing import List, Optional, Union, Dict, Any, Callable
from cortex._engine.agent import Agent
from cortex._engine.connection import Connection
from delfhos.memory import Chat, Memory


def _has_confirm_policy(confirm_policy: Any) -> bool:
    if isinstance(confirm_policy, bool):
        return confirm_policy
    if isinstance(confirm_policy, list):
        return len(confirm_policy) > 0
    if isinstance(confirm_policy, str):
        return confirm_policy.strip().lower() not in ("none", "false", "")
    return False


class Cortex:
    """
    AI agent that executes tasks by generating and running Python code against your tools.

    Cortex orchestrates a multi-step workflow:
      1. Prefilter: Choose relevant tools for the task.
      2. Generate: Create optimized Python code using an LLM.
      3. Execute: Run code in a sandbox against real services.
      4. Iterate: Get feedback and refine until the goal succeeds.

    Quick example:
        agent = Cortex(tools=[Gmail(), Drive()], llm="gemini-3.1-flash-lite-preview")
        agent.start().run("Archive unread emails and summarize to alice@co.com")

    Advanced example:
        agent = Cortex(
            tools=[WebSearch(), SQL(url="postgresql://..."), Sheets(...)],
            light_llm="gemini-3.1-flash-lite-preview",
            heavy_llm="gemini-3.1-pro",
            chat=Chat(keep=5, summarize=True),
            system_prompt="You are a data analyst. Be thorough.",
            confirm=["write", "delete"],
            on_confirm=lambda brief: input(f"Approve {brief}? ").lower() == "y"
        )

    Args:
        tools: Service tools (Gmail, Drive, SQL, MCP, etc) or @tool functions.
        llm: Single LLM for all ops (simple). Use either llm OR (light_llm + heavy_llm).
        light_llm: Fast LLM for prefiltering (advanced; requires heavy_llm).
        heavy_llm: Stronger LLM for code generation (advanced; requires light_llm).
        summarizer_llm: Optional model for conversation compression.
        chat: Chat(keep=10, summarize=False) for session memory.
        memory: Persistent memory across sessions (e.g., SQL database).
        system_prompt: Context/role injected into every LLM call.
        confirm: Approval policy: True (all), ["write", "delete"], or "none".
        on_confirm: Approval callback fn(brief) -> bool. If set, enables human-in-the-loop.
        verbose: If True, print detailed execution traces.
        providers: API key overrides {\"google\": \"...\", \"openai\": \"...\", etc}.
    """

    def __init__(
        self,
        tools: Optional[List[Union[Connection, Callable, Any]]] = None,
        chat: Optional[Chat] = None,
        memory: Optional[Memory] = None,
        llm: Optional[str] = None,
        light_llm: Optional[str] = None,
        heavy_llm: Optional[str] = None,
        summarizer_llm: Optional[str] = None,
        system_prompt: Optional[str] = None,
        confirm: Optional[Union[bool, List[str], str]] = None,
        on_confirm: Optional[Callable] = None,
        providers: Optional[Dict[str, str]] = None,
        verbose: bool = False,
    ):
        """Initialize an Agent (Cortex) with tools and language models.
        
        Args:
            tools: List of Service tools (Gmail, Drive, SQL, MCP, etc), @tool functions, or Connections.
            llm: Single LLM for all operations (e.g., "gemini-3.1-flash-lite-preview").
                 Shorthand for: light_llm=llm, heavy_llm=llm.
            light_llm: (Advanced) Fast LLM for prefiltering/lightweight tasks (requires heavy_llm).
            heavy_llm: (Advanced) Powerful LLM for code generation (requires light_llm).
            chat: Chat(keep=10, summarize=True) — session memory & auto-summarization.
            memory: Persistent memory for facts/context (e.g., persisted embeddings).
            system_prompt: Custom instructions injected into every LLM call.
            confirm: Approval policy before executing actions:
                     - True: require approval for everything
                     - False/"none": no approvals
                     - ["write", "delete"]: only approve these actions (default)
            on_confirm: Approval callback fn(brief) -> bool for custom approval UI.
            verbose: If True, print detailed execution traces and debugging info.
            providers: Override API keys {\"google\": \"...\", \"openai\": \"...\", etc}.
        
        Example::
        
            # Simple (single LLM)
            agent = Agent(
                tools=[Gmail(), Drive()],
                llm="gemini-3.1-flash-lite-preview"
            )
            agent.run("Forward today's reports to alice@co.com")
            
            # Advanced (multiple LLMs + memory)
            agent = Agent(
                tools=[WebSearch(), SQL(url="..."), Sheets(...)],
                light_llm="gemini-3.1-flash-lite-preview",
                heavy_llm="gemini-3.1-pro",
                chat=Chat(),  # auto-summarizes
                confirm=["write", "delete"],  # require approval
                verbose=True
            )
        """
        resolved_tools = tools or []
        resolved_confirm = ["write", "delete"] if confirm is None else confirm

        if memory is not None and chat is None:
            chat = Chat(keep=8, summarize=True)

        self._agent = Agent(
            tools=resolved_tools,
            llm=llm,
            light_llm=light_llm,
            heavy_llm=heavy_llm,
            summarizer_llm=summarizer_llm,
            on_confirm=on_confirm,
            confirm=resolved_confirm,
            system_prompt=system_prompt,
            chat=chat,
            memory=memory,
            providers=providers,
            verbose=verbose,
            _explicit_llms={
                "light_llm": light_llm is not None,
                "heavy_llm": heavy_llm is not None,
                "summarizer_llm": summarizer_llm is not None
            }
        )

    @property
    def last_trace(self):
        """Retrieve the last execution trace of the agent."""
        return self._agent.last_trace

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> "Cortex":
        """Start the agent. Returns self for fluent chaining: agent.start().run(...)"""
        self._agent.start()
        return self

    def stop(self):
        """Clean up resources before exiting."""
        if hasattr(self, '_agent') and hasattr(self._agent, 'stop'):
            self._agent.stop()

    # ─── Task execution ───────────────────────────────────────────────────────

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
        # Note: run() will auto-start the agent and print task box first
        self._agent.run(task)

    def run(self, task: str, timeout: float = 60.0) -> bool:
        """
        Submit a task and block until it completes (or timeout is reached).

        Args:
            task:    Natural language task description.
            timeout: Maximum seconds to wait (default: 60).

        Returns:
            True if completed, False if timed out.
        """
        # Note: run() will auto-start the agent and print task box first
        # Capture current active task count as baseline
        before = self._active_task_count()
        self._agent.run(task)

        # Wait for the new task to start and then finish.
        # Prevent returning early before the scheduler picks up the task.
        deadline = time.time() + timeout
        task_started = False
        poll_interval = 0.1  # Internal polling frequency
        while time.time() < deadline:
            current = self._active_task_count()
            if not task_started and current > before:
                task_started = True
            elif task_started and current <= before:
                return True
            time.sleep(poll_interval)
        return False
    async def arun(self, task: str, timeout: float = 60.0) -> bool:
        """
        Submit a task asynchronously and wait for its completion.

        Args:
            task:    Natural language task description.
            timeout: Maximum seconds to wait (default: 60).

        Returns:
            True if completed, False if timed out.
        """
        import asyncio
        if not self._agent.running:
            self._agent.start()

        # Capture current active task count as baseline
        before = self._active_task_count()
        await self._agent.run_async(task)

        # Wait for the new task to start and then finish.
        # Prevent returning early before the scheduler picks up the task.
        deadline = time.time() + timeout
        task_started = False
        poll_interval = 0.1  # Internal polling frequency
        while time.time() < deadline:
            current = self._active_task_count()
            if not task_started and current > before:
                task_started = True
            elif task_started and current <= before:
                return True
            await asyncio.sleep(poll_interval)
        return False

    # ─── Human approval ───────────────────────────────────────────────────────

    def get_pending_approvals(self) -> list:
        """Get all approval requests waiting for human decision."""
        return self._agent.get_pending_approvals()

    def approve(self, request_id: str, response: str = "Approved") -> bool:
        """Approve a pending action request."""
        return self._agent.approve(request_id, response)

    def reject(self, request_id: str, reason: str = "Rejected") -> bool:
        """Reject a pending action request."""
        return self._agent.reject(request_id, reason)

    # ─── Inspection ───────────────────────────────────────────────────────────

    def info(self) -> Dict[str, Any]:
        """Return current agent state: running tasks, tools, models, etc."""
        return self._agent.info()

    def get_llm_config_string(self) -> str:
        """Get the LLM configuration string for display.
        
        Returns clean LLM configuration based on what user explicitly provided.
        """
        return self._agent.get_llm_config_string()

    @property
    def usage(self):
        """Token usage statistics across the agent lifecycle."""
        return self._agent.usage
        
    @property
    def memory(self):
        """Returns the attached Memory instance, if any."""
        return self._agent.memory

    @property
    def chat(self):
        """Returns the attached Chat instance."""
        return self._agent.chat

    @property
    def agent_id(self) -> str:
        """Unique identifier for this agent instance."""
        return self._agent.agent_id

    # ─── Context manager support ──────────────────────────────────────────────

    def __enter__(self) -> "Cortex":
        # Don't start here - let run() handle startup so task box appears first
        return self

    def __exit__(self, *_) -> None:
        self.stop()

    async def __aenter__(self) -> "Cortex":
        # Don't start here - let run() handle startup so task box appears first
        return self

    async def __aexit__(self, *_) -> None:
        self.stop()

    def __str__(self) -> str:
        return f"Cortex(id='{self.agent_id}', running={self._agent.running})"

    # ─── Private helpers ──────────────────────────────────────────────────────

    def _active_task_count(self) -> int:
        try:
            return len(self._agent.logger.active_tasks)
        except Exception:
            return 0
