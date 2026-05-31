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
from typing import List, Optional, Union, Dict, Any, Callable, Iterator, AsyncIterator
from cortex._engine.agent import Agent
from cortex._engine.connection import Connection
from cortex._engine.types import Response, StreamSnapshot
from rich.box import SQUARE
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
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
        agent = Cortex(tools=[Gmail(), Drive()], llm="gemini-3.1-flash-lite")
        agent.start().run("Archive unread emails and summarize to alice@co.com")

    Advanced example with per-tool approval:
        agent = Cortex(
            tools=[
                Gmail(oauth_credentials="oauth.json", allow=["read", "send"], confirm=["send"]),
                SQL(url="postgresql://...", confirm=["write"]),
                Sheets(...),
            ],
            light_llm="gemini-3.1-flash-lite",
            heavy_llm="gemini-3.1-pro",
            vision_llm="gemini-3.1-pro-vision",  # explicit model for image/multimodal tasks
            chat=Chat(keep=5, summarize=True, summarizer_llm="gemini-3.1-flash-lite"),
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
        vision_llm: Model used for image analysis and multimodal tasks. Defaults to heavy_llm.
        chat: Chat(keep=10, summarize=False) for session memory (set Chat.summarizer_llm for compression).
        memory: Persistent memory across sessions (e.g., SQL database).
        system_prompt: Context/role injected into every LLM call.
        on_confirm: Approval callback fn(brief) -> bool. If set, enables human-in-the-loop.
                    Per-tool approval is configured on each tool: Gmail(confirm=["send"]).
        verbose: If True, print detailed execution traces.
        prefilter_mode: Tool prefilter strategy — "auto" (default), "filter", "search", or "off".
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
        vision_llm=None,
        system_prompt: Optional[str] = None,
        on_confirm: Optional[Callable] = None,
        providers: Optional[Dict[str, str]] = None,
        verbose: bool = False,
        prefilter_mode: str = "auto",
        retry_count: int = 1,
        sandbox: str = "auto",
        sandbox_config: Optional[Dict[str, Any]] = None,
        budget_usd: Optional[float] = None,
        comments: str = "readable",
    ):
        """Initialize an Agent (Cortex) with tools and language models.

        Args:
            tools: List of Service tools (Gmail, Drive, SQL, APITool, etc), @tool functions, or Connections.
                   Per-tool approval: set confirm= on each connection, e.g. Gmail(confirm=["send"]).
                   Custom tools: use @tool(confirm=True) to always require approval.
            llm: Single LLM for all operations (e.g., "gemini-3.1-flash-lite").
                 Shorthand for: light_llm=llm, heavy_llm=llm.
            light_llm: (Advanced) Fast LLM for prefiltering/lightweight tasks (requires heavy_llm).
            heavy_llm: (Advanced) Powerful LLM for code generation (requires light_llm).
            vision_llm: Model used for image analysis and multimodal tasks. Defaults to heavy_llm.
            chat: Chat(keep=10, summarize=True) — session memory & auto-summarization (set Chat.summarizer_llm for compression).
            memory: Persistent memory for facts/context (e.g., persisted embeddings).
            system_prompt: Custom instructions injected into every LLM call.
            on_confirm: Approval callback fn(brief) -> bool for custom approval UI.
            verbose: If True, print detailed execution traces and debugging info.
            prefilter_mode: Tool prefilter strategy. "auto" (default): "off" for <10 actions, "filter" for 10–49, "search" for ≥50. "filter" = single LLM call. "search" = iterative LLM search loop. "off" = no prefiltering.
            retry_count: Number of times to auto-retry execution on failure (default: 1).
            providers: Override API keys {"google": "...", "openai": "...", etc}.
            budget_usd: Hard spending cap in USD. Once the cumulative LLM cost across all
                        run() calls reaches this limit, new tasks are blocked until
                        reset_budget() is called. Use agent.total_cost_usd to track spend.
            comments: Narration style for the agent's print() output. "readable" (default)
                      produces structured Markdown for a UI; "speakable" produces conversational
                      first-person prose suited for a text-to-speech engine. Both styles still
                      record the formal tool desc= and the spoken lines in Response.trace.

        Example::

            # Simple (single LLM)
            agent = Agent(
                tools=[Gmail(), Drive()],
                llm="gemini-3.1-flash-lite"
            )
            agent.run("Forward today's reports to alice@co.com")

            # Advanced (multiple LLMs + per-tool approval)
            agent = Agent(
                tools=[
                    SQL(url="...", confirm=["write"]),  # confirm before writes
                    Gmail(oauth_credentials="...", confirm=["send"]),
                ],
                light_llm="gemini-3.1-flash-lite",
                heavy_llm="gemini-3.1-pro",
                vision_llm="gemini-3.1-pro-vision",  # override for image analysis
                chat=Chat(summarizer_llm="gemini-3.1-flash-lite"),  # auto-summarizes
                budget_usd=0.50,                   # refuse new tasks after $0.50 spent
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
            vision_llm=vision_llm,
            on_confirm=on_confirm,
            system_prompt=system_prompt,
            chat=chat,
            memory=memory,
            providers=providers,
            verbose=verbose,
            prefilter_mode=prefilter_mode,
            retry_count=retry_count,
            sandbox=sandbox,
            sandbox_config=sandbox_config,
            budget_usd=budget_usd,
            comments=comments,
            _explicit_llms={
                "light_llm": light_llm is not None,
                "heavy_llm": heavy_llm is not None,
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

    def run_async(self, task: str) -> str:
        """
        Submit a task for execution in the background. Does not wait for completion.

        The agent:
          1. Filters which connections are relevant for the task.
          2. Generates Python code using the LLM.
          3. Executes the code in a background thread.

        Args:
            task: Natural language task description.

        Returns:
            The task_id. Pass it to poll(task_id) to inspect live progress, or
            wait for completion via poll()/stream().
        """
        # Note: run() will auto-start the agent and print task box first
        return self._agent.run(task)

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

    def run_chat(self, message: None = None, timeout: float = 120.0) -> None:
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
            RunChatMessageError: If a message argument is passed (use run() or run_async() instead).
            ValueError: If Chat was not provided when creating the Agent.
        """
        if message is not None:
            from delfhos.errors import RunChatMessageError
            raise RunChatMessageError()

        # Validate that Chat was provided when creating the agent
        if self._agent.chat is None:
            raise ValueError(
                "Agent.run_chat() requires a Chat parameter.\n\n"
                "Create your agent with Chat enabled:\n\n"
                "  from delfhos import Agent, Chat\n"
                "  agent = Agent(\n"
                "      tools=[...],\n"
                "      llm='gemini-3.1-flash-lite',\n"
                "      chat=Chat(summarizer_llm='gemini-3.1-flash-lite')\n"
                "  )\n"
                "  agent.run_chat()"
            )
        
        from cortex._engine.utils.console import console as runtime_console
        from delfhos import __version__

        chat_console = runtime_console.console

        # Ensure _configure_tools() has run so get_available_tools() reflects
        # only the user's tools, not the 7 defaults pre-loaded in Orchestrator.__init__.
        if not self._agent._tools_configured:
            self._agent.start(suppress_startup_message=True)

        def _render_welcome():
            try:
                tools = self._agent.get_available_tools()
            except Exception:
                tools = []
            runtime_console.print_welcome_banner(
                version=__version__,
                llm_config=self._agent.get_llm_config_string(),
                tools=tools,
                agent_id=self._agent.agent_id,
            )

        _render_welcome()

        # Prompt styled with the design tokens directly: stark caret, mono "you",
        # faint separator. No bold (DESIGN.md §11.6), no bright accents.
        # 38;2;R;G;B = truecolor foreground.
        #   #ffffff (stark)  ·  #8e8e8e (text-mute)  ·  #4a4a4a (text-faint)
        prompt_str = (
            "\x1b[38;2;255;255;255m❯\x1b[0m "
            "\x1b[38;2;142;142;142myou\x1b[0m "
            "\x1b[38;2;74;74;74m›\x1b[0m "
        )

        try:
            while True:
                # Pause the live spinner while waiting for user input so Rich's
                # control bytes don't compete with the terminal prompt.
                runtime_console.pause_live(clear_tasks=True)
                try:
                    user_input = input(prompt_str).strip()
                except (EOFError, KeyboardInterrupt):
                    runtime_console.loading_stop_all()
                    chat_console.print("\n  [#8e8e8e]· chat ended.[/#8e8e8e]")
                    break
                finally:
                    # Always restore live rendering (idempotent if _pause_depth already 0).
                    runtime_console.resume_live()

                if not user_input:
                    continue

                lowered = user_input.lower()
                if lowered in {"/exit", "/quit"}:
                    runtime_console.loading_stop_all()
                    chat_console.print(
                        "  [#8e8e8e]· session ended.[/#8e8e8e]\n"
                    )
                    break
                if lowered == "/help":
                    cmd_table = Table.grid(padding=(0, 2))
                    # Eyebrow keys, primary values — matches DESIGN.md §3.3.
                    cmd_table.add_column(style="#ffffff", no_wrap=True)
                    cmd_table.add_column(style="#c8c8c8")
                    cmd_table.add_row("/help",  "show this help")
                    cmd_table.add_row("/clear", "clear the screen and re-print the banner")
                    cmd_table.add_row("/stop",  "stop the underlying agent (resumes on next message)")
                    cmd_table.add_row("/exit",  "end the chat session")
                    cmd_table.add_row("", "")
                    cmd_table.add_row("[#8e8e8e]ctrl-c[/#8e8e8e]", "[#8e8e8e]cancel current input[/#8e8e8e]")
                    cmd_table.add_row("[#8e8e8e]ctrl-d[/#8e8e8e]", "[#8e8e8e]end session[/#8e8e8e]")

                    help_title = Text("commands", style="#8e8e8e")

                    help_panel = Panel(
                        cmd_table,
                        title=help_title,
                        title_align="left",
                        border_style="#2a2a2a",
                        box=SQUARE,
                        expand=False,
                        padding=(1, 2),
                    )
                    chat_console.print(help_panel)
                    chat_console.print()
                    continue
                if lowered == "/clear":
                    chat_console.clear()
                    _render_welcome()
                    continue
                if lowered == "/stop":
                    self.stop()
                    runtime_console.loading_stop_all()
                    chat_console.print(
                        "  [#f59e0b]![/#f59e0b]  agent stopped.  "
                        "[#8e8e8e]send a new message to resume.[/#8e8e8e]\n"
                    )
                    continue

                response = None
                try:
                    response = self.run(user_input, timeout=timeout)
                except Exception as exc:
                    err_title = Text("error", style="#fca5a5")
                    chat_console.print(
                        Panel(
                            Text(str(exc), style="#ffffff"),
                            title=err_title,
                            title_align="left",
                            border_style="#fca5a5",
                            box=SQUARE,
                            expand=False,
                            padding=(0, 2),
                        )
                    )
                finally:
                    # Force-close any lingering spinner before returning to prompt.
                    runtime_console.loading_stop_all()

                # Note: Result is already printed by orchestrator.task_summary() above,
                # so we only need to handle explicit errors here.
                if response is not None and not response.status:
                    err = response.error or "Unknown error"
                    err_title = Text("error", style="#fca5a5")
                    chat_console.print(
                        Panel(
                            Text(str(err), style="#ffffff"),
                            title=err_title,
                            title_align="left",
                            border_style="#fca5a5",
                            box=SQUARE,
                            expand=False,
                            padding=(0, 2),
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

    # ─── Streaming / live status ──────────────────────────────────────────────

    def poll(self, task_id: str) -> StreamSnapshot:
        """
        Return a point-in-time snapshot of a request submitted via run_async().

        The snapshot unifies request state, the live trace (tool calls, pipeline
        phases, and the agent's printed narration), and the output produced so far.

        Args:
            task_id: The id returned by run_async().

        Returns:
            StreamSnapshot — inspect .state ("queued"|"running"|"done"|"error"),
            .events, .output_so_far, and (once terminal) .result / .error / .trace.

        Example::

            task_id = agent.run_async("Summarize my unread emails")
            while True:
                snap = agent.poll(task_id)
                print(snap.state, snap.output_so_far)
                if snap.is_terminal:
                    break
                time.sleep(0.2)
        """
        return self._agent.orchestrator.get_task_snapshot(task_id)

    def stream(
        self, task: str, interval: float = 0.2, timeout: float = 120.0
    ) -> Iterator[StreamSnapshot]:
        """
        Submit a task and yield live snapshots until it finishes (or times out).

        Args:
            task:     Natural language task description.
            interval: Seconds between snapshots (default 0.2).
            timeout:  Max seconds to keep streaming (default 120).

        Yields:
            StreamSnapshot objects. The final yielded snapshot is terminal
            (.is_terminal is True) unless the timeout was reached first.

        Example::

            for snap in agent.stream("Find the cheapest flight and email it to me"):
                print(snap.state, "-", snap.output_so_far[-80:])
        """
        task_id = self.run_async(task)
        deadline = time.time() + timeout
        while time.time() < deadline:
            snap = self.poll(task_id)
            yield snap
            if snap.is_terminal:
                return
            time.sleep(interval)
        # Final attempt after timeout so callers always see the latest state.
        yield self.poll(task_id)

    async def astream(
        self, task: str, interval: float = 0.2, timeout: float = 120.0
    ) -> AsyncIterator[StreamSnapshot]:
        """
        Async variant of stream(): submit a task and yield live snapshots.

        Args:
            task:     Natural language task description.
            interval: Seconds between snapshots (default 0.2).
            timeout:  Max seconds to keep streaming (default 120).

        Yields:
            StreamSnapshot objects, ending with a terminal snapshot.

        Example::

            async for snap in agent.astream("Generate the weekly report"):
                print(snap.state)
        """
        if not self._agent.running:
            self._agent.start()
        task_id = await self._agent.run_async(task)
        deadline = time.time() + timeout
        while time.time() < deadline:
            snap = self.poll(task_id)
            yield snap
            if snap.is_terminal:
                return
            await asyncio.sleep(interval)
        yield self.poll(task_id)

    def serve(self, host: str = "127.0.0.1", port: int = 8080, **uvicorn_kwargs) -> None:
        """
        Expose this agent over HTTP (blocking). Serves a small FastAPI app:

            POST /run               body {"task": "..."} -> {"task_id": "..."}
            GET  /tasks/{id}        -> JSON snapshot (state, events, output_so_far, ...)
            GET  /tasks/{id}/stream -> Server-Sent Events stream of snapshots
            GET  /health            -> {"ok": true}

        Args:
            host: Interface to bind (default 127.0.0.1).
            port: Port to bind (default 8080).
            **uvicorn_kwargs: Extra args forwarded to uvicorn.run().

        To mount the app inside an existing ASGI server instead of running it
        standalone, use: ``from cortex._engine.server import AgentServer`` and
        access ``AgentServer(agent).app``.
        """
        import uvicorn
        from cortex._engine.server import AgentServer

        server = AgentServer(self)
        uvicorn.run(server.app, host=host, port=port, **uvicorn_kwargs)

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

    @property
    def total_cost_usd(self) -> float:
        """Cumulative LLM cost in USD across all run() calls on this agent."""
        return self._agent.total_cost_usd

    def reset_budget(self, budget_usd: Optional[float] = None) -> None:
        """Reset accumulated cost to $0, optionally updating the spending limit.

        Args:
            budget_usd: New limit in USD. Pass None to keep the current limit.

        Example::

            agent.reset_budget()             # clear spend, keep same cap
            agent.reset_budget(budget_usd=1.00)  # clear spend and raise cap to $1
        """
        self._agent.reset_budget(budget_usd=budget_usd)

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
            trace=res.get("trace"),
            files=res.get("output_files", {}),
        )
