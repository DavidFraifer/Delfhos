from typing import List, Union, Optional, Dict, Any, Literal
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
    if isinstance(confirm_policy, bool):
        return confirm_policy
    if isinstance(confirm_policy, list):
        return len(confirm_policy) > 0
    if isinstance(confirm_policy, str):
        return confirm_policy.strip().lower() not in ("none", "false", "")
    return False


def _tools_have_confirm_policies(tools: Optional[List[Union[str, callable, Connection]]]) -> bool:
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
    SUPPORTED_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-flash-preview", "gemini-3.1-flash-lite-preview", "mercury-2"]
    INACTIVITY_TIMEOUT = 600  # 10 minutes in seconds
    
    def __init__(self, tools: List[Union[str, callable, Connection]], light_llm: str, heavy_llm: str, 
                 agent_id: Optional[str] = None, validation_mode: bool = False, auto_stop_timeout: Optional[int] = None, 
                 enable_human_approval: bool = False, on_confirm: Optional[callable] = None, confirm: Optional[Union[bool, List[str], str]] = None,
                 agent_context: Optional[str] = None, 
                 file_search_store_name: Optional[str] = None,
                 prefilter_model: Optional[str] = None,
                 code_generation_model: Optional[str] = None,
                 vision_model: Optional[str] = None,
                 search_model: Optional[str] = None,
                 chat: Optional[Chat] = None,
                 memory: Optional[Memory] = None,
                 trace: Union[Literal["full", "minimal"], bool] = "full"):
        configure_api_keys()

        approval_enabled = bool(
            enable_human_approval
            or on_confirm is not None
            or _has_confirm_policy(confirm)
            or _tools_have_confirm_policies(tools)
        )
        
        # Generate agent ID if not provided - use full UUID for consistency with database
        self.agent_id = agent_id or str(uuid.uuid4())
        self.enable_human_approval = approval_enabled
        self.on_confirm = on_confirm
        self.confirm_policy = confirm
        self.trace_mode = trace
        self.last_trace = None
        
        # Validation of provided models
        models_to_validate = [
            (light_llm, "light_llm"), 
            (heavy_llm, "heavy_llm"),
            (prefilter_model, "prefilter_model"),
            (code_generation_model, "code_generation_model"),
            (vision_model, "vision_model"),
            (search_model, "search_model")
        ]
        
        for model, name in models_to_validate:
            if model and model not in self.SUPPORTED_MODELS:
                raise_error("AGT-002", 
                           context={"model": model, "model_type": name, "supported": self.SUPPORTED_MODELS})
        
        self.tools = tools
        self.light_llm = light_llm
        self.heavy_llm = heavy_llm
        
        # Specific model configurations
        self.prefilter_model = prefilter_model or light_llm
        self.code_generation_model = code_generation_model or heavy_llm
        self.vision_model = vision_model or heavy_llm
        self.search_model = search_model or light_llm
        
        self.validation_mode = validation_mode  
        self.logger = CORTEXLogger() 
        self.usage = TokenUsage()
        
        self.orchestrator = Orchestrator(
            logger=self.logger, 
            light_llm=light_llm, 
            heavy_llm=heavy_llm, 
            agent_id=self.agent_id, 
            validation_mode=validation_mode, 
            enable_human_approval=approval_enabled, 
            on_confirm=on_confirm,
            confirm=confirm,
            agent_context=agent_context,
            prefilter_model=self.prefilter_model,
            code_generation_model=self.code_generation_model,
            vision_model=self.vision_model,
            search_model=self.search_model,
            token_usage=self.usage,
            memory=memory,
            trace_mode=self.trace_mode,
            trace_callback=self._update_trace
        )
        self.orchestrator.file_search_store_name = file_search_store_name
        self.running = False
        self.last_called = None  # Track when the agent was last used
        self.created_at = _utcnow()
        
        # Auto-stop functionality
        self.auto_stop_timeout = auto_stop_timeout or self.INACTIVITY_TIMEOUT
        self.last_activity = self.created_at
        self.inactivity_timer = None
        self.timer_lock = threading.Lock()
        
        self.chat = chat
        self.memory = memory

        # Wire chat so every completed task's output is captured as an assistant turn
        if self.chat:
            def _append_assistant_response(task_id: str, message: str):
                if message and message.strip() and message != "Task completed successfully":
                    self.chat.append("assistant", message)
            self.orchestrator.on_task_complete = _append_assistant_response

        self._configure_tools()
        self._warmup_clients()

    def _update_trace(self, trace: Trace):
        self.last_trace = trace
    
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
        if not self.tools:
            raise_error("AGT-003", context={"tools_provided": self.tools})
        
        self.orchestrator.tools.tools.clear()
        from .tools.internal_tools import internal_tools
        
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
                    "TL-001",
                    context={
                        "tool": str(tool),
                        "tool_type": type(tool).__name__,
                        "hint": "Decorate custom functions with @tool before passing to Agent(tools=[...]).",
                    },
                )
            else:
                report_error("TL-001", context={"tool": str(tool), "tool_type": type(tool).__name__})
    
    def add_tool(self, name: str, func):
        """Add a tool to the agent"""
        self.orchestrator.add_tool(name, func)
    
    def _reset_inactivity_timer(self):
        """Reset the inactivity timer when activity occurs"""
        with self.timer_lock:
            self.last_activity = _utcnow()
            
            # Cancel existing timer
            if self.inactivity_timer:
                if self.inactivity_timer.is_alive():
                    self.inactivity_timer.cancel()
                self.inactivity_timer = None
            
            # Start new timer only if agent is running
            if self.running:
                self.inactivity_timer = threading.Timer(self.auto_stop_timeout, self._auto_stop_due_to_inactivity)
                self.inactivity_timer.daemon = True
                self.inactivity_timer.start()
    
    def _auto_stop_due_to_inactivity(self):
        """Automatically stop the agent due to inactivity"""
        with self.timer_lock:
            # Double-check that agent is still running and we still want to auto-stop
            if self.running:
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
        
    def start(self):
        if not self.running:
            self.orchestrator.start()
            self.running = True
            available_tools = list(self.orchestrator.tools.tools.keys())
            console.system("Agent started", f"Available tools: {', '.join(available_tools)} | Auto-stop: {self.auto_stop_timeout/60:.1f}min", agent_id=self.agent_id)
            
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
                # Run the unified extraction and summarization on session close
                try:
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        asyncio.ensure_future(self._session_close_boundary(), loop=loop)
                    except RuntimeError:
                        asyncio.run(self._session_close_boundary())
                except Exception as e:
                    console.error("SESSION CLOSE", f"Failed to run boundary extraction: {str(e)}", agent_id=self.agent_id)
                
                # Clear chat explicitly at the end regardless of memory
                if self.chat:
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
            result, token_info = await llm_completion_async(
                prompt=prompt,
                model=self.light_llm,
                max_tokens=300,
                temperature=0.3
            )
            dur_comp = int((time.time() - start_comp) * 1000)
            
            if token_info and "total_tokens" in token_info:
                self.usage.summarizer.add(token_info)
                if self.logger and task_id:
                    self.logger.add_tokens(task_id, token_info, model=self.light_llm, function_name="mid_session_compress")
            
            if self.last_trace:
                from .trace import ChatCompressionTrace
                from datetime import datetime
                self.last_trace.chat_compression = ChatCompressionTrace(
                    triggered_at=datetime.fromtimestamp(start_comp),
                    model_used=self.light_llm,
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
        if not self.memory:
            return
            
        if not self.chat or (not self.chat.messages and not self.chat.summary):
            return
            
        from .internal.llm import llm_completion_async
        import json
        
        session_close_start = time.time()
        text_context = ""
        if self.chat and self.chat.summary:
            text_context += f"PREVIOUS SUMMARY: {self.chat.summary}\n\n"
        text_context += "RECENT MESSAGES:\n"
        if self.chat:
            for msg in self.chat.messages:
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
                
                if self.last_trace:
                    from datetime import datetime
                    from .trace import SessionCloseTrace
                    session_close_duration = time.time() - session_close_start
                    self.last_trace.session_close = SessionCloseTrace(
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
        """
        Run a task with the agent (Async version)
        """
        task_id = self._prepare_run_task()
        
        if self.chat:
            if isinstance(message, list):
                for m in message:
                    self.chat.append(m.get('role', 'user'), m.get('content', str(m)))
            else:
                self.chat.append("user", message)
                
            # Launch compression as a background task so it doesn't block task execution
            asyncio.create_task(self._compress_chat_if_needed(task_id))
            
        task_content = ""
        if self.chat:
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

    def run(self, message: Union[str, List[Dict[str, str]]], max_history: int = 10):
        """
        Run a task with the agent (Sync version)
        """
        task_id = self._prepare_run_task()
        
        if self.chat:
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
        if self.chat:
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
        
    def info(self) -> dict:
        """Get comprehensive information about the agent's current state"""
        # Basic agent information
        info = {
            "agent_id": self.agent_id,
            "running": self.running,
            "last_called": self.last_called.isoformat() if self.last_called else None,
            "last_activity": self.last_activity.isoformat(),
            "creation_time": self.created_at.isoformat(),
            "auto_stop": {
                "enabled": True,
                "timeout_minutes": self.auto_stop_timeout / 60,
                "time_until_stop": max(
                    0,
                    (self.last_activity + timedelta(seconds=self.auto_stop_timeout) - _utcnow()).total_seconds() / 60
                ) if self.running else 0
            },
            "models": {
                "light_llm": self.light_llm,
                "heavy_llm": self.heavy_llm
            },
            "validation_mode": self.validation_mode,
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
        """Get list of available tools"""
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
        """Get all pending approval requests for this agent"""
        if not self.enable_human_approval or not self.orchestrator.approval_manager:
            return []
        return self.orchestrator.approval_manager.get_pending_requests(agent_id=self.agent_id)
    
    def get_pending_approval_count(self) -> int:
        """Get count of pending approval requests for this agent"""
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
