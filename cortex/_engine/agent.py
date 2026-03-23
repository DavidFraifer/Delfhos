from typing import List, Union, Optional, Dict, Any, Literal, Callable
from .core.orchestrator import Orchestrator
from .types import TokenUsage
from delfhos.memory import Chat, Memory
from .config import configure_api_keys
from .utils.logger import CORTEXLogger
from .utils.console import console
from .utils import report_error, raise_error
from .connection import Connection
from .trace import Trace
import uuid
import threading
import time
import asyncio
from datetime import datetime, timedelta, timezone


def _utcnow() -> datetime:
    """Return current UTC time with timezone information."""
    return datetime.now(timezone.utc)


def _has_confirm_policy(confirm_policy: Any) -> bool:
    if confirm_policy is None:
        return True
    if isinstance(confirm_policy, bool):
        return confirm_policy
    if isinstance(confirm_policy, list):
        return len(confirm_policy) > 0
    if isinstance(confirm_policy, str):
        return confirm_policy.strip().lower() not in ("none", "false", "")
    return False


def _tools_have_confirm_policies(tools: Optional[List[Union[str, Callable, Connection]]]) -> bool:
    if not tools:
        return False
    for configured_tool in tools:
        if _has_confirm_policy(getattr(configured_tool, "confirm", None)):
            return True
    return False

_CLIENT_MAP = {
    "gmail": ("cortex._engine.tools.gmail.gmail_client", "GmailClient"),
    "sheets": ("cortex._engine.tools.sheets.gsheets_client", "GoogleSheetsClient"),
    "docs": ("cortex._engine.tools.docs.docs_client", "GoogleDocsClient"),
    "drive": ("cortex._engine.tools.drive.gdrive_client", "GoogleDriveClient"),
    "calendar": ("cortex._engine.tools.calendar.calendar_client", "GoogleCalendarClient"),
}


