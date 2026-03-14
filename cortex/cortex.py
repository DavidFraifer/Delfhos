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


from delfhos.errors import AgentConfirmationError


class Cortex:
    """
    Cortex AI agent — orchestrates tools, code generation, and execution.

    Args:
        tools:        List of tools: @tool-decorated functions,
                      service tools (Gmail, SQL, Sheets...), and MCP servers.
        light_llm:    Fast LLM model for filtering and simple tasks.
        heavy_llm:    Powerful LLM model for code generation.
        agent_id:     Optional custom agent identifier (auto-generated UUID if not set).
        context:      Optional agent role description. Helps the LLM understand the agent's purpose.
                      E.g. "You are a finance assistant managing accounting reports."
        system_prompt: Alias of `context`. Preferred explicit name for the agent instruction.
        confirm:      Deployment-level confirmation policy. Can be a list of tool kinds 
                      (e.g., ["send", "write"]) or True for all.
        enable_human_approval: If True, the agent will pause and wait for human sign-off
                               before sensitive actions (manual approve/reject mode).
        on_confirm:   Optional callback for approval decisions. Providing this automatically
                      enables human approval.
        validation_mode: If True, run in safe/dry-run mode (no writes).
    """

    def __init__(
        self,
        tools: Optional[List[Union[Connection, Callable, Any]]] = None,
        chat: Optional[Chat] = None,
        memory: Optional[Memory] = None,
        light_llm: str = "gemini-3.1-flash-lite-preview",
        heavy_llm: str = "gemini-3.1-flash-lite-preview",
        agent_id: Optional[str] = None,
        context: Optional[str] = None,
        system_prompt: Optional[str] = None,
        confirm: Optional[Union[bool, List[str], str]] = None,
        file_search_store_name: Optional[str] = None,
        enable_human_approval: bool = False,
        on_confirm: Optional[Callable] = None,
        validation_mode: bool = False,
        trace: Union[str, bool] = "full",
    ):
        resolved_tools = tools or []

        if memory is not None and chat is None:
            chat = Chat(keep=8, summarize=True)

        if isinstance(confirm, list) or (isinstance(confirm, str) and confirm.strip().lower() not in ("all", "none", "false", "")):
            for t in resolved_tools:
                if type(t).__name__ == "Tool" or (callable(t) and hasattr(t, "tool_name") and hasattr(t, "execute")):
                    if not getattr(t, "kind", None):
                        raise AgentConfirmationError(confirm=confirm)

        approval_enabled = bool(enable_human_approval or on_confirm is not None or _has_confirm_policy(confirm))
        resolved_context = system_prompt if system_prompt is not None else context



        self._agent = Agent(
            tools=resolved_tools,
            light_llm=light_llm,
            heavy_llm=heavy_llm,
            agent_id=agent_id,
            validation_mode=validation_mode,
            enable_human_approval=approval_enabled,
            on_confirm=on_confirm,
            confirm=confirm,
            agent_context=resolved_context,
            file_search_store_name=file_search_store_name,
            chat=chat,
            memory=memory,
            trace=trace,
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
        if not self._agent.running:
            self._agent.start()
        self._agent.run(task)

    def run(self, task: str, timeout: float = 60.0, poll_interval: float = 0.5) -> bool:
        """
        Submit a task and block until it completes (or timeout is reached).

        Args:
            task:          Natural language task description.
            timeout:       Maximum seconds to wait (default: 60).
            poll_interval: How often to poll for completion (seconds).

        Returns:
            True if completed, False if timed out.
        """
        if not self._agent.running:
            self._agent.start()

        # Capture current active task count as baseline
        before = self._active_task_count()
        self._agent.run(task)

        # Wait for the new task to appear and then finish
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._active_task_count() <= before:
                # New task started and finished (or never appeared — edge case)
                return True
            time.sleep(poll_interval)
        return False
    async def arun(self, task: str, timeout: float = 60.0, poll_interval: float = 0.5) -> bool:
        """
        Submit a task asynchronously and wait for its completion.

        Args:
            task:          Natural language task description.
            timeout:       Maximum seconds to wait (default: 60).
            poll_interval: How often to poll for completion (seconds).

        Returns:
            True if completed, False if timed out.
        """
        import asyncio
        if not self._agent.running:
            self._agent.start()

        # Capture current active task count as baseline
        before = self._active_task_count()
        await self._agent.run_async(task)

        # Wait for the new task to appear and then finish
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._active_task_count() <= before:
                # New task started and finished
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
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()

    async def __aenter__(self) -> "Cortex":
        self.start()
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
