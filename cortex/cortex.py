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
import asyncio
from typing import List, Optional, Union, Dict, Any, Callable
from cortex._engine.agent import Agent
from cortex._engine.connection import Connection
from cortex._engine.types import Response
from rich.panel import Panel
from rich.markdown import Markdown
from delfhos.memory import Chat, Memory



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

    Advanced example with per-tool approval:
        agent = Cortex(
            tools=[
                Gmail(oauth_credentials="oauth.json", allow=["read", "send"], confirm=["send"]),
                SQL(url="postgresql://...", confirm=["write"]),
                Sheets(...),
            ],
            light_llm="gemini-3.1-flash-lite-preview",
            heavy_llm="gemini-3.1-pro",
            code_llm="gemini-3.1-pro",        # explicit model for code generation
            vision_llm="gemini-3.1-pro-vision",  # explicit model for image/multimodal tasks
            chat=Chat(keep=5, summarize=True, summarizer_llm="gemini-3.1-flash-lite-preview"),
            system_prompt="You are a data analyst. Be thorough.",
            on_confirm=lambda brief: input(f"Approve {brief}? ").lower() == "y"
        )

    WebSearch Tip: Request specific formats in your query for structured results:
        agent.run("Find mortgage rate. Ask WebSearch to return ONLY the percentage.")
        agent.run("Top 3 AI trends. Request: Format as 1. trend, 2. trend, 3. trend")
        agent.run("COVID stats. Request: Return JSON with country and cases fields.")

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
                    Per-tool approval is configured on each tool: Gmail(confirm=["send"]).
        verbose: If True, print detailed execution traces.
        enable_prefilter: If True, use LLM to pre-filter relevant tools before code generation (default: False).
        providers: API key overrides {\"google\": \"...\", \"openai\": \"...\", etc}.
    """

    def __init__(
        self,
        tools: Optional[List[Union[Connection, Callable, Any]]] = None,
        chat: Optional[Chat] = None,
        memory: Optional[Memory] = None,
        llm=None,
        light_llm=None,
        heavy_llm=None,
        code_llm=None,
        vision_llm=None,
        system_prompt: Optional[str] = None,
        on_confirm: Optional[Callable] = None,
        providers: Optional[Dict[str, str]] = None,
        verbose: bool = False,
        enable_prefilter: bool = False,
        retry_count: int = 1,
    ):
        """Initialize an Agent (Cortex) with tools and language models.

        Args:
            tools: List of Service tools (Gmail, Drive, SQL, APITool, etc), @tool functions, or Connections.
                   Per-tool approval: set confirm= on each connection, e.g. Gmail(confirm=["send"]).
                   Custom tools: use @tool(confirm=True) to always require approval.
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
            verbose: If True, print detailed execution traces and debugging info.
            enable_prefilter: If True, use LLM to pre-filter relevant tools before code generation (default: False, disabled).
            retry_count: Number of times to auto-retry execution on failure (default: 1).
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
                    SQL(url="...", confirm=["write"]),  # confirm before writes
                    Gmail(oauth_credentials="...", confirm=["send"]),
                ],
                light_llm="gemini-3.1-flash-lite-preview",
                heavy_llm="gemini-3.1-pro",
                code_llm="gemini-3.1-pro",        # override for code generation
                vision_llm="gemini-3.1-pro-vision",  # override for image analysis
                chat=Chat(summarizer_llm="gemini-3.1-flash-lite-preview"),  # auto-summarizes
                verbose=True
            )
        """
        resolved_tools = tools or []
        if memory is not None and chat is None:
            chat = Chat(keep=8, summarize=True)

        self._agent = Agent(
            tools=resolved_tools,
            llm=llm,
            light_llm=light_llm,
            heavy_llm=heavy_llm,
            code_generation_llm=code_llm,
            vision_llm=vision_llm,
            on_confirm=on_confirm,
            system_prompt=system_prompt,
            chat=chat,
            memory=memory,
            providers=providers,
            verbose=verbose,
            enable_prefilter=enable_prefilter,
            retry_count=retry_count,
            _explicit_llms={
                "light_llm": light_llm is not None,
                "heavy_llm": heavy_llm is not None,
                "code_generation_llm": code_llm is not None,
                "vision_llm": vision_llm is not None
            }
        )



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

    def run(self, task: str, timeout: float = 60.0) -> Response:
        """
        Submit a task and block until it completes (or timeout is reached).

        Args:
            task:    Natural language task description.
            timeout: Maximum seconds to wait (default: 60).

        Returns:
            Response object containing the final result, cost, and metadata.
        """
        task_id = self._agent.run(task)

        deadline = time.time() + timeout
        poll_interval = 0.1
        while time.time() < deadline:
            res = self._agent.orchestrator.task_results.get(task_id)
            if res is not None:
                return self._build_response(res)
            time.sleep(poll_interval)
        return Response(text="Timeout", status=False, error="Timeout waiting for task")

    def run_chat(self, timeout: float = 120.0) -> None:
        """
        Start a synchronous interactive chat loop in the console.

        This method does not accept a task argument. Instead, it opens a
        terminal chat session where each user message is executed with `run()`
        and control returns to the prompt after every response.

        Commands:
            /exit, /quit: End chat session.
            /help: Show quick help.
            /stop: Stop the underlying agent process (next message auto-starts it again).

        Args:
            timeout: Maximum seconds to wait per message (default: 120).
        
        Raises:
            ValueError: If Chat was not provided when creating the Agent.
        """
        # Validate that Chat was provided when creating the agent
        if self._agent.chat is None:
            raise ValueError(
                "Agent.run_chat() requires a Chat parameter.\n\n"
                "Create your agent with Chat enabled:\n\n"
                "  from delfhos import Agent, Chat\n"
                "  agent = Agent(\n"
                "      tools=[...],\n"
                "      llm='gemini-3.1-flash-lite-preview',\n"
                "      chat=Chat(summarizer_llm='gemini-3.1-flash-lite-preview')\n"
                "  )\n"
                "  agent.run_chat()"
            )
        
        from cortex._engine.utils.console import console as runtime_console

        chat_console = runtime_console.console

        welcome = Panel(
            "[bold cyan]Welcome to Delfhos[/bold cyan]\n\n"
            "Type your request and press Enter\n"
            "[dim]Type /help for commands[/dim]",
            title="[bold cyan]Interactive Chat[/bold cyan]",
            border_style="cyan",
            expand=False,
            padding=(1, 2),
        )
        chat_console.print(welcome)
        chat_console.print()  # Blank line for spacing

        try:
            while True:
                # Pause the live spinner while waiting for user input so Rich's
                # control bytes don't compete with the terminal prompt.
                runtime_console.pause_live(clear_tasks=True)
                try:
                    user_input = input("You > ").strip()
                except (EOFError, KeyboardInterrupt):
                    runtime_console.loading_stop_all()
                    chat_console.print("\n[dim]Chat ended.[/dim]")
                    break
                finally:
                    # Always restore live rendering (idempotent if _pause_depth already 0).
                    runtime_console.resume_live()

                if not user_input:
                    continue

                lowered = user_input.lower()
                if lowered in {"/exit", "/quit"}:
                    runtime_console.loading_stop_all()
                    chat_console.print("[dim]Goodbye.[/dim]\n")
                    break
                if lowered == "/help":
                    help_panel = Panel(
                        "[bold cyan]/help[/bold cyan]   Show this help\n"
                        "[bold cyan]/stop[/bold cyan]   Stop agent (will restart on next message)\n"
                        "[bold cyan]/exit[/bold cyan]   Exit chat\n"
                        "[bold cyan]/clear[/bold cyan]  Clear screen",
                        title="[bold]Commands[/bold]",
                        border_style="blue",
                        padding=(1, 2),
                    )
                    chat_console.print(help_panel)
                    chat_console.print()  # Spacing
                    continue
                if lowered == "/clear":
                    chat_console.clear()
                    chat_console.print(welcome)
                    chat_console.print()
                    continue
                if lowered == "/stop":
                    self.stop()
                    runtime_console.loading_stop_all()
                    chat_console.print("[yellow]Agent stopped.[/yellow] [dim]Send a new message to resume.[/dim]\n")
                    continue

                response = None
                try:
                    response = self.run(user_input, timeout=timeout)
                except Exception as exc:
                    chat_console.print(
                        Panel(
                            f"[red]{exc}[/red]",
                            title="[bold red]✗ Error[/bold red]",
                            border_style="red",
                            expand=False,
                            padding=(1, 2),
                        )
                    )
                finally:
                    # Force-close any lingering spinner before returning to prompt.
                    runtime_console.loading_stop_all()

                # Note: Result is already printed by orchestrator.task_summary() above,
                # so we only need to handle explicit errors here.
                if response is not None and not response.status:
                    err = response.error or "Unknown error"
                    chat_console.print(
                        Panel(
                            f"[red]{err}[/red]",
                            title="[bold red]✗ Error[/bold red]",
                            border_style="red",
                            expand=False,
                            padding=(1, 2),
                        )
                    )

                chat_console.print()  # Blank line for spacing between responses
        finally:
            runtime_console.loading_stop_all()

    async def arun(self, task: str, timeout: float = 60.0) -> Response:
        """
        Submit a task asynchronously and wait for its completion.

        Args:
            task:    Natural language task description.
            timeout: Maximum seconds to wait (default: 60).

        Returns:
            Response object containing the final result, cost, and metadata.
        """
        if not self._agent.running:
            self._agent.start()

        task_id = await self._agent.run_async(task)

        deadline = time.time() + timeout
        poll_interval = 0.1
        while time.time() < deadline:
            res = self._agent.orchestrator.task_results.get(task_id)
            if res is not None:
                return self._build_response(res)
            await asyncio.sleep(poll_interval)
            
        return Response(text="", status=False, error="Timeout waiting for task")

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
    def retry_count(self) -> int:
        """Number of times to auto-retry execution on failure."""
        return self._agent.retry_count

    @retry_count.setter
    def retry_count(self, value: int):
        self._agent.retry_count = value

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
            
    def _build_response(self, res: dict) -> Response:
        status = res.get("completed", False)
        error = res.get("final_message") if not status else None
        text = res.get("final_message", "") if status else ""
        return Response(
            text=text,
            status=status,
            error=error,
            cost_usd=res.get("cost_usd"),
            duration_ms=int(res.get("duration", 0) * 1000),
            trace=res.get("trace")
        )