class Agent:
    """
    An autonomous agent that executes goals using tools, LLMs, and sandboxed Python code generation.
    
    The agent preprocesses tools (prefilter), generates optimized Python code, executes it
    in a sandbox, and iterates with confirmation/feedback until the goal succeeds.
    
    Example (simple):
        agent = Agent(tools=[Gmail(), Drive()], llm="gemini-3.1-flash-lite-preview")
        agent.start().run("Send yesterday's reports to alice@co.com")
    
    Example (advanced with multiple LLMs and per-tool approval):
        agent = Agent(
            tools=[
                Gmail(oauth_credentials="secrets.json", allow=["read", "send"], confirm=["send"]),
                SQL(host="localhost", database="main", confirm=["write"]),
            ],
            light_llm="gemini-3.1-flash-lite-preview",  # for prefiltering
            heavy_llm="gemini-3.1-pro",  # for code generation
            chat=Chat(keep=5, summarize=True),
            system_prompt="You are a data analyst. Be precise."
        )
        result = agent.run("Find Q3 trends in revenue and email summary to ops@co.com")
    
    Args:
        tools: List of tool names (str), async functions, or Connection instances.
               Set confirm= on each Connection/Tool to require approval for specific actions.
        llm: Single LLM for all operations (e.g., "gemini-3.1-flash-lite-preview").
             Shorthand for: light_llm=llm, heavy_llm=llm.
        light_llm: (Advanced) LLM for prefiltering/lightweight tasks (required if not using llm).
        heavy_llm: (Advanced) LLM for code generation (required if not using llm).
        code_generation_llm: Model used specifically for Python code generation. Defaults to heavy_llm.
        vision_llm: Model used for image analysis and multimodal tasks. Defaults to heavy_llm.
        chat: Chat(keep=10, summarize=False) — session memory & summarization.
        memory: Optional persistent memory (e.g., SQL database).
        system_prompt: Context injected into every LLM call.
        on_confirm: Approval callback fn(request_id, message) for custom approval handling.
        verbose: If True, print detailed execution traces.
        providers: API key overrides {"google": "...", "openai": "..."}, etc.
    """
    def __init__(self, tools: List[Union[str, Callable, Connection]], llm: Optional[str] = None, light_llm: Optional[str] = None, heavy_llm: Optional[str] = None,
                 agent_id: Optional[str] = None, auto_stop_timeout: Optional[int] = None,
                 on_confirm: Optional[Callable] = None,
                 system_prompt: Optional[str] = None,
                 prefilter_llm: Optional[str] = None,
                 code_generation_llm: Optional[str] = None,
                 vision_llm: Optional[str] = None,
                 chat: Optional[Chat] = None,
                 memory: Optional[Memory] = None,
                 providers: Optional[Dict[str, str]] = None,
                 verbose: bool = False,
                 enable_prefilter: bool = False,
                 _explicit_llms: Optional[Dict[str, bool]] = None):
        """Initialize an Agent with tools and language models.
        
        Args:
            tools: List of Connection objects, @tool functions, or string names.
                   Per-tool approval: set confirm= on each tool (e.g., Gmail(confirm=["send"])).
            llm: Single LLM model for all operations (e.g., "gemini-3.1-flash-lite-preview").
            light_llm: Fast LLM for filtering/analysis (use with heavy_llm).
            heavy_llm: Powerful LLM for code generation (use with light_llm).
            code_generation_llm: Model used specifically for Python code generation. Defaults to heavy_llm.
            vision_llm: Model used for image analysis and multimodal tasks. Defaults to heavy_llm.
            agent_id: Custom agent identifier (auto-generated if omitted).
            auto_stop_timeout: Auto-stop after N seconds of inactivity (None = never auto-stop).
            on_confirm: Callback fn(request_id, message) for custom approval handling.
            system_prompt: Custom system instructions for code generation.
            chat: Chat instance for session memory with auto-summarization (set Chat.summarizer_llm for compression).
            memory: Memory instance for persistent semantic storage.
            enable_prefilter: If True, use LLM to pre-filter relevant tools before code generation (default: False, disabled).
            verbose: If True, print execution traces and debugging info.
            providers: Dict of API provider overrides (internal use).
        
        Raises:
            CORTEXError: If llm configuration is invalid (must provide either llm OR both light_llm+heavy_llm).
        
        Example::
        
            # Simple mode (single LLM for everything)
            agent = Agent(
                tools=[Gmail(), Drive()],
                llm="gemini-3.1-flash-lite-preview"
            )
            
            # Advanced mode (light + heavy LLM split)
            agent = Agent(
                tools=[Gmail(), Drive(), SQL(url="...")],
                light_llm="gemini-3.1-flash-lite-preview",  # fast, cheap
                heavy_llm="gemini-3.1-pro",  # powerful, for code generation
                chat=Chat(keep=10),  # session memory
                verbose=True  # see execution details
            )
        """
        self._api_configured = False
        self._providers = providers
        
        # Validate that user has explicitly chosen LLM configuration
        # User MUST choose either:
        # 1. A single "llm" for everything (simple mode)
        # 2. Both "light_llm" AND "heavy_llm" (advanced mode)
        if llm is None and (light_llm is None or heavy_llm is None):
            raise_error("AGT-002", context={
                "reason": "LLM configuration required",
                "hint": "Please provide either:\n"
                       "  1. A single 'llm' parameter (used for all operations), OR\n"
                       "  2. Both 'light_llm' and 'heavy_llm' parameters (light_llm for filtering, heavy_llm for code generation)"
            })
        
        # User chose single llm for everything
        if llm is not None and light_llm is None and heavy_llm is None:
            resolved_light_llm = llm
            resolved_heavy_llm = llm
            use_single_llm = True
        # User chose light_llm and heavy_llm explicitly
        elif light_llm is not None and heavy_llm is not None:
            resolved_light_llm = light_llm
            resolved_heavy_llm = heavy_llm
            # llm parameter is ignored if light_llm and heavy_llm are provided
            use_single_llm = False
        # Invalid mix (e.g., only light_llm without heavy_llm)
        else:
            raise_error("AGT-002", context={
                "reason": "Incomplete LLM configuration",
                "hint": "You provided light_llm or heavy_llm, but not both. Please provide:\n"
                       "  1. A single 'llm' parameter, OR\n"
                       "  2. BOTH 'light_llm' AND 'heavy_llm' parameters"
            })
        
        # Track which LLMs were explicitly provided by the user (not just defaulted)
        # If _explicit_llms is provided (from Cortex wrapper), use that; otherwise infer from Parameters
        if _explicit_llms:
            # Use the explicit tracking from Cortex wrapper
            self._explicit_llm_config = {
                "llm": _explicit_llms.get("llm", llm is not None),
                "light_llm": _explicit_llms.get("light_llm", light_llm is not None),
                "heavy_llm": _explicit_llms.get("heavy_llm", heavy_llm is not None),
                "prefilter_llm": prefilter_llm is not None,
                "code_generation_llm": code_generation_llm is not None,
                "vision_llm": vision_llm is not None
            }
        else:
            # Infer from parameters (for direct Agent usage)
            self._explicit_llm_config = {
                "llm": llm is not None,
                "light_llm": light_llm is not None,
                "heavy_llm": heavy_llm is not None,
                "prefilter_llm": prefilter_llm is not None,
                "code_generation_llm": code_generation_llm is not None,
                "vision_llm": vision_llm is not None
            }

        approval_enabled = bool(
            on_confirm is not None
            or _tools_have_confirm_policies(tools)
        )
        
        # Generate agent ID if not provided - use full UUID for consistency with database
        self.agent_id = agent_id or str(uuid.uuid4())
        self.enable_human_approval = approval_enabled
        self.on_confirm = on_confirm
        self.verbose = verbose
        self.trace_mode = "full" if verbose else "minimal"
        self._last_trace = None
        
        # Basic model validation (accept provider-compatible model IDs, not a fixed list)
        models_to_validate = [
            (resolved_light_llm, "light_llm"),
            (resolved_heavy_llm, "heavy_llm"),
            (prefilter_llm, "prefilter_llm"),
            (code_generation_llm, "code_generation_llm"),
            (vision_llm, "vision_llm")
        ]
        
        for model, name in models_to_validate:
            if model is None:
                continue
            if not isinstance(model, str) or not model.strip():
                raise_error("AGT-002", context={"model": model, "model_type": name, "reason": "Model must be a non-empty string"})
        
        self.tools = tools
        self.llm = llm  # Store original choice (could be None if using light_llm/heavy_llm)
        self.light_llm = resolved_light_llm
        self.heavy_llm = resolved_heavy_llm

        # Specific model configurations - use appropriate defaults based on what user chose
        self.prefilter_llm = prefilter_llm or self.light_llm
        self.code_generation_llm = code_generation_llm or self.heavy_llm
        self.vision_llm = vision_llm or self.heavy_llm
        self.chat = chat
        self.memory = memory
        
        self.logger = CORTEXLogger() 
        self.usage = TokenUsage()
        
        self.orchestrator = Orchestrator(
            logger=self.logger,
            light_llm=self.light_llm,
            heavy_llm=self.heavy_llm,
            agent_id=self.agent_id,
            on_confirm=on_confirm,
            approval_enabled=approval_enabled,
            system_prompt=system_prompt,
            prefilter_llm=self.prefilter_llm,
            code_generation_llm=self.code_generation_llm,
            vision_llm=self.vision_llm,
            token_usage=self.usage,
            memory=memory,
            trace_mode=self.trace_mode,
            trace_callback=self._update_trace,
            llm_config=self.get_llm_config_string(),
            verbose="high" if self.verbose else "low",
            enable_prefilter=enable_prefilter
        )
        self.running = False
        self.last_called = None  # Track when the agent was last used
        self.created_at = _utcnow()
        
        # Auto-stop functionality (disabled by default - agent stays open until user stops it)
        self.auto_stop_timeout = auto_stop_timeout
        self.last_activity = self.created_at
        self.inactivity_timer = None
        self.timer_lock = threading.Lock()

        # Wire chat so every completed task's output is captured as an assistant turn
        if self.chat is not None:
            def _append_assistant_response(task_id: str, message: str):
                if message and message.strip() and message != "Task completed successfully":
                    self.chat.append("assistant", message)
            self.orchestrator.on_task_complete = _append_assistant_response

        self._tools_configured = False

    def _update_trace(self, trace: Trace):
        self._last_trace = trace

    def _get_summarizer_llm(self) -> str:
        """Get the LLM to use for chat summarization.

        Returns the LLM from chat.summarizer_llm if set, otherwise defaults to light_llm.
        """
        if self.chat and self.chat.summarizer_llm:
            return self.chat.summarizer_llm
        return self.light_llm
    
    def _warmup_clients(self):
        """Eagerly build Google API clients for all connections.
        
        This pre-warms the module-level client caches (OAuth refresh + service build)
        so the first tool call doesn't pay the ~300-500ms cold-start penalty.
        """
        warmed = []
        for conn in self.orchestrator.tools.connections.values():
            tool_name = getattr(conn, "tool_name", "").lower()
            if tool_name not in _CLIENT_MAP or not conn.is_active():
                continue
            
            module_path, class_name = _CLIENT_MAP[tool_name]
            try:
                import importlib
                mod = importlib.import_module(module_path)
                client_cls = getattr(mod, class_name)
                creds = conn.get_credentials()
                client = client_cls(creds)
                # Trigger OAuth refresh + API service build → populates module cache
                client._build_credentials()
                warmed.append(tool_name)
            except Exception:
                pass  # Non-fatal — client will be built lazily on first use
        
        if warmed:
            console.debug("Client warm-up", f"Pre-built API clients: {', '.join(warmed)}", agent_id=self.agent_id)
    
    def _configure_tools(self):
        """Configure which tools are available to the orchestrator"""
        self.orchestrator.tools.tools.clear()
        from .tools.internal_tools import internal_tools
        
        # Allow LLM-only mode (tools=[]): no user tools are registered,
        # but the orchestrator can still complete pure-LLM tasks.
        if not self.tools:
            return
        
        for tool in self.tools:
            if isinstance(tool, Connection):
                # If it's an MCP connection, compile it (introspect + register)
                if tool.connection_name == "mcp" or getattr(tool, "TOOL_NAME", "") == "mcp" or hasattr(tool, "compile"):
                    tool.compile()

                # Connection - add it to the orchestrator
                self.orchestrator.add_connection(tool, agent_id=self.agent_id)
                # Also add the corresponding internal tool function
                tool_name = tool.tool_name.lower() if hasattr(tool, 'tool_name') else None
                if tool_name and tool_name in internal_tools:
                    self.orchestrator.add_tool(tool_name, internal_tools[tool_name])
            elif callable(tool) and hasattr(tool, "tool_name") and hasattr(tool, "execute"):
                # Custom user-defined Tool abstraction
                t_name = getattr(tool, "tool_name", "")
                # Use the precise API doc if available (includes param names, types, return type)
                if hasattr(tool, "api_doc") and callable(tool.api_doc):
                    t_desc = tool.api_doc()
                else:
                    t_desc = getattr(tool, "description", "")
                self.orchestrator.add_tool(t_name, tool, description=t_desc)
            elif isinstance(tool, str) and tool in internal_tools:
                # Built-in tool by name - no description needed
                self.orchestrator.add_tool(tool, internal_tools[tool])
            elif callable(tool):
                report_error(
                    "TOL-001",
                    context={
                        "tool": str(tool),
                        "tool_type": type(tool).__name__,
                        "hint": "Decorate custom functions with @tool before passing to Agent(tools=[...]).",
                    },
                )
            else:
                report_error("TOL-001", context={"tool": str(tool), "tool_type": type(tool).__name__})
    
    def add_tool(self, name: str, func):
        """Register a new tool (function or Connection) with the running agent.
        
        Useful for dynamic tool injection after agent startup.
        
        Args:
            name: Label for the tool (used in error messages and logs).
            func: A callable function or Connection instance.
        
        Example::
        
            @tool
            def get_time() -> str:
                return time.strftime("%H:%M")
            
            agent.add_tool("time", get_time)
        """
        self.orchestrator.add_tool(name, func)
    
    def get_llm_config_string(self) -> str:
        """Generate LLM configuration string for display in execution summary.
        
        Returns clean LLM configuration based on what user explicitly provided:
        - If only llm was provided: "llm: X"
        - If light_llm and heavy_llm provided: "light_llm: X, heavy_llm: X"
        - If individual specialized LLMs provided: show all explicitly provided ones
        """
        explicit = self._explicit_llm_config
        
        # Count which LLMs were explicitly provided
        explicitly_provided = [k for k, v in explicit.items() if v]
        
        # Case 1: User chose single llm for everything
        if explicit["llm"] and not explicit["light_llm"] and not explicit["heavy_llm"]:
            return f"llm: {self.llm}"
        
        # Case 2: User chose light_llm and heavy_llm, no specialized overrides
        if explicit["light_llm"] and explicit["heavy_llm"]:
            specialized = [k for k in ["code_generation_llm", "vision_llm", "prefilter_llm"]
                          if explicit.get(k)]

            # Check if chat has custom summarizer_llm
            chat_has_custom_summarizer = self.chat and self.chat.summarizer_llm and self.chat.summarizer_llm != self.light_llm

            if not specialized and not chat_has_custom_summarizer:
                # No specialized overrides, show just light and heavy
                return f"light_llm: {self.light_llm}, heavy_llm: {self.heavy_llm}"

            # User has specialized overrides - show all explicitly provided
            llm_parts = [f"light_llm: {self.light_llm}", f"heavy_llm: {self.heavy_llm}"]

            if explicit["code_generation_llm"] and self.code_generation_llm != self.heavy_llm:
                llm_parts.append(f"code_generation_llm: {self.code_generation_llm}")
            if explicit["vision_llm"] and self.vision_llm != self.heavy_llm:
                llm_parts.append(f"vision_llm: {self.vision_llm}")
            if chat_has_custom_summarizer:
                llm_parts.append(f"summarizer_llm: {self.chat.summarizer_llm}")
            if explicit["prefilter_llm"] and self.prefilter_llm != self.light_llm:
                llm_parts.append(f"prefilter_llm: {self.prefilter_llm}")

            return ", ".join(llm_parts)
        
        # Fallback (shouldn't reach here due to validation)
        return f"light_llm: {self.light_llm}, heavy_llm: {self.heavy_llm}"
    
    def _reset_inactivity_timer(self):
        """Reset the inactivity timer when activity occurs"""
        with self.timer_lock:
            self.last_activity = _utcnow()
            
            # Cancel existing timer
            if self.inactivity_timer:
                if self.inactivity_timer.is_alive():
                    self.inactivity_timer.cancel()
                self.inactivity_timer = None
            
            # Start new timer only if agent is running and auto_stop_timeout is set
            if self.running and self.auto_stop_timeout is not None:
                self.inactivity_timer = threading.Timer(self.auto_stop_timeout, self._auto_stop_due_to_inactivity)
                self.inactivity_timer.daemon = True
                self.inactivity_timer.start()
    
    def _auto_stop_due_to_inactivity(self):
        """Automatically stop the agent due to inactivity"""
        with self.timer_lock:
            # Double-check that agent is still running and we still want to auto-stop
            if self.running and self.auto_stop_timeout is not None:
                console.warning("Auto-stop", f"Agent automatically stopped due to {self.auto_stop_timeout/60:.1f} minutes of inactivity", agent_id=self.agent_id)
                self.stop()
            # Clear the timer reference since this method means the timer has fired
            self.inactivity_timer = None
    
    def _cancel_inactivity_timer(self):
        """Cancel the inactivity timer"""
        with self.timer_lock:
            if self.inactivity_timer:
                if self.inactivity_timer.is_alive():
                    self.inactivity_timer.cancel()
                self.inactivity_timer = None
        
    def start(self, suppress_startup_message: bool = False):
        """Initialize the agent and prepare it to execute tasks.
        
        Usually called automatically by `run()`, but you can call it explicitly
        if you need to control the agent lifecycle.
        
        Args:
            suppress_startup_message: If True, don't log the "Agent started" message.
        
        Example::
        
            agent.start()
            agent.run("Do something")
            agent.run("Do something else")
            agent.stop()  # Clean up resources
        """
        if not self.running:
            # Deferred tool setup (MCP compile, client warmup) — runs once
            if not self._tools_configured:
                self._configure_tools()
                self._warmup_clients()
                self._tools_configured = True

            self.orchestrator.start()
            self.running = True
            
            # Only log "Agent started" if not auto-starting from run()
            # (run() prints task box first, so we skip this to avoid duplication)
            if not suppress_startup_message:
                available_tools = list(self.orchestrator.tools.tools.keys())
                console.system("Agent started", f"Available tools: {', '.join(available_tools)}", agent_id=self.agent_id)
            
            # Start inactivity timer
            self._reset_inactivity_timer()
        
    def stop(self, task_id: Optional[str] = None):
        """Stop a specific task or the entire agent
        
        Args:
            task_id (Optional[str]): If provided, stops the specific task. 
                                   If None or empty, stops the entire agent.
        """
        if task_id:
            # Stop specific task
            if self.logger and task_id in self.logger.active_tasks:
                # Mark task as stopped and log completion
                console.info("Task stopped", "Task manually stopped", task_id=task_id, agent_id=self.agent_id)
                self.logger.complete_task(task_id, "stopped", 0.0)
                console.success("Task termination", "Task has been stopped", agent_id=self.agent_id)
            else:
                # Task not found or logging not enabled
                if not self.logger:
                    report_error("AGT-004", context={"task_id": task_id, "reason": "logging disabled"})
                else:
                    report_error("AGT-004", context={"task_id": task_id, "reason": "task not found", "active_tasks": list(self.logger.active_tasks.keys())})
        else:
            # Stop entire agent
            if self.running:
                # Stop all active tasks first
                if self.logger and self.logger.active_tasks:
                    active_task_ids = list(self.logger.active_tasks.keys())
                    console.info("Agent shutdown", f"Stopping {len(active_task_ids)} active tasks", agent_id=self.agent_id)
                    
                    for active_task_id in active_task_ids:
                        console.debug("Task cleanup", "Stopping task", task_id=active_task_id, agent_id=self.agent_id)
                        self.logger.complete_task(active_task_id, "stopped", 0.0)
                
                # Stop the orchestrator
                self.orchestrator.stop()
                self.running = False
                
                # Cancel inactivity timer
                self._cancel_inactivity_timer()
                # Memory extraction is now expected to happen during task execution
                # via runtime `memory.save(...)` calls in generated code.
                if self.chat is not None and getattr(self.chat, "persist", True) is False:
                    self.chat.clear()

                console.system("Agent stopped", "All tasks terminated", agent_id=self.agent_id)
            else:
                report_error("AGT-005", context={"agent_id": self.agent_id, "current_state": "not running"})
    
    def _prepare_run_task(self) -> str:
        """Shared setup for agent execution."""
        if not self.running:
            raise_error("AGT-001", context={"agent_id": self.agent_id, "operation": "run task"})
        
        self.last_called = _utcnow()
        self._reset_inactivity_timer()
        
        task_id = str(uuid.uuid4())
        
        if self.logger:
            self.logger.start_task(task_id, "Conversation Summarization", self.agent_id)
            
        return task_id

    async def _compress_chat_if_needed(self, task_id: str):
        """Perform mid-session summarization asynchronously using a chat snapshot."""
        if not self.chat.summarize or not self.chat.needs_compression():
            return
            
        # Snapshot the messages so the LLM operates on a fixed history,
        # allowing new messages to arrive safely while this runs in the background.
        messages_snapshot = self.chat.get_messages_for_compression()
        compressed_count = len(messages_snapshot)
        
        from .internal.llm import llm_completion_async

        # Include any prior summary so it isn't lost across multiple compression rounds
        prior_summary = self.chat.summary
        prompt = "Summarize the following conversation concisely, incorporating any prior summary. Focus on key details, facts, and tasks.\n\n"
        if prior_summary:
            prompt += f"PREVIOUS SUMMARY: {prior_summary}\n\n"
        prompt += "RECENT MESSAGES:\n"
        for msg in messages_snapshot:
            prompt += f"{msg['role'].upper()}: {msg['content']}\n"
            
        try:
            import time
            start_comp = time.time()
            summarizer = self._get_summarizer_llm()
            result, token_info = await llm_completion_async(
                prompt=prompt,
                model=summarizer,
                max_tokens=300,
                temperature=0.3
            )
            dur_comp = int((time.time() - start_comp) * 1000)

            if token_info and "total_tokens" in token_info:
                self.usage.summarizer.add(token_info)
                if self.logger and task_id:
                    self.logger.add_tokens(task_id, token_info, model=summarizer, function_name="mid_session_compress")

            if self._last_trace:
                from .trace import ChatCompressionTrace
                from datetime import datetime
                self._last_trace.chat_compression = ChatCompressionTrace(
                    triggered_at=datetime.fromtimestamp(start_comp),
                    model_used=summarizer,
                    messages_before=compressed_count,
                    messages_after=1,
                    summary_generated=result.strip(),
                    duration_ms=dur_comp,
                    tokens_input=token_info.get("input_tokens", 0) if token_info else 0,
                    tokens_output=token_info.get("output_tokens", 0) if token_info else 0
                )
                
            new_summary = result.strip()
            self.chat.apply_compression(new_summary, compressed_count)
                
        except Exception as e:
            console.error("CHAT COMPRESSION", f"Summarization failed: {str(e)}", agent_id=self.agent_id)

    async def _session_close_boundary(self):
        """Unified LLM call to extract long-term memory at the end of a session."""
        if self.memory is None:
            return
            
        if self.chat is None or (not self.chat._messages and not self.chat.summary):
            return
            
        from .internal.llm import llm_completion_async
        import json
        
        session_close_start = time.time()
        text_context = ""
        if self.chat is not None and self.chat.summary:
            text_context += f"PREVIOUS SUMMARY: {self.chat.summary}\n\n"
        text_context += "RECENT MESSAGES:\n"
        if self.chat is not None:
            for msg in self.chat._messages:
                text_context += f"{msg['role'].upper()}: {msg['content']}\n"
            
        prompt = f"""You are a memory extraction system. Extract long-term actionable knowledge into a list of facts.
Guidelines: {self.memory.guidelines if self.memory.guidelines else 'Extract relevant facts, user preferences, and final conclusions.'}

{text_context}

Return a JSON object with a single key "facts" containing an array of extracted fact strings.
If there are no new facts, return an empty array: {{"facts": []}}
Never return null, "none", or plain text."""
        
        try:
            result, token_info = await llm_completion_async(
                prompt=prompt,
                model=self.light_llm,
                max_tokens=500,
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            if token_info and "total_tokens" in token_info:
                self.usage.extractor.add(token_info)
                
            try:
                import re
                if isinstance(result, list):
                    # In some library versions, JSON mode returns a list/dict directly or chunks
                    result = "".join(str(x) for x in result)
                elif not isinstance(result, str):
                    result = str(result)
                    
                match = re.search(r'\{.*\}', result, re.DOTALL)
                clean_json = match.group(0) if match else result
                data = json.loads(clean_json)
                
                # Fetch strict array instead of freeform string
                knowledge_array = data.get("facts", [])
                
                facts_extracted = len(knowledge_array) if isinstance(knowledge_array, list) else 0

                if isinstance(knowledge_array, list) and len(knowledge_array) > 0:
                    knowledge_str = "\n".join(str(k).strip() for k in knowledge_array if str(k).strip())
                    if knowledge_str:
                        self.memory.save(knowledge_str)
                
                if self._last_trace:
                    from datetime import datetime
                    from .trace import SessionCloseTrace
                    session_close_duration = time.time() - session_close_start
                    self._last_trace.session_close = SessionCloseTrace(
                        started_at=datetime.fromtimestamp(session_close_start),
                        duration_ms=int(session_close_duration * 1000),
                        model_used=self.light_llm,
                        combined=False,
                        summary_generated="",
                        facts_extracted=facts_extracted,
                        facts_written=facts_extracted,
                        facts_deduplicated=0,  # Could be added if memory impl returns details
                        tokens_input=token_info.get("input_tokens", 0) if token_info else 0,
                        tokens_output=token_info.get("output_tokens", 0) if token_info else 0
                    )
            except json.JSONDecodeError:
                console.error("MEMORY EXTRACTION", "Failed to parse JSON response", agent_id=self.agent_id)
                
        except Exception as e:
            console.error("MEMORY EXTRACTION", f"Extraction failed: {str(e)}", agent_id=self.agent_id)

    async def run_async(self, message: Union[str, List[Dict[str, str]]], max_history: int = 10):
        """Run a task with the agent (async version).
        
        Non-blocking version of `run()` — returns immediately with a coroutine.
        Useful for integration with async frameworks (FastAPI, etc).
        
        Args:
            message: Task description (string) or conversation history (list of message dicts).
            max_history: Max previous messages to include as context (default 10).
        
        Returns:
            Task result/output from the agent.
        
        Example::
        
            async def main():
                agent = Agent(tools=[Gmail()], llm="gemini-3.1-flash-lite-preview")
                await agent.run_async("Read my latest emails and summarize")
        """
        # Display task box FIRST before anything else
        if isinstance(message, str):
            console.print_task_box(message)
        elif isinstance(message, list):
            # For list of messages, concatenate them for display
            display_msg = "\n".join([m.get('content', str(m)) for m in message])
            console.print_task_box(display_msg)
        
        # Configure API keys once if not already done (after task box so task appears first)
        if not self._api_configured:
            configure_api_keys(providers=self._providers)
            self._api_configured = True
        
        # Auto-start agent if not already running (suppress startup message since task box already printed)
        if not self.running:
            self.start(suppress_startup_message=True)
        
        task_id = self._prepare_run_task()
        
        if self.chat is not None:
            if isinstance(message, list):
                for m in message:
                    self.chat.append(m.get('role', 'user'), m.get('content', str(m)))
            else:
                self.chat.append("user", message)
                
            # Launch compression as a background task so it doesn't block task execution
            asyncio.create_task(self._compress_chat_if_needed(task_id))
            
        task_content = ""
        if self.chat is not None:
            if self.chat.summary:
                task_content += f"Conversation Summary: {self.chat.summary}\n\n"
            
            recent = self.chat.messages[-max_history:]
            for m in recent:
                task_content += f"{m['role'].upper()}: {m['content']}\n"
        else:
            if isinstance(message, list):
                for m in message:
                    task_content += f"{m.get('role', 'user').upper()}: {m.get('content', str(m))}\n"
            else:
                task_content = message
            
        console.info("AGENT", f"Task payload generated ({len(task_content)} chars)", agent_id=self.agent_id, task_id=task_id)
        self.orchestrator.receive_message({"payload": task_content.strip(), "task_id": task_id})
        
        return task_id

    def run(self, message: Union[str, List[Dict[str, str]]], max_history: int = 10):
        """Execute a task with the agent (blocking version).
        
        Automatically starts the agent if not already running. Waits for the task
        to complete before returning.
        
        Args:
            message: Task description (string) or conversation history (list of message dicts with 'role' and 'content').
            max_history: Max previous messages to include as context (default 10).
        
        Returns:
            Task result/output from the agent.
        
        Example::
        
            agent = Agent(tools=[Gmail(), Drive()], llm="gemini-3.1-flash-lite-preview")
            result = agent.run("Forward today's reports to alice@acme.com")
            print(result)
        """
        # Display task box FIRST before anything else
        if isinstance(message, str):
            console.print_task_box(message)
        elif isinstance(message, list):
            # For list of messages, concatenate them for display
            display_msg = "\n".join([m.get('content', str(m)) for m in message])
            console.print_task_box(display_msg)
        
        # Configure API keys once if not already done (after task box so task appears first)
        if not self._api_configured:
            configure_api_keys(providers=self._providers)
            self._api_configured = True
        
        # Auto-start agent if not already running (suppress startup message since task box already printed)
        if not self.running:
            self.start(suppress_startup_message=True)
        
        task_id = self._prepare_run_task()
        
        if self.chat is not None:
            if isinstance(message, list):
                for m in message:
                    self.chat.append(m.get('role', 'user'), m.get('content', str(m)))
            else:
                self.chat.append("user", message)
                
            # Launch compression safely without blocking the Sync flow
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(self._compress_chat_if_needed(task_id))
            except RuntimeError:
                # If no running loop is found (which happens if run() is called outside an async context)
                # We spin up a targeted background thread to process the asyncio call non-blocking.
                import threading
                def run_in_thread():
                    asyncio.run(self._compress_chat_if_needed(task_id))
                threading.Thread(target=run_in_thread, daemon=True).start()
        
        task_content = ""
        if self.chat is not None:
            if self.chat.summary:
                task_content += f"Conversation Summary: {self.chat.summary}\n\n"
            
            recent = self.chat.messages[-max_history:]
            for m in recent:
                task_content += f"{m['role'].upper()}: {m['content']}\n"
        else:
            if isinstance(message, list):
                for m in message:
                    task_content += f"{m.get('role', 'user').upper()}: {m.get('content', str(m))}\n"
            else:
                task_content = message
            
        console.info("AGENT", f"Task payload generated ({len(task_content)} chars)", agent_id=self.agent_id, task_id=task_id)
        self.orchestrator.receive_message({"payload": task_content.strip(), "task_id": task_id})
        
        return task_id
        
    def info(self) -> dict:
        """Get comprehensive information about the agent's current state.
        
        Returns:
            dict with keys: agent_id, running, last_called, models, tools, chat_memory,
                   approval_count, and more.
        """
        # Basic agent information
        info = {
            "agent_id": self.agent_id,
            "running": self.running,
            "last_called": self.last_called.isoformat() if self.last_called else None,
            "last_activity": self.last_activity.isoformat(),
            "creation_time": self.created_at.isoformat(),
            "auto_stop": {
                "enabled": self.auto_stop_timeout is not None,
                "timeout_minutes": self.auto_stop_timeout / 60 if self.auto_stop_timeout else None,
                "time_until_stop": max(
                    0,
                    (self.last_activity + timedelta(seconds=self.auto_stop_timeout) - _utcnow()).total_seconds() / 60
                ) if self.running and self.auto_stop_timeout else 0
            },
            "models": {
                "llm": self.llm,
                "light_llm": self.light_llm,
                "heavy_llm": self.heavy_llm,
                "summarizer_llm": self._get_summarizer_llm()
            },
            "logging_enabled": self.logger is not None
        }
        
        # Tool information
        info["tools"] = {
            "available_tools": self.get_available_tools(),
            "tool_count": len(self.get_available_tools())
        }
        
        # Current tasks information
        if self.logger and hasattr(self.logger, 'active_tasks'):
            active_tasks = self.logger.active_tasks
            info["current_tasks"] = {
                "active_count": len(active_tasks),
                "tasks": []
            }
            
            for task_id, task_data in active_tasks.items():
                task_info = {
                    "task_id": task_id,
                    "message": task_data.get("message", "")[:100] + ("..." if len(task_data.get("message", "")) > 100 else ""),
                    "start_time": task_data.get("start_datetime", ""),
                    "status": task_data.get("status", "unknown"),
                    "tokens_used": task_data.get("tokens_used", 0),
                    "llm_calls": task_data.get("llm_calls", 0)
                }
                info["current_tasks"]["tasks"].append(task_info)
        else:
            info["current_tasks"] = {
                "active_count": 0,
                "tasks": [],
                "note": "Logging not enabled - cannot track active tasks"
            }
        
        # Queue information
        if hasattr(self.orchestrator, 'message_queue'):
            queue_size = self.orchestrator.message_queue.qsize()
            info["message_queue"] = {
                "pending_messages": queue_size,
                "queue_empty": queue_size == 0
            }
        

        
            
        return info
        
    def get_agent_id(self) -> str:
        """Get the agent ID"""
        return self.agent_id
        
    def get_available_tools(self) -> List[str]:
        """Get names of all tools currently available to this agent.
        
        Returns:
            List of tool names.
        """
        return list(self.orchestrator.tools.tools.keys())
    
    @staticmethod
    def get_all_internal_tools() -> List[str]:
        """Get list of all internal tools that can be used"""
        from .tools.internal_tools import internal_tools
        return list(internal_tools.keys())
    
    def get_log_stats(self) -> dict:
        """Get logging statistics"""
        if self.logger:
            return self.logger.get_log_stats()
        return {"logging": "disabled"}
    
    # ==================== HUMAN APPROVAL METHODS ====================
    
    def get_pending_approvals(self) -> list:
        """Get all pending human approval requests for this agent.
        
        Returns:
            List of approval request objects (or empty list if no pending requests).
        """
        if not self.enable_human_approval or not self.orchestrator.approval_manager:
            return []
        return self.orchestrator.approval_manager.get_pending_requests(agent_id=self.agent_id)
    
    def get_pending_approval_count(self) -> int:
        """Get count of pending human approval requests for this agent.
        
        Returns:
            Integer count of pending approvals.
        """
        if not self.enable_human_approval or not self.orchestrator.approval_manager:
            return 0
        return self.orchestrator.approval_manager.get_pending_count(agent_id=self.agent_id)
    
    def approve(self, request_id: str, response: str = "Approved") -> bool:
        """Approve a pending request
        
        Args:
            request_id: The approval request ID
            response: Optional approval message
            
        Returns:
            True if approved successfully, False otherwise
        """
        if not self.enable_human_approval or not self.orchestrator.approval_manager:
            console.warning("Approval failed", "Human approval not enabled for this agent", agent_id=self.agent_id)
            return False
        return self.orchestrator.approval_manager.approve(request_id, response)
    
    def reject(self, request_id: str, reason: str = "Rejected") -> bool:
        """Reject a pending request
        
        Args:
            request_id: The approval request ID
            reason: Optional rejection reason
            
        Returns:
            True if rejected successfully, False otherwise
        """
        if not self.enable_human_approval or not self.orchestrator.approval_manager:
            console.warning("Rejection failed", "Human approval not enabled for this agent", agent_id=self.agent_id)
            return False
        return self.orchestrator.approval_manager.reject(request_id, reason)
    
    def get_approval_info(self, request_id: str) -> Optional[dict]:
        """Get information about a specific approval request"""
        if not self.enable_human_approval or not self.orchestrator.approval_manager:
            return None
        return self.orchestrator.approval_manager.get_request(request_id)
    
    # ==============================================================
    
    def __str__(self) -> str:
        return f"Agent(id='{self.agent_id}', tools={len(self.tools)}, running={self.running})"
    
    def __repr__(self) -> str:
        return self.__str__()
