"""
Orchestrator - Python-Based Agent Task Execution

Manages task analysis, Python code generation, and execution using tool libraries.
"""

from typing import Dict, Any, Optional, Union, List
from ..utils.logger import CORTEXLogger
from ..utils.console import console
from ..utils.llm_utils import normalize_llm_result
from ..tools.tool import ToolContainer
from ..tools.tool_registry import (
    build_prefilter_prompt,
    build_filtered_api_docs,
    get_available_actions_for_connections,
    parse_prefilter_response,
    filter_selected_actions,
    build_connection_context_for_prompt,
)
from ..memory.AgentMemory import AgentMemory
from delfhos.errors import ApprovalRejectedError
from ..internal.llm import llm_completion_async
from .python_executor import parse_python_code

from .approval_manager import ApprovalManager
from ..trace import Trace, MemoryRetrievalTrace, PrefilterTrace, CodeGenTrace, ExecutionTrace, ToolCallTrace
import asyncio, threading, queue, time, uuid
from datetime import datetime, timedelta, timezone


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




class Orchestrator:
    """
    Orchestrates agent task execution using Python code generation with auto-detection of relevant connections.
    
    Flow:
    1. Receive task message
    2. Pre-fetch SQL schema if SQL tool is selected/available
    3. Generate Python code using LLM
    4. Execute Python code with tool libraries
    5. Return results
    """
    
    MAX_WAIT_TIMES_ENTRIES = 100
    PREFILTER_MEMORY_MAX_CHARS = 1200
    PREFILTER_MEMORY_MAX_LINES = 20
    _VISIBLE_PHASES = {
        "memory_retrieval": "Retrieving memory",
        "prefilter": "Analyzing tools",
        "sql_schema": "Loading schema",
        "llm_code_generation": "Planning",
        "awaiting_approval": "Awaiting approval",
    }
    
    def __init__(self, light_llm: str, heavy_llm: str, logger: CORTEXLogger, agent_id: str = "unknown",
                 on_confirm=None,
                 approval_enabled: bool = False, system_prompt: Optional[str] = None,
                 prefilter_llm: Optional[str] = None, code_generation_llm: Optional[str] = None,
                 vision_llm: Optional[str] = None, token_usage=None,
                 memory=None, trace_mode: Union[str, bool] = "full", trace_callback=None, llm_config: Optional[str] = None,
                 verbose: str = "low", enable_prefilter: bool = False, retry_count: int = 1):
        approval_enabled = on_confirm is not None or approval_enabled

        # Core configuration
        self.trace_mode = trace_mode
        self.trace_callback = trace_callback
        self.current_trace = None
        self.logger = logger
        self.light_llm = light_llm
        self.heavy_llm = heavy_llm
        self.llm_config = llm_config  # Store LLM configuration string for display in summary
        self.verbose = verbose  # Store verbose logging mode ("low" or "high")
        self.enable_prefilter = enable_prefilter  # Whether to use prefilter for tool selection
        self.retry_count = retry_count
        
        # Specific model overrides
        self.prefilter_llm = prefilter_llm or self.light_llm
        self.code_generation_llm = code_generation_llm or self.heavy_llm
        self.vision_llm = vision_llm or self.heavy_llm
        
        self.agent_id = agent_id
        self.enable_human_approval = approval_enabled
        self.confirm_policy = None  # Per-tool; resolved from each connection's confirm list
        self.system_prompt = system_prompt  # Agent instruction injected in code-generation prompt
        # Backward compatibility for runtime namespace (`ctx`) expected by PythonExecutor.
        # Keep legacy shape as dict to avoid AttributeError and preserve old behavior.
        self.agent_context = {"system_prompt": system_prompt} if system_prompt else {}
        self.token_usage = token_usage
        self.memory = memory  # Long-term Memory with embedding retrieval
        
        # Initialize components
        self.tools = ToolContainer(logger=self.logger)
        self.tool_descriptions = {}
        
        # Add internal tools
        from ..tools.internal_tools import internal_tools
        for tool_name, tool_func in internal_tools.items():
            self.tools.add_tool(tool_name, tool_func)
        self.message_queue = queue.Queue()  # Kept for legacy compat (unused by scheduler)
        self._async_queue: asyncio.Queue = None  # Created inside the scheduler's event loop
        self._scheduler_loop: asyncio.AbstractEventLoop = None  # Ref to scheduler's event loop
        self._scheduler_ready = threading.Event()  # Fired once the loop + queue are ready
        self.scheduler_thread = None
        self.running = False
        self.agent_memory = AgentMemory(f"Orchestrator-Agent-{agent_id}", max_tasks=50)
        self.wait_times = {}
        self.task_results = {}
        self.task_tools_used = {}
        self.task_tool_timings = {}
        self.tool_timing_callback = None
        self.on_task_complete = None  # Optional callback(task_id, final_message) — used to capture assistant responses
        self.detected_language = 'en'  # Track task language for responses
        self._active_phase_logs = {}
        
        # SQL Schema Caching
        self._sql_schema_cache = None
        self._sql_schema_last_fetch = 0
        self.SQL_SCHEMA_CACHE_TTL = 600  # 10 minutes
        
        # Initialize approval manager if enabled
        self.approval_manager = ApprovalManager(on_confirm=on_confirm) if approval_enabled else None
        
    def _add_tokens(self, task_id: str, token_info: dict, model: str = None, function_name: str = None, duration: float = None):
        """Wrapper to track tokens for both the Agent's TokenUsage and the Logger."""
        if self.token_usage and token_info:
            self.token_usage.task.add(token_info)
        if self.logger:
            self.logger.add_tokens(task_id, token_info, model, function_name, duration)

    def _safe_add_tokens(self, task_id: str, token_info: dict, model: str = None, function_name: str = None, duration: float = None):
        """Best-effort token accounting helper used in non-critical paths."""
        try:
            self._add_tokens(task_id, token_info, model, function_name, duration=duration)
        except Exception:
            pass
        


    def _ui_text(self, key: str) -> str:
        """UI text for timeline steps (always English for consistency)."""
        texts = {
            "planning": "Planning",
            "retrying": "Retrying",
            "analyzing_connections": "Analyzing connections",
            "retrieving_knowledge": "Retrieving knowledge",
            "fetching_schema": "Fetching database schema"
        }
        return texts.get(key, key)

    def _normalize_connection_filter_response(self, response: str) -> str:
        response_clean = (response or "").strip().upper()
        return response_clean.replace("OUTPUT:", "").replace("CONNECTIONS:", "").replace("SELECTED:", "").strip()

    def _compact_prefilter_memory_context(self, memory_context: Optional[str]) -> str:
        """Trim memory context for prefilter to reduce token usage while preserving key facts."""
        if not memory_context or not isinstance(memory_context, str):
            return ""

        lines = [line.strip() for line in memory_context.splitlines() if line.strip()]
        if len(lines) > self.PREFILTER_MEMORY_MAX_LINES:
            lines = lines[:self.PREFILTER_MEMORY_MAX_LINES]

        compact = "\n".join(lines)
        if len(compact) > self.PREFILTER_MEMORY_MAX_CHARS:
            compact = compact[:self.PREFILTER_MEMORY_MAX_CHARS].rstrip() + "\n... [truncated]"

        return compact

    def _extract_selected_connection_indices(self, response_clean: str, total_connections: int) -> list:
        parts = [p.strip() for p in response_clean.split(',')]
        selected_indices = []
        for part in parts:
            digits = ''.join(c for c in part if c.isdigit())
            if digits:
                idx = int(digits)
                if 1 <= idx <= total_connections:
                    selected_indices.append(idx)
        return selected_indices

    def _parse_connection_filter_selection(self, response: str, connections: list, task_id: str = "") -> list:
        """Parse and validate connection-filter LLM output into selected connection objects."""
        response_clean = self._normalize_connection_filter_response(response)

        if response_clean == "NONE" or not response_clean:
            console.debug("Connection filtering: No relevant connections", "", task_id=task_id, agent_id=self.agent_id)
            return []

        try:
            selected_indices = self._extract_selected_connection_indices(response_clean, len(connections))
            if not selected_indices:
                console.warning(
                    "Connection filtering: No valid connection numbers found in response",
                    f"Response was: {response_clean}, using all connections",
                    task_id=task_id,
                    agent_id=self.agent_id,
                )
                return []

            selected_connections = [connections[i - 1] for i in selected_indices]
            selected_names = [c.connection_name if hasattr(c, 'connection_name') else "Connection" for c in selected_connections]
            console.debug(
                "Connection filtering completed",
                f"Selected {len(selected_connections)} connections: {', '.join(selected_names)}",
                task_id=task_id,
                agent_id=self.agent_id,
            )
            return selected_connections
        except Exception as parse_error:
            console.warning(
                "Failed to parse connection filtering response",
                f"Response: {response_clean}, Error: {parse_error}, using all connections",
                task_id=task_id,
                agent_id=self.agent_id,
            )
            return []

    def add_tool(self, name: str, func, description: str = None):
        self.tools.add_tool(name, func)
        if description: 
            self.tool_descriptions[name] = description
    
    def add_connection(self, connection, agent_id: str = None):
        """Add a connection to the orchestrator"""
        self.tools.add_connection(connection, agent_id=agent_id or self.agent_id)

    async def require_approval(self, task_id: str, message: str, context: str = "", ui_metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Request human approval for a potentially sensitive action.
        
        - Creates an approval request via ApprovalManager (if enabled)
        - Emits an 'awaiting_approval' timing entry so the UI shows the step
        - Waits (in a background thread) for the human decision
        
        Returns True if approved, False if rejected or if approval is not enabled.
        """
        if not self.approval_manager:
            # No approval manager configured – treat as implicitly approved
            return True
        
        start_time = time.time()
        
        # Create approval request (persists to DB via callback configured in tasks_supabase)
        request = await self.approval_manager.create_request_async(
            task_id=task_id,
            agent_id=self.agent_id,
            message=message,
            context=context or ""
        )
        
        # Emit timing entry so timeline shows "Awaiting approval"
        try:
            timing_metadata = {"approval_request_id": request.request_id}
            if ui_metadata and isinstance(ui_metadata, dict):
                # Merge caller-provided UI metadata (e.g. payload preview widgets)
                timing_metadata.update(ui_metadata)
            await self.track_tool_timing_async(
                task_id,
                "awaiting_approval",
                duration=None,
                model=None,
                description=message,
                is_starting=True,
                metadata=timing_metadata,
            )
        except Exception:
            # Timing is best-effort; approval flow must still work even if this fails
            pass
        
        # Block until human approves/rejects, but do it off the event loop
        loop = asyncio.get_running_loop()
        approved = await loop.run_in_executor(
            None, self.approval_manager.wait_for_approval, request.request_id
        )
        
        # Mark the approval step as completed in the timeline
        duration = time.time() - start_time
        # Track human-wait time so compute metrics can exclude non-compute idle time.
        self.wait_times[task_id] = self.wait_times.get(task_id, 0.0) + max(duration, 0.0)
        try:
            end_metadata = {"approval_request_id": request.request_id, "approved": bool(approved)}
            if ui_metadata and isinstance(ui_metadata, dict):
                end_metadata.update(ui_metadata)
            await self.track_tool_timing_async(
                task_id,
                "awaiting_approval",
                duration=duration,
                model=None,
                description=message,
                is_starting=False,
                metadata=end_metadata,
            )
        except Exception:
            pass
        
        # Raise error if approval was rejected
        if not approved:
            raise ApprovalRejectedError(operation=message)
        
        return approved

    def set_logger(self, logger):
        self.logger = logger
    
    def start(self):
        if not self.running:
            self.running = True
            self._scheduler_ready.clear()
            self.scheduler_thread = threading.Thread(target=self._scheduler_worker, daemon=True)
            self.scheduler_thread.start()
            # Wait until the asyncio loop + queue are initialized (fast, typically <1ms)
            self._scheduler_ready.wait(timeout=2.0)
    
    def stop(self):
        self.running = False
        if self.scheduler_thread: 
            self.scheduler_thread.join()
    
    def track_tool_usage(self, task_id: str, tool_name: str, model: str = None):
        """Track which tools are used for each task"""
        if not tool_name:
            return
        entry = {"tool": tool_name, "model": model}
        if task_id not in self.task_tools_used:
            self.task_tools_used[task_id] = []
        task_entries = self.task_tools_used[task_id]
        for existing in task_entries:
            if (isinstance(existing, dict) and 
                existing.get("tool") == entry["tool"] and 
                existing.get("model") == entry["model"]):
                return
        task_entries.append(entry)
    
    async def track_tool_timing_async(self, task_id: str, tool_name: str, duration: float, model: str = None, description: str = None, is_starting: bool = False, metadata: Optional[Dict[str, Any]] = None, wait_time: float = 0.0):
        """Async version of track_tool_timing that properly awaits the callback"""
        timing_entry = self._track_tool_timing_internal(task_id, tool_name, duration, model, description, is_starting, metadata, wait_time=wait_time)
        
        # Properly await the callback if set
        if timing_entry and self.tool_timing_callback:
            try:
                import inspect
                if inspect.iscoroutinefunction(self.tool_timing_callback):
                    await self.tool_timing_callback(task_id, timing_entry)
                else:
                    self.tool_timing_callback(task_id, timing_entry)
            except Exception as e:
                print(f"[TRACK_TIMING_ASYNC] Callback error: {e}")
    
    def _track_tool_timing_internal(self, task_id: str, tool_name: str, duration: float, model: str = None, description: str = None, is_starting: bool = False, metadata: Optional[Dict[str, Any]] = None, wait_time: float = 0.0):
        """Internal method that handles timing entry creation/update. Returns the timing entry if callback should be triggered."""
        if task_id not in self.task_tool_timings:
            self.task_tool_timings[task_id] = []
        
        current_time = time.time()
        existing_entries = self.task_tool_timings[task_id]
        
        # Normalize description for comparison (strip whitespace, lowercase)
        normalized_desc = (description or "").strip().lower()
        
        # If this is a completion (duration is not None), try to find and update the starting entry
        if not is_starting and duration is not None:
            # Look for an existing entry with same tool, same description, and no duration (ongoing)
            for existing in reversed(existing_entries[-20:]):  # Check last 20 entries
                if isinstance(existing, dict):
                    existing_tool = existing.get('tool')
                    existing_duration = existing.get('duration')
                    existing_desc = (existing.get('description') or "").strip().lower()
                    
                    # Match: same tool, same description, and no duration (ongoing step)
                    if (existing_tool == tool_name and
                        existing_desc == normalized_desc and
                        (existing_duration is None or existing_duration == 0)):
                        # Found the starting entry - update it with duration
                        existing['duration'] = duration
                        existing['status'] = 'success'
                        if model:
                            existing['model'] = model
                        # Update metadata if provided (e.g., sheet_link, drive_link)
                        if metadata:
                            existing['ui_metadata'] = metadata
                            
                        if wait_time > 0.0:
                            existing['wait_time'] = wait_time
                        self._emit_phase_progress(task_id, tool_name, description, is_starting=False, duration=duration, metadata=existing.get('ui_metadata'), model=model)
                        return existing  # Return updated entry for callback
        
        # If this is a starting entry or no matching ongoing entry found, create new entry                                                                      
        if is_starting or duration is None:
            # Starting entry - no duration
            timing_entry = {
                'tool': tool_name,
                'duration': None,  # None indicates ongoing
                'timestamp': current_time,
                'status': 'running'  # Status indicates it's running
            }
            if description:
                timing_entry['description'] = description
            if model:
                timing_entry['model'] = model
            if metadata:
                timing_entry['ui_metadata'] = metadata
            self.task_tool_timings[task_id].append(timing_entry)
            self._emit_phase_progress(task_id, tool_name, description, is_starting=True, duration=None, metadata=metadata, model=model)
            return timing_entry  # Return new entry for callback
        else:
            # Completion entry but no matching starting entry found - create new entry
            # Check for recent duplicate entries (within 1 second) to avoid duplicates
            for existing in reversed(existing_entries[-10:]):  # Check last 10 entries
                if isinstance(existing, dict):
                    existing_tool = existing.get('tool')
                    existing_timestamp = existing.get('timestamp', 0)
                    existing_duration = existing.get('duration', 0)
                    existing_desc = (existing.get('description') or "").strip().lower()
                    
                    # More strict matching: same tool, same description, within 1s, and similar duration (within 15%)
                    if (existing_tool == tool_name and 
                        existing_desc == normalized_desc and
                        abs(existing_timestamp - current_time) < 1.0 and
                        existing_duration is not None and
                        abs(existing_duration - duration) < max(duration * 0.15, 0.15)):
                        # This is a duplicate - update existing entry
                        if abs(existing_duration - duration) > 0.1:
                            existing['duration'] = duration
                        if model and not existing.get('model'):
                            existing['model'] = model
                        return None  # Don't trigger callback for duplicates
            
            # No duplicate found, create new entry
            timing_entry = {
                'tool': tool_name,
                'duration': duration,
                'timestamp': current_time,
                'model': model,
                'status': 'success'
            }
            if description:
                timing_entry['description'] = description
            if metadata:
                timing_entry['ui_metadata'] = metadata
            if wait_time > 0.0:
                timing_entry['wait_time'] = wait_time
            self.task_tool_timings[task_id].append(timing_entry)
            self._emit_phase_progress(task_id, tool_name, description, is_starting=False, duration=duration, metadata=metadata, model=model)
            return timing_entry  # Return new entry for callback

    def _emit_phase_progress(self, task_id: str, tool_name: str, description: Optional[str], is_starting: bool, duration: Optional[float], metadata: Optional[Dict[str, Any]] = None, model: Optional[str] = None):
        """Emit uniform, user-facing log line for every tool call except code generation."""
        # Code generation is tracked separately (Planning spinner + its own timing)
        if tool_name == "llm_code_generation":
            loading_key = f"{task_id}:llm_code_generation"
            if is_starting:
                if loading_key not in self._active_phase_logs:
                    self._active_phase_logs[loading_key] = True
                    console.loading_start("[white]Planning[/white]  [bright_yellow]llm[/bright_yellow] [grey50]...[/grey50]", loading_key)
            else:
                self._active_phase_logs.pop(loading_key, None)
                console.loading_stop(loading_key)
                if duration is not None:
                    console.tool("[white]Planning[/white]  [bright_yellow]llm[/bright_yellow]", None, task_id=task_id)
            return

        is_internal = tool_name in self._VISIBLE_PHASES
        label = description or self._VISIBLE_PHASES.get(tool_name, tool_name)

        # External tools without a description add no value — skip
        if not is_internal and not description:
            return

        tool_color = "bright_yellow" if not is_internal else "magenta"
        formatted_label = f"[white]{label}[/white]  [{tool_color}]{tool_name}[/{tool_color}]"

        # Internal phases are singleton per task; external tools key by description too (parallel-safe)
        if is_internal:
            key = (task_id, tool_name)
            loading_key = f"{task_id}:{tool_name}"
            spinner_label = formatted_label
        else:
            desc_norm = (label or "").strip().lower()
            key = (task_id, tool_name, desc_norm)
            loading_key = f"{task_id}:{tool_name}:{desc_norm}"
            spinner_label = formatted_label

        if is_starting:
            if key in self._active_phase_logs:
                return
            self._active_phase_logs[key] = True
            
            # Add a subtle, engaging suffix only while it's actively running
            running_label = f"{spinner_label} [grey50]...[/grey50]"
            console.loading_start(running_label, loading_key)
            return

        # ── Completion ──────────────────────────────────────────────────────
        self._active_phase_logs.pop(key, None)
        console.loading_stop(loading_key)

        if duration is None:
            return

        # Extract params from metadata
        args   = dict((metadata or {}).get("_tool_trace_args") or {})
        action = (metadata or {}).get("_tool_action") or ""
        
        if model and "model" not in args:
            args["model"] = model

        param_parts = []
        if action and not is_internal:
            param_parts.append(f"action={action}")

        noisy_keys = {
            "prompt", "desc", "ui_metadata", "metadata", "content", "body", "html", "text"
        }
        preferred_keys = (
            "query", "max_results", "model", "max_tokens", "temperature",
            "sql", "range", "sheet_name", "spreadsheet_id", "to", "subject"
        )

        compact_items = []
        for k in preferred_keys:
            if k in args and k not in noisy_keys:
                compact_items.append((k, args[k]))
        for k, v in args.items():
            if k in noisy_keys or any(k == x for x, _ in compact_items):
                continue
            compact_items.append((k, v))

        for k, v in compact_items[:2]:
            v_str = str(v).replace("\n", " ").strip()
            if len(v_str) > 42:
                v_str = v_str[:39] + "…"
            param_parts.append(f"{k}={v_str}")
        params_str = "  ".join(param_parts)

        # Uniform message: description first (white), then a colored tool tag.
        # Duration is omitted — the elapsed timestamp shown before the icon (verbose mode) is sufficient
        tool_color = "bright_yellow" if not is_internal else "magenta"
        msg = f"[white]{label}[/white]  [{tool_color}]{tool_name}[/{tool_color}]"
        console.tool(msg, params_str or None, task_id=task_id)
    
    def track_tool_timing(self, task_id: str, tool_name: str, duration: float, model: str = None, description: str = None, is_starting: bool = False):
        """Track tool execution timing for each task (sync version - uses asyncio.create_task for callback)
        
        Args:
            task_id: Task ID
            tool_name: Name of the tool
            duration: Duration in seconds (None for ongoing steps)
            model: Optional model name
            description: Optional description
            is_starting: If True, this is a starting entry (duration should be None)
        """
        timing_entry = self._track_tool_timing_internal(task_id, tool_name, duration, model, description, is_starting)
        
        # Trigger callback if we have an entry to report
        if timing_entry and self.tool_timing_callback:
                try:
                    import inspect
                    if inspect.iscoroutinefunction(self.tool_timing_callback):
                        asyncio.create_task(self.tool_timing_callback(task_id, timing_entry))
                    else:
                        self.tool_timing_callback(task_id, timing_entry)
                except Exception as e:
                    print(f"[TRACK_TIMING] Callback error: {e}")
    
    def get_tools_used(self, task_id: str) -> list:
        """Get the list of tools used for a specific task"""
        tools = self.task_tools_used.get(task_id, [])
        return [entry.copy() if isinstance(entry, dict) else entry for entry in tools]
    
    def get_tool_timings(self, task_id: str) -> list:
        """Get the tool execution timings for a specific task"""
        return self.task_tool_timings.get(task_id, [])
    
    def receive_message(self, message):
        if self.running and self._scheduler_loop and self._async_queue:
            # Thread-safe enqueue into the scheduler's asyncio event loop
            self._scheduler_loop.call_soon_threadsafe(self._async_queue.put_nowait, message)
        elif self.running:
            # Race: scheduler not fully ready yet — wait briefly then retry
            if self._scheduler_ready.wait(timeout=1.0) and self._scheduler_loop and self._async_queue:
                self._scheduler_loop.call_soon_threadsafe(self._async_queue.put_nowait, message)
        return self.running
    
    def _cleanup_wait_times_if_needed(self):
        """Cleanup old wait_times entries if limit exceeded"""
        if len(self.wait_times) > self.MAX_WAIT_TIMES_ENTRIES:
            keep_count = self.MAX_WAIT_TIMES_ENTRIES // 2
            sorted_tasks = sorted(self.wait_times.keys())
            tasks_to_remove = sorted_tasks[:-keep_count] if len(sorted_tasks) > keep_count else []
            for task_id in tasks_to_remove:
                self.wait_times.pop(task_id, None)
    
    def _scheduler_worker(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._scheduler_loop = loop
        self._async_queue = asyncio.Queue()
        self._scheduler_ready.set()  # Signal that the loop + queue are ready
        running_tasks = set()

        async def scheduler_loop():
            nonlocal running_tasks
            while self.running:
                # Drain any pre-enqueued messages (race-condition safety)
                while not self._async_queue.empty():
                    try:
                        message = self._async_queue.get_nowait()
                        task = asyncio.create_task(self._process_message_async(message))
                        running_tasks.add(task)
                        running_tasks -= {t for t in running_tasks if t.done()}
                    except asyncio.QueueEmpty:
                        break

                # Yield control so running tasks can make progress, then wait for next message
                try:
                    # Wait for the next message — yields immediately to event loop
                    message = await asyncio.wait_for(self._async_queue.get(), timeout=0.2)
                    task = asyncio.create_task(self._process_message_async(message))
                    running_tasks.add(task)
                    running_tasks -= {t for t in running_tasks if t.done()}
                except asyncio.TimeoutError:
                    # Timeout is just a heartbeat to re-check self.running
                    pass

        try:
            loop.run_until_complete(scheduler_loop())
            if running_tasks:
                loop.run_until_complete(asyncio.gather(*running_tasks, return_exceptions=True))
        except Exception:
            pass
        finally:
            self._scheduler_loop = None
            self._async_queue = None
            loop.close()
    
    async def _process_message_async(self, message):
        """Process a task message through the Python execution pipeline"""
        start_time = time.time()
        
        # Detect messages with pre-generated task_id
        payload = message
        task_id = None
        
        if isinstance(message, dict):
            if 'task_id' in message and 'payload' in message:
                # Message wrapped with task_id from Agent.run_async()
                task_id = message['task_id']
                payload = message['payload']
        
        # Fallback: Generate new task_id if not provided
        if not task_id:
            task_id = str(uuid.uuid4())

        # Initialize tracking
        self.wait_times[task_id] = 0.0
        display_message = payload[:60] + "..." if isinstance(payload, str) and len(payload) > 60 else payload
        self.logger.start_task(task_id, message, self.agent_id)

        # Initialize Trace
        if self.trace_mode:
            from datetime import datetime
            self.current_trace = Trace(
                session_id=task_id,
                task=payload if isinstance(payload, str) else str(payload),
                started_at=datetime.now(),
                trace_mode=self.trace_mode if isinstance(self.trace_mode, str) else "full"
            )
            self.current_trace.add_event("session_start", "task received")
            if self.trace_callback:
                self.trace_callback(self.current_trace)

        try:
            # SQL schema is now fetched inside llm_generate_python ONLY if prefilter selects SQL actions
            # This saves tokens and time when SQL is not needed for the task
            sql_schema = None

            # NOTE: Connection filtering is now handled by the prefilter inside llm_generate_python
            # This saves ~460 tokens by eliminating a redundant LLM call
            relevant_connections = None  # Pass all connections, prefilter will select needed tools

            # ─── Memory retrieval (embedding-based) ──────────────────────────
            # Runs BEFORE prefilter so context is available to both prefilter
            # and code generation. Local embeddings, no LLM call needed.
            memory_context = None
            if self.memory:
                console.info("Step", "Retrieving memories...", task_id=task_id, agent_id=self.agent_id)
                mem_start = time.time()
                from datetime import datetime
                mem_start_dt = datetime.now()
                if self.current_trace:
                    self.current_trace.add_event("memory_start", "retrieving memory")

                await self.track_tool_timing_async(task_id, "memory_retrieval", None, None, description="Retrieving memory", is_starting=True)
                try:
                    memory_context = self.memory.retrieve(payload)
                    mem_duration = time.time() - mem_start
                    facts_n = len(memory_context.splitlines()) if memory_context else 0

                    if self.current_trace:
                        self.current_trace.memory_retrieval = MemoryRetrievalTrace(
                            started_at=mem_start_dt,
                            duration_ms=int(mem_duration * 1000),
                            query=payload if isinstance(payload, str) else str(payload),
                            facts_retrieved=facts_n,
                            context_injected=memory_context if (memory_context and self.trace_mode == "full") else "",
                            embedding_backend="local"
                        )
                        self.current_trace.add_event("memory_complete", f"{facts_n} facts retrieved")

                    await self.track_tool_timing_async(task_id, "memory_retrieval", mem_duration, None, description="Retrieving memory", is_starting=False)
                    console.debug("Memory retrieval",
                                 f"Retrieved {facts_n} relevant facts ({mem_duration*1000:.0f}ms)",
                                 task_id=task_id, agent_id=self.agent_id)
                except Exception as mem_err:
                    mem_duration = time.time() - mem_start
                    await self.track_tool_timing_async(task_id, "memory_retrieval", mem_duration, None, description="Retrieving memory", is_starting=False)
                    console.warning("Memory retrieval failed",
                                f"{type(mem_err).__name__}: {mem_err}",
                                task_id=task_id, agent_id=self.agent_id)
            
            # Generate Python code
            code_gen_start = time.time()
            try:
                python_code = await self.llm_generate_python(payload, task_id=task_id, sql_schema=sql_schema, relevant_connections=relevant_connections, memory_context=memory_context)
            except Exception as code_gen_error:
                console.error("Python code generation failed with exception", 
                             f"{type(code_gen_error).__name__}: {str(code_gen_error)}", 
                             task_id=task_id, agent_id=self.agent_id)
                raise  # Re-raise to be caught by outer exception handler
            code_gen_time = time.time() - code_gen_start

            if not python_code or not python_code.strip():
                # No code generated - direct answer or error
                console.error("No Python code generated", "LLM did not produce executable code. Task may require tools that are not available or the request was unclear.",
                            task_id=task_id, agent_id=self.agent_id)
                result = {
                    "success": False,
                    "result": "Unable to generate code for this task. Please ensure all required tools (gmail, files, sheets, llm) are configured and try again.",
                    "error": "No executable Python code was generated. The task may require specific tools that need to be configured.",
                    "execution_time": 0
                }
            else:
                # Execute Python code
                console.debug("Executing Python code", f"Code generation time: {code_gen_time:.2f}s",
                            task_id=task_id, agent_id=self.agent_id)
                
                # Show generated code in verbose mode
                if self.verbose == "high":
                    from rich.panel import Panel
                    from rich.syntax import Syntax
                    code_syntax = Syntax(python_code, "python", theme="github-dark", line_numbers=True)
                    code_panel = Panel(code_syntax, title="[bold]Generated Code[/bold]", border_style="dim", expand=False)
                    console.console.print(code_panel)
                    console.console.print()  # Blank line
                
                from .python_executor import PythonExecutor
                executor = PythonExecutor(
                    self.tools,
                    task_id,
                    self.agent_id,
                    self.light_llm,
                    self.heavy_llm,
                    orchestrator=self,
                    vision_model=self.vision_llm
                )
                
                if self.current_trace:
                    self.current_trace.add_event("exec_start", "sandbox ready")

                exec_start = time.time()
                result = await executor.execute(python_code)
                exec_duration = time.time() - exec_start

                if self.current_trace:
                    from datetime import datetime
                    ex_start_dt = datetime.fromtimestamp(exec_start)
                    self.current_trace.execution = ExecutionTrace(
                        started_at=ex_start_dt,
                        duration_ms=int(exec_duration * 1000),
                        code_executed=python_code,
                        stdout=result.get("output", ""),
                        outcome="success" if result.get("success") else "error",
                        error_type=None,
                        error_message=result.get("error", None),
                        retry_reason=None
                    )
                    self.current_trace.add_event("exec_complete", "success" if result.get("success") else "error")
                
                # Auto-retry on execution failure: re-generate code with error context
                for retry_attempt in range(self.retry_count):
                    if result.get("success") or not result.get("error"):
                        break
                    error_msg = result["error"]
                    # Retry on code bugs and disallowed action attempts.
                    retryable_errors = ("TypeError", "KeyError", "NameError", "AttributeError", "IndexError", "ValueError", "RuntimeError", "SyntaxError")
                    disallowed_action_error = ("ERR-TOL-007" in error_msg) or ("Action not allowed" in error_msg)
                    should_retry = disallowed_action_error or any(err in error_msg for err in retryable_errors)
                    if should_retry:
                        warning_prefix = ""
                        if disallowed_action_error:
                            warning_prefix = (
                                "WARNING: Generated code attempted a disallowed action. "
                                "Execution was blocked; regenerating with stricter permission constraints."
                            )
                            console.warning(
                                "Blocked disallowed action",
                                warning_prefix,
                                task_id=task_id,
                                agent_id=self.agent_id,
                            )

                        console.debug("Auto-retry", f"Retrying after error: {error_msg[:200]}", 
                                    task_id=task_id, agent_id=self.agent_id)
                        await self.track_tool_timing_async(task_id, "llm_code_generation", None, self.code_generation_llm, description=self._ui_text("retrying"), is_starting=True)
                        
                        # Build rich context for retry
                        partial_output = result.get("output", "").strip()
                        
                        # Summarize completed tool steps from timings
                        completed_steps = []
                        tool_entries = self.task_tool_timings.get(task_id, [])
                        for entry in tool_entries:
                            if entry.get("duration") is not None and entry.get("tool") not in ("llm_code_generation", "prefilter", "sql_schema"):
                                desc = entry.get("description", entry.get("tool", "unknown"))
                                completed_steps.append(f"  - {desc} ({entry.get('duration', 0):.1f}s)")
                        
                        completed_section = ""
                        if completed_steps:
                            completed_section = "\n\nSTEPS ALREADY COMPLETED SUCCESSFULLY (do NOT repeat these):\n" + "\n".join(completed_steps)
                        
                        output_section = ""
                        if partial_output:
                            output_section = f"\n\nPARTIAL OUTPUT (already printed to user):\n{partial_output[:500]}"
                        
                        retry_instructions = (
                            "INSTRUCTIONS: Fix the error and generate ONLY the code needed to complete the remaining work. "
                            "CRITICAL: If the error occurred inside a loop, you MUST rewrite and execute the ENTIRE loop from scratch "
                            "(using the preserved data like fetched lists/results). Do NOT try to resume a loop from the middle. "
                            "Steps already completed BEFORE the failure (sheets created, files uploaded, queries executed, etc.) "
                            "should NOT be repeated — use their results if needed. Output Python code ONLY."
                        )
                        if disallowed_action_error:
                            retry_instructions = (
                                "INSTRUCTIONS: The previous attempt called at least one DISALLOWED action and was blocked. "
                                "Regenerate code that uses only permitted actions from the tool APIs shown in prompt context. "
                                "Never call blocked actions again. If a required action is not permitted, print a clear message "
                                "requesting permission change instead of attempting it. Output Python code ONLY."
                            )

                        retry_prompt = f"""TASK: "{payload}"

PREVIOUS CODE THAT FAILED:
```python
{python_code}
```

ERROR:
{error_msg}
{completed_section}{output_section}

CRITICAL STATE PRESERVATION: All variables defined in the PREVIOUS CODE before it crashed are ALREADY preserved in memory. You CAN and MUST use them directly. Do NOT query the database again or recreate variables.

{retry_instructions}"""
                        
                        try:
                            retry_llm_start = time.time()
                            retry_llm_result = await llm_completion_async(
                                model=self.code_generation_llm,
                                prompt=retry_prompt,
                                temperature=0.0,
                                max_tokens=4000,
                                response_format=None
                            )
                            retry_llm_duration = time.time() - retry_llm_start
                            await self.track_tool_timing_async(task_id, "llm_code_generation", retry_llm_duration, self.code_generation_llm, description=self._ui_text("retrying"), is_starting=False)
                            self.track_tool_usage(task_id, "llm_code_generation", self.code_generation_llm)
                            
                            retry_response, retry_token_info = normalize_llm_result(retry_llm_result)
                            self._safe_add_tokens(task_id, retry_token_info, self.code_generation_llm, "llm_retry", duration=retry_llm_duration)
                            
                            retry_code = parse_python_code(retry_response)
                            if retry_code and retry_code.strip():
                                console.debug("Executing retry code", f"{len(retry_code)} chars",
                                            task_id=task_id, agent_id=self.agent_id)
                                
                                if self.current_trace:
                                    self.current_trace.code_generation.attempt += 1
                                    self.current_trace.code_generation.tokens_input += retry_token_info.get("input_tokens", 0)
                                    self.current_trace.code_generation.tokens_output += retry_token_info.get("output_tokens", 0)
                                    self.current_trace.execution.retry_reason = next((err for err in retryable_errors if err in error_msg), "Unknown")
                                    self.current_trace.execution.code_executed += "\n# --- RETRY ---\n" + retry_code

                                retry_exec_start = time.time()
                                retry_result = await executor.execute(retry_code)
                                retry_exec_duration = time.time() - retry_exec_start

                                if self.current_trace:
                                    self.current_trace.execution.duration_ms += int(retry_exec_duration * 1000)
                                    self.current_trace.execution.stdout += "\n" + retry_result.get("output", "")
                                    self.current_trace.execution.outcome = "success" if retry_result.get("success") else "error"
                                    self.current_trace.execution.error_message = retry_result.get("error", None)
                                
                                original_output = result.get("output", "")
                                new_output = retry_result.get("output", "")

                                if original_output.strip() and new_output.strip():
                                    combined_output = original_output.rstrip() + "\n\n--- Auto-Retry Executed ---\n" + new_output.lstrip()
                                elif new_output.strip():
                                    combined_output = "--- Auto-Retry Executed ---\n" + new_output.lstrip()
                                else:
                                    combined_output = original_output

                                if warning_prefix:
                                    warning_banner = f"WARNING: {warning_prefix}\n\n"
                                    combined_output = warning_banner + (combined_output or "")
                                
                                result = retry_result
                                result["output"] = combined_output
                                result["execution_time"] += result.get("execution_time", 0)  # Combine time
                        except Exception as retry_error:
                            console.error("Auto-retry failed", f"{retry_error}",
                                        task_id=task_id, agent_id=self.agent_id)
                            # Append the retry error to the output so the user knows what happened
                            result["error"] += f"\n\nRetry failed: {str(retry_error)}"
            
            # Calculate timing and get token info
            task_duration = time.time() - start_time
            total_wait_time = self.wait_times.get(task_id, 0.0)

            # Compute time = full wall-clock duration minus explicit waiting time
            # (e.g., awaiting human approval). Keep in valid bounds.
            computational_time = max(task_duration - total_wait_time, 0.0)
            computational_time = min(computational_time, task_duration)
            
            # Get token/cost info from logger
            task_data = self.logger.active_tasks.get(task_id, {})
            token_info = {
                'tokens_used': task_data.get('tokens_used', 0), 
                'input_tokens': task_data.get('input_tokens', 0),
                'output_tokens': task_data.get('output_tokens', 0), 
                'llm_calls': task_data.get('llm_calls', 0),
                'total_cost_usd': round(task_data.get('total_cost_usd'), 8) if task_data.get('total_cost_usd') is not None else None,
                'pricing_path': task_data.get('pricing_path'),
            }
            
            # Print LLM call summary
            llm_breakdown = task_data.get('llm_breakdown', [])
            if llm_breakdown:
                summary_lines = ["LLM Call Summary:"]
                for i, call in enumerate(llm_breakdown, 1):
                    model = call.get('model', 'unknown')
                    input_tokens = call.get('input_tokens', 0)
                    output_tokens = call.get('output_tokens', 0)
                    call_cost_usd = call.get('cost_usd')
                    function_name = call.get('function_name', 'unknown')
                    duration = call.get('duration')
                    dur_str = f" in {duration:.2f}s" if duration is not None else ""
                    cost_str = f"${call_cost_usd:.6f}" if call_cost_usd is not None else "None"
                    summary_lines.append(f"  {i}. {function_name} ({model}){dur_str}: {input_tokens} in, {output_tokens} out | {cost_str}")
                total_duration = sum(call.get('duration') or 0.0 for call in llm_breakdown)
                total_dur_str = f" in {total_duration:.2f}s" if total_duration > 0 else ""
                tot_cost_str = f"${token_info['total_cost_usd']:.6f}" if token_info['total_cost_usd'] is not None else "None"
                summary_lines.append(f"Total: {token_info['llm_calls']} calls{total_dur_str}, {token_info['input_tokens']} in, {token_info['output_tokens']} out, {tot_cost_str}")
                console.debug("LLM Calls Summary", "\n".join(summary_lines),
                            task_id=task_id, agent_id=self.agent_id)
            
                
                if self.current_trace and self.current_trace.execution:
                    exec_calls = [c for c in llm_breakdown if c.get("function_name") not in ("prefilter", "llm_code_generation", "llm_connection_filtering", "llm_rag_retrieval")]
                    self.current_trace.execution.tokens_input = sum(c.get("input_tokens", 0) for c in exec_calls)
                    self.current_trace.execution.tokens_output = sum(c.get("output_tokens", 0) for c in exec_calls)
                
            # Print Tool Timings Summary
            tool_entries = self.task_tool_timings.get(task_id, [])
            completed_tools = []
            if tool_entries:
                timing_lines = ["Task Phases Timing Summary:"]
                completed_tools = [e for e in tool_entries if e.get("duration") is not None]
                for i, entry in enumerate(completed_tools, 1):
                    tool_n = entry.get('tool', 'unknown')
                    desc = entry.get('description', '')
                    dur = entry.get('duration', 0.0)
                    desc_str = f" - {desc}" if desc else ""
                    is_waiting_phase = isinstance(tool_n, str) and (
                        tool_n == "awaiting_approval" or tool_n.startswith("awaiting_")
                    )
                    perc_base = task_duration if is_waiting_phase else computational_time
                    perc = (dur / perc_base * 100) if perc_base > 0 else 0
                    timing_lines.append(f"  {i}. {tool_n}{desc_str}: {dur:.2f}s ({perc:.1f}%)")
                    
                    if self.current_trace and tool_n not in ("llm_code_generation", "prefilter", "memory_retrieval") and not tool_n.startswith("llm_"):
                        meta = entry.get("ui_metadata") or {}
                        args = meta.get("_tool_trace_args", {})
                        action = meta.get("_tool_action", "")
                        from datetime import timedelta
                        start_time_dt = datetime.fromtimestamp(entry.get("timestamp", time.time()))
                        dur_ms = int(dur * 1000)
                        
                        tc = ToolCallTrace(
                            tool_name=f"{tool_n}.{action}" if action else tool_n,
                            arguments=args,
                            started_at=start_time_dt,
                            duration_ms=dur_ms,
                            outcome="success" if entry.get("status") == "success" else "error",
                            result=meta.get("_tool_trace_result", ""),
                            error=meta.get("_tool_trace_error", None)
                        )
                        self.current_trace.tool_calls.append(tc)
                        
                        # Add timeline events
                        arg_strs = []
                        for k, v in (args or {}).items():
                            val_str = repr(v) if isinstance(v, str) else str(v)
                            arg_strs.append(f"{k}={val_str}")
                        arg_summary = ", ".join(arg_strs)
                        if len(arg_summary) > 25: arg_summary = arg_summary[:22] + "..."
                        
                        self.current_trace.add_event("tool_call_start", f"{tc.tool_name}({arg_summary})", t=start_time_dt)
                        end_time_dt = start_time_dt + timedelta(milliseconds=dur_ms)
                        self.current_trace.add_event("tool_call_end", f"{tc.tool_name} → {tc.outcome} {dur_ms}ms", t=end_time_dt)

                if timing_lines[1:]:
                    console.debug("Task Timing Summary", "\n".join(timing_lines),
                            task_id=task_id, agent_id=self.agent_id)
            
            # Show detailed execution timeline in verbose mode
            if self.verbose == "high" and (tool_entries or llm_breakdown):
                from rich.table import Table
                import rich.box as rich_box

                def _to_sort_ts(raw_ts):
                    if isinstance(raw_ts, (int, float)):
                        return float(raw_ts)
                    if isinstance(raw_ts, str):
                        try:
                            return datetime.fromisoformat(raw_ts).timestamp()
                        except Exception:
                            return 0.0
                    return 0.0

                duplicated_phase_tools = {'prefilter', 'llm_code_generation', 'llm_connection_filtering', 'llm_rag_retrieval'}
                
                # Exclude duplicate LLM tracking tasks that are already natively logged as explicit tools
                hidden_llm_breakdown_funcs = {"llm", "web_search", "gmail_dsl_parsing"}
                llm_function_names = {c.get('function_name', '') for c in llm_breakdown if isinstance(c, dict)} - hidden_llm_breakdown_funcs

                _LLM_LABELS = {
                    'llm_code_generation':       'Planning',
                    'prefilter':                 'Prefilter',
                    'llm_connection_filtering':  'Connection filter',
                    'llm_rag_retrieval':         'RAG retrieval',
                }

                timeline_items = []

                # LLM calls — description comes from the phase label, model goes to Info
                for call in llm_breakdown:
                    fn = call.get('function_name', 'unknown')
                    if fn in hidden_llm_breakdown_funcs:
                        continue
                    
                    label = _LLM_LABELS.get(fn, fn)
                    model = call.get('model', '')
                    timeline_items.append({
                        'type': 'llm',
                        'timestamp': _to_sort_ts(call.get('timestamp', 0)),
                        'tool': 'llm',
                        'description': label,
                        'params': f"model={model}" if model else '',
                        'duration': call.get('duration', 0) or 0,
                        'wait_time': 0,
                        'status': 'ok',
                    })

                # Tool / phase calls
                for entry in completed_tools:
                    tn = entry.get('tool', 'unknown')
                    if tn in duplicated_phase_tools or tn in llm_function_names or tn == 'awaiting_approval':
                        continue
                    meta = entry.get('ui_metadata') or {}
                    args   = meta.get('_tool_trace_args') or {}
                    action = meta.get('_tool_action') or ''
                    param_parts = []
                    if action:
                        param_parts.append(f"action={action}")
                    for k, v in list(args.items())[:6]:
                        v_s = str(v)
                        if len(v_s) > 80:
                            v_s = v_s[:77] + '…'
                        param_parts.append(f"{k}={v_s}")
                    timeline_items.append({
                        'type': 'tool',
                        'timestamp': _to_sort_ts(entry.get('timestamp', 0)),
                        'tool': tn,
                        'description': entry.get('description', ''),
                        'params': '  '.join(param_parts),
                        'duration': entry.get('duration', 0) or 0,
                        'wait_time': entry.get('wait_time', 0) or 0,
                        'status': entry.get('status', 'unknown'),
                    })

                timeline_items.sort(key=lambda x: x['timestamp'])

                # ── Table ────────────────────────────────────────────────────
                timeline_table = Table(
                    title="[bold]Execution Timeline[/bold]",
                    show_header=True, header_style="bold",
                    box=rich_box.SIMPLE_HEAD, show_lines=True, expand=True, padding=(0, 1),
                )
                timeline_table.add_column("Description", ratio=4)
                timeline_table.add_column("Tool",        min_width=12, style="bright_yellow", no_wrap=True)
                timeline_table.add_column("Params",      ratio=5,      style="dim")
                timeline_table.add_column("Duration",    min_width=8,  no_wrap=True)

                for item in timeline_items:
                    dur  = item['duration']
                    if dur <= 0:
                        dur_str = "[dim]—[/dim]"
                    else:
                        dur_str = f"{dur:.2f}s"

                    if item['type'] == 'llm':
                        icon = "[dim]~[/dim]"
                    elif item['status'] in ('ok', 'success'):
                        icon = "[green]✓[/green]"
                    else:
                        icon = "[red]✗[/red]"

                    timeline_table.add_row(
                        item['description'] or "[dim]—[/dim]",
                        f"{icon} {item['tool']}",
                        item['params'] or "[dim]—[/dim]",
                        dur_str,
                    )

                console.console.print(timeline_table)
                console.console.print()
            
            # Determine task status and final message
            if result.get("success"):
                task_status = "success"
                output_raw = result.get("output", "")
                result_raw = result.get("result", "")

                # Safely normalize to strings, avoid None.strip()
                output = output_raw.strip() if isinstance(output_raw, str) else (str(output_raw).strip() if output_raw is not None else "")
                result_value = result_raw.strip() if isinstance(result_raw, str) else (str(result_raw).strip() if result_raw is not None else "")
                
                # Avoid duplication: if output and result are the same, use only one
                # If output exists and is different from result, prefer output (from print statements)
                # If result exists and is different from output, prefer result (explicit return)
                if output and output != result_value:
                    final_message = output
                elif result_value and result_value != output:
                    final_message = result_value
                elif output:
                    final_message = output
                elif result_value:
                    final_message = result_value
                else:
                    final_message = "Task completed successfully"
            else:
                task_status = "error"
                error_msg = result.get("error", "Unknown error")
                output_msg = result.get("output", "")
                
                # Provide more helpful error message
                if "Tool not found" in error_msg or "tool" in error_msg.lower():
                    final_message = f"Task failed: {error_msg}\n\nTip: Make sure all required tools (gmail, files, sheets, llm) are configured for this agent."
                elif "No Python code generated" in error_msg or "Unable to generate code" in error_msg:
                    final_message = f"Task failed: {error_msg}\n\nTip: The task may require specific tools. Ensure gmail, files, sheets, and llm tools are available."
                else:
                    # Include output if available (may contain useful error context)
                    if output_msg and output_msg.strip():
                        final_message = f"Task failed: {error_msg}\n\nOutput:\n{output_msg}"
                    else:
                        final_message = f"Task failed: {error_msg}"
            
            tools_used = [
                entry.get("tool") if isinstance(entry, dict) else str(entry)
                for entry in self.get_tools_used(task_id)
            ]
            
            # Log final task completion status BEFORE summary
            status_label = task_status.upper()
            console.info(status_label, "Task has being completed", task_id=task_id, agent_id=self.agent_id)
            
            console.task_summary(task_id, task_duration, token_info, "completed", final_message,
                                 computational_time, wait_time=total_wait_time, agent_id=self.agent_id, task_status=task_status, tools=tools_used, llm_config=self.llm_config)
            
            self.logger.complete_task(task_id, task_status, computational_time)
            
            # Store task result
            self.task_results[task_id] = {
                "status": task_status,
                "completed": result.get("success", False),
                "final_message": final_message,
                "duration": task_duration,
                "compute_time": computational_time,
                "tokens_used": token_info.get('tokens_used', 0),
                "cost_usd": token_info.get('total_cost_usd'),
                "trace": self.current_trace
            }
            
            if self.current_trace:
                from datetime import datetime
                self.current_trace.ended_at = datetime.now()
                self.current_trace.outcome = "success" if result.get("success", False) else "failed"
                self.current_trace.total_cost_usd = token_info.get('total_cost_usd')
                self.current_trace.pricing_path = token_info.get('pricing_path', "") or ""

                cost_by_function = {}
                for call in llm_breakdown:
                    fn = call.get("function_name", "unknown")
                    c_val = call.get("cost_usd")
                    if c_val is not None:
                        cost_by_function[fn] = cost_by_function.get(fn, 0.0) + float(c_val)
                self.current_trace.cost_by_function = {k: round(v, 8) for k, v in cost_by_function.items()}

                def _sum_costs(*fns):
                    costs = [cost_by_function[f] for f in fns if f in cost_by_function]
                    return round(sum(costs), 8) if costs else None

                if self.current_trace.prefilter:
                    self.current_trace.prefilter.cost_usd = _sum_costs("prefilter", "llm_connection_filtering", "llm_rag_retrieval")
                if self.current_trace.code_generation:
                    self.current_trace.code_generation.cost_usd = _sum_costs("llm_code_generation", "llm_retry")
                if self.current_trace.execution:
                    reserved = {"prefilter", "llm_connection_filtering", "llm_rag_retrieval", "llm_code_generation", "llm_retry"}
                    exec_fns = [fn for fn in cost_by_function if fn not in reserved]
                    self.current_trace.execution.cost_usd = _sum_costs(*exec_fns)

                self.current_trace.add_event("session_end", f"outcome: {self.current_trace.outcome}")
            
            # Notify chat of the assistant response
            if self.on_task_complete and task_status == "success":
                try:
                    self.on_task_complete(task_id, final_message)
                except Exception:
                    pass

            # Cleanup
            for active_key in list(self._active_phase_logs.keys()):
                if active_key[0] == task_id:
                    self._active_phase_logs.pop(active_key, None)
            self.wait_times.pop(task_id, None)
            self._cleanup_wait_times_if_needed()
            
        except Exception as e:
            elapsed = time.time() - start_time
            total_wait_time = self.wait_times.get(task_id, 0.0)
            comp_time = max(elapsed - total_wait_time, 0.0)

            error_text = f"{type(e).__name__}: {str(e)}"
            console.print_exception(e, title="Task Execution Failed")

            if self.logger:
                self.logger.complete_task(task_id, "error", comp_time)

            # Store task result for callers and diagnostics
            self.task_results[task_id] = {
                "status": "error",
                "completed": False,
                "final_message": f"Task failed: {error_text}",
                "duration": elapsed,
                "compute_time": comp_time,
                "tokens_used": 0,
                "trace": self.current_trace
            }

            # Cleanup
            for active_key in list(self._active_phase_logs.keys()):
                if active_key[0] == task_id:
                    self._active_phase_logs.pop(active_key, None)
            self.wait_times.pop(task_id, None)
            self._cleanup_wait_times_if_needed()
    
    async def llm_filter_connections(self, message: str, task_id: str = "") -> list:
        """
        Filter connections based on task description using LLM.
        
        Args:
            message: Task message
            task_id: Task ID for logging
        
        Returns:
            List of connection IDs that are relevant to the task
        """
        # Track timing for filtering step
        await self.track_tool_timing_async(task_id, "llm_connection_filtering", None, self.prefilter_llm, description=self._ui_text("analyzing_connections"), is_starting=True)
        
        llm_start_time = time.time()
        
        # Get all available connections with descriptions
        connections = list(self.tools.connections.values())
        if not connections:
            # No connections to filter, return empty list
            llm_duration = time.time() - llm_start_time
            await self.track_tool_timing_async(task_id, "llm_connection_filtering", llm_duration, self.prefilter_llm, description=self._ui_text("analyzing_connections"), is_starting=False)
            return []
        
        # OPTIMIZATION: If <= 2 connections, skip LLM filtering and return all
        if len(connections) < 3:
            console.debug("Connection filtering skipped", f"Only {len(connections)} connections available", task_id=task_id, agent_id=self.agent_id)
            llm_duration = time.time() - llm_start_time
            await self.track_tool_timing_async(task_id, "llm_connection_filtering", llm_duration, self.prefilter_llm, description="Skipped filtering (low count)", is_starting=False)
            return connections
        
        # Build connection descriptions for LLM
        connection_list = []
        for idx, conn in enumerate(connections, 1):
            conn_name = conn.connection_name if hasattr(conn, 'connection_name') else f"Connection {idx}"
            conn_tool = conn.tool_name if hasattr(conn, 'tool_name') else "unknown"
            conn_desc = conn.metadata.get('description', '') if hasattr(conn, 'metadata') else ''
            if not conn_desc and hasattr(conn, 'description'):
                conn_desc = conn.description
            connection_list.append(f"{idx}. {conn_name} ({conn_tool}): {conn_desc if conn_desc else 'No description'}")
        
        connections_text = "\n".join(connection_list)
        
        prompt = f"""You are a connection filter. Analyze the task and select ONLY the connections needed.

Task: {message}

Available Connections:
{connections_text}

Guidelines:
- Read/search emails → need gmail connection
- Create Google Sheets (spreadsheet) → need sheets connection
- Create Google Docs (document) → need docs connection
- Create Excel/CSV files (local files) → need files connection
- Upload files to Drive → need drive connection
- Database queries → need sql connection
- Search web → need websearch connection...

IMPORTANT: 
- "Use excel" usually means Google Sheets (use sheets), NOT local Excel file (files)
- Only use drive if task explicitly mentions uploading to Drive or searching Drive
- Only use files if task explicitly mentions saving local files (Excel/CSV files on disk)

CRITICAL: Output ONLY comma-separated numbers (e.g., "1" or "1,2"). Do NOT output "ALL", "all", connection names, or any text. If no connections match, output "NONE".

Examples:
Task: "Read emails from contacto@civislend.com and create Excel file"
Connections:
1. Gmail (gmail): Email access
2. Sheets (sheets): Google Spreadsheets
3. Files (files): Local file operations
Output: 1,2

Task: "Read emails and create a spreadsheet with the data"
Connections:
1. Gmail (gmail): Email
2. Sheets (sheets): Spreadsheets
Output: 1,2

Task: "Give me top 10 expensive tasks from database"
Connections:
1. Gmail (gmail): Email
2. Sales DB (sql): Database
Output: 2

Now analyze the task and output ONLY the connection numbers (comma-separated) or "NONE":"""
        
        try:
            llm_result = await llm_completion_async(
                model=self.prefilter_llm,
                prompt=prompt,
                temperature=0.0,
                max_tokens=50
            )
            llm_duration = time.time() - llm_start_time
            
            # Track completion
            await self.track_tool_timing_async(task_id, "llm_connection_filtering", llm_duration, self.prefilter_llm, description=self._ui_text("analyzing_connections"), is_starting=False)
            
            response, norm_token_info = normalize_llm_result(llm_result)
            
            # Log tokens
            self._safe_add_tokens(task_id, norm_token_info, self.prefilter_llm, "llm_connection_filtering", duration=llm_duration)
            
            # Log raw response for debugging
            console.debug("Connection filtering LLM response", 
                         f"Raw response: {response}", 
                         task_id=task_id, agent_id=self.agent_id)
            
            return self._parse_connection_filter_selection(response, connections, task_id=task_id)
            
        except Exception as e:
            llm_duration = time.time() - llm_start_time
            await self.track_tool_timing_async(task_id, "llm_connection_filtering", llm_duration, self.light_llm, description=self._ui_text("analyzing_connections"), is_starting=False)
            console.error("Connection filtering failed", 
                         f"{type(e).__name__}: {str(e)}", 
                         task_id=task_id, agent_id=self.agent_id)
            return []
    
    async def llm_generate_python(self, message: str, task_id: str = "", sql_schema: str = None, relevant_connections: list = None, memory_context: str = None) -> str:
        """
        Generate Python code to accomplish the task.
        
        Args:
            message: Task message
            task_id: Task ID for logging
            sql_schema: Optional SQL schema string
            relevant_connections: Optional list of filtered connections (if None, uses all)
            memory_context: Optional long-term memory facts retrieved via embeddings
        
        Returns:
            Python code string ready to execute
        """
        # sql_schema_section will be built AFTER schema is fetched (if needed)
        sql_schema_section = ""
        
        # Build system prompt section if available
        agent_context_section = ""
        if self.system_prompt:
            agent_context_section = f"\n\nContext:\n{self.system_prompt}"

        # Build long-term memory section if available
        memory_context_section = ""
        if memory_context:
            memory_context_section = f"\n\nLong-term Memory (relevant facts):\n{memory_context}"

        # Use filtered connections if provided, otherwise use all
        connections = relevant_connections if relevant_connections is not None else list(self.tools.connections.values())
        
        # ========== INTELLIGENT CONTEXT FILTERING ==========
        # Use a cheap LLM call with minimal summaries to select which tools/actions are needed
        # Then only include compressed docs for those specific tools/actions
        
        # Get available tools/actions from connections
        available_actions = get_available_actions_for_connections(connections, custom_tools=self.tools.tools)
        
        # ========== OPTIONAL PREFILTERING STEP ==========
        # If prefilter is disabled, skip filtering and use all available tools
        # Check for SQL tools early, as we may start schema fetch either way
        has_sql_connections = "sql" in self.tools.tools
        schema_task = None
        
        async def _fetch_sql_schema_optimistic():
            """Fetch SQL schema for all SQL connections. Runs concurrently with prefilter or code gen."""
            schema_start = time.time()
            sql_conns = [
                conn for conn in self.tools.connections.values()
                if getattr(conn, "tool_name", "").lower() == "sql" and conn.is_active()
            ]
            if not sql_conns:
                return None
            
            schema_parts = []
            for sql_conn in sql_conns:
                conn_name = sql_conn.connection_name
                
                # Use cached schema if valid
                current_time = time.time()
                cache_key = f"sql_schema_{conn_name}"
                cached = getattr(self, '_sql_schema_cache_map', {}).get(cache_key)
                cached_time = getattr(self, '_sql_schema_time_map', {}).get(cache_key, 0)
                
                if cached and (current_time - cached_time < self.SQL_SCHEMA_CACHE_TTL):
                    schema_text = cached
                    console.debug(f"SQL schema used from cache", f"connection={conn_name}", task_id=task_id, agent_id=self.agent_id)
                else:
                    schema_result = await self.tools.execute_tool(
                        sql_conn.connection_name,
                        context={"action": "SCHEMA", "params": {}},
                        task_id=task_id,
                        light_llm=self.light_llm,
                        heavy_llm=self.heavy_llm,
                        agent_id=self.agent_id,
                        validation_mode=False,
                    )
                    if isinstance(schema_result, dict) and "schema" in schema_result:
                        schema_text = str(schema_result.get("schema") or "")
                    else:
                        schema_text = str(schema_result or "")
                    
                    # Update per-connection cache
                    if not hasattr(self, '_sql_schema_cache_map'):
                        self._sql_schema_cache_map = {}
                        self._sql_schema_time_map = {}
                    self._sql_schema_cache_map[cache_key] = schema_text
                    self._sql_schema_time_map[cache_key] = current_time
                
                if schema_text:
                    if len(sql_conns) > 1:
                        schema_parts.append(f'--- Connection: "{conn_name}" ---\n{schema_text}')
                    else:
                        schema_parts.append(schema_text)
            
            schema_duration = time.time() - schema_start
            return "\n\n".join(schema_parts) if schema_parts else None
        
        if not self.enable_prefilter:
            # Prefilter disabled - use all available tools directly
            # Convert available_actions dict to list of "tool:action" strings
            all_actions = []
            for tool_name, actions in available_actions.items():
                for action in actions:
                    all_actions.append(f"{tool_name}:{action}")
            
            selected_actions = all_actions  # Use all available actions
            connection_map = {}  # Will be populated from connections
            
            # Build connection context from all available connections
            for conn in (relevant_connections or list(self.tools.connections.values())):
                tool_name = getattr(conn, "tool_name", "").lower()
                if tool_name:
                    if tool_name not in connection_map:
                        connection_map[tool_name] = []
                    connection_map[tool_name].append(getattr(conn, "connection_name", ""))
            
            # Start schema fetch if SQL tools are available
            if has_sql_connections:
                schema_task = asyncio.create_task(_fetch_sql_schema_optimistic())
            
            # Build full API docs with all available tools (not filtered)
            python_api_docs = build_filtered_api_docs(all_actions, custom_descriptions=self.tool_descriptions)
            python_examples = ""
            
            console.info("Code generation", "Starting (prefilter disabled - using all tools)", task_id=task_id, agent_id=self.agent_id)
        else:
            # Prefilter enabled - use LLM to filter relevant tools
            # Build prefilter prompt with connection names/descriptions
            # Include compacted memory context so prefilter remains token-efficient.
            prefilter_task = message
            if memory_context:
                compact_memory = self._compact_prefilter_memory_context(memory_context)
                if compact_memory:
                    prefilter_task = f"{message}\n\n[Relevant memory facts]\n{compact_memory}"
            prefilter_prompt = build_prefilter_prompt(prefilter_task, available_actions, connections=connections, custom_descriptions=self.tool_descriptions)
            
            # ========== OPTIMISTIC PARALLEL SCHEMA FETCH ==========
            # If SQL connections exist, start fetching schema IN PARALLEL with prefilter
            # This saves ~1.5s on SQL tasks (schema fetch runs while prefilter is thinking)
            if has_sql_connections:
                schema_task = asyncio.create_task(_fetch_sql_schema_optimistic())
            
            # Use light LLM for cheap prefiltering
            connection_map = {}  # tool_name -> [connection_name, ...]
            try:
                # Track UI step for filtering
                await self.track_tool_timing_async(task_id, "prefilter", None, self.prefilter_llm, description=self._ui_text("analyzing_connections"), is_starting=True)
                
                prefilter_start = time.time()
                prefilter_result = await llm_completion_async(
                    model=self.prefilter_llm, # Use configured prefilter llm
                    prompt=prefilter_prompt,
                    temperature=0.0,
                    max_tokens=1000  # Enough for direct answers or comma-separated tool list
                )
                prefilter_duration = time.time() - prefilter_start
                
                # Normalize the result first to get the response string
                prefilter_response, prefilter_tokens = normalize_llm_result(prefilter_result)
                
                # ========== DIRECT ANSWER SHORTCUT ==========
                # If the prefilter returns "ANSWER: <text>", answer directly without code gen
                stripped_response = prefilter_response.strip()
                if stripped_response.upper().startswith("ANSWER:"):
                    answer_text = stripped_response[7:].strip()
                    
                    # Cancel schema task if running
                    if schema_task and not schema_task.done():
                        schema_task.cancel()
                    
                    # Track completion
                    await self.track_tool_timing_async(
                        task_id, "prefilter", prefilter_duration, self.prefilter_llm,
                        description="Direct answer (no tools needed)", is_starting=False,
                        metadata={"direct_answer": True}
                    )
                    # Log prefilter tokens
                    self._safe_add_tokens(task_id, prefilter_tokens, self.prefilter_llm, "prefilter", duration=prefilter_duration)
                    
                    console.debug("Prefilter direct answer", 
                                 f"Answered directly without code generation ({prefilter_duration*1000:.0f}ms)", 
                                 task_id=task_id, agent_id=self.agent_id)
                    
                    # Return a simple print() that outputs the answer
                    escaped_answer = answer_text.replace('\\', '\\\\').replace('"""', '\\"\\"\\"')
                    return f'print("""{escaped_answer}""")'
                
                # Parse selected actions AND connection mapping
                selected_actions, connection_map = parse_prefilter_response(prefilter_response, connections)

                # Enforce allow restrictions strictly before code generation docs are built.
                # If prefilter proposes disallowed actions, drop them and warn.
                selected_actions, blocked_actions = filter_selected_actions(selected_actions, available_actions)
                if blocked_actions:
                    console.warning(
                        "Prefilter proposed disallowed actions",
                        (
                            "Blocked actions were removed before code generation: "
                            f"{', '.join(sorted(blocked_actions))}"
                        ),
                        task_id=task_id,
                        agent_id=self.agent_id,
                    )
                
                # Show available actions in verbose mode
                if self.verbose == "high":
                    from rich.panel import Panel
                    from rich.table import Table
                    from collections import defaultdict
                    
                    # Group actions by tool
                    actions_by_tool = defaultdict(list)
                    if isinstance(available_actions, dict):
                        for tool, acts_set in available_actions.items():
                            for act in acts_set:
                                if act not in actions_by_tool[tool]:
                                    actions_by_tool[tool].append(act)
                    else:
                        # Fallback if it's a list (legacy)
                        for action in available_actions:
                            parts = action.split(":")
                            tool = parts[0] if parts else "unknown"
                            act = ":".join(parts[1:]) if len(parts) > 1 else tool
                            if act not in actions_by_tool[tool]:
                                actions_by_tool[tool].append(act)
                    
                    # Identify internal framework tools
                    internal_tool_names = {"files", "llm", "lzmafilter", "sql", "gmail", "sheets", "drive", "calendar", "docs", "websearch", "memory"}
                    
                    # Add memory tool if configured
                    if self.memory:
                        actions_by_tool["memory"] = {"save"}
                    
                    # Create table with tools grouped by type
                    actions_table = Table(title="Available Actions for Agent", show_header=True, header_style="bold cyan")
                    actions_table.add_column("Tool", style="cyan", width=20)
                    actions_table.add_column("Actions", style="green")
                    actions_table.add_column("Type", style="dim yellow", width=12)
                    
                    # Display user-provided tools FIRST (higher priority for agent)
                    user_tools_added = False
                    for tool_name in sorted(actions_by_tool.keys()):
                        if tool_name not in internal_tool_names:
                            if not user_tools_added:
                                user_tools_added = True
                            
                            acts = actions_by_tool[tool_name]
                            actions_str = ", ".join(sorted(acts))
                            
                            # Mark selected tools
                            is_selected = any(a.startswith(tool_name + ":") or a == tool_name or a == f"[{tool_name}]" for a in selected_actions)
                            status_style = "bold green" if is_selected else "dim"
                            
                            actions_table.add_row(
                                f"[{status_style}]{tool_name}[/{status_style}]",
                                f"[{status_style}]{actions_str}[/{status_style}]",
                                f"[bold magenta]User[/bold magenta]"
                            )
                    
                    # Add separator
                    if user_tools_added:
                        actions_table.add_row("[dim]─[/dim]", "[dim]─[/dim]", "[dim]─[/dim]")
                    
                    # Display internal tools (sandbox/framework only)
                    for tool_name in sorted(actions_by_tool.keys()):
                        if tool_name in internal_tool_names:
                            acts = actions_by_tool[tool_name]
                            actions_str = ", ".join(sorted(acts))
                            
                            # Mark selected tools
                            is_selected = any(a.startswith(tool_name + ":") or a == tool_name or a == f"[{tool_name}]" for a in selected_actions)
                            status_style = "bold green" if is_selected else "dim"
                            actions_table.add_row(
                                f"[{status_style}]{tool_name}[/{status_style}]",
                                f"[{status_style}]{actions_str}[/{status_style}]",
                                f"[dim white]Internal[/dim white]"
                            )
                    
                    # Add legend/explanation at the bottom
                    actions_table.caption = (
                        "[bold]Legend:[/bold] "
                        "[bold magenta]User[/bold magenta] = Tools you provided (Native, MCP, Custom Tools) | "
                        "[dim white]Internal[/dim white] = Sandbox-only tools (files, llm)"
                    )
                    
                    actions_panel = Panel(actions_table, border_style="cyan", expand=False)
                    console.console.print(actions_panel)
                    console.console.print()  # Blank line
                
                # Trace updating
                if self.current_trace:
                    from datetime import datetime
                    pf_end_dt = datetime.now()
                    pf_start_dt = datetime.fromtimestamp(prefilter_start)
                    tools_avail_count = len(available_actions)
                    base_selected = {action.split(":")[0] for action in selected_actions}
                    tools_rej = [a for a in available_actions if a not in base_selected]
                    self.current_trace.prefilter = PrefilterTrace(
                        started_at=pf_start_dt,
                        duration_ms=int(prefilter_duration * 1000),
                        model_used=self.prefilter_llm,
                        tools_available=tools_avail_count,
                        tools_selected=list(base_selected),
                        tools_rejected=tools_rej,
                        tokens_input=prefilter_tokens.get("input_tokens", prefilter_tokens.get("prompt_tokens", 0)),
                        tokens_output=prefilter_tokens.get("output_tokens", prefilter_tokens.get("completion_tokens", 0)),
                        ran_parallel_with="sql_schema_fetch" if schema_task else None
                    )
                    self.current_trace.add_event("prefilter_complete", f"{len(selected_actions)} tools selected", t=pf_end_dt)

                # Track completion with selected tools in metadata
                await self.track_tool_timing_async(
                    task_id, 
                    "prefilter", 
                    prefilter_duration, 
                    self.prefilter_llm,
                    description=self._ui_text("analyzing_connections"), 
                    is_starting=False,
                    metadata={"selected_tools": selected_actions, "connection_map": connection_map}
                )
                
                # Log prefilter tokens
                self._safe_add_tokens(task_id, prefilter_tokens, self.prefilter_llm, "prefilter", duration=prefilter_duration)
                
                # Extract tool names without :EXECUTE suffix for cleaner summary
                selected_tools = set()
                for action in selected_actions:
                    tool_name = action.split(':')[0] if ':' in action else action
                    selected_tools.add(tool_name)
                
                # Log prefiltering completion with tool count
                tool_count = len(selected_tools)
                tool_label = "tool" if tool_count == 1 else "tools"
                console.info("Prefiltering", f"— {tool_count} {tool_label} selected", task_id=task_id, agent_id=self.agent_id)
                
                # Build compressed API docs for only selected actions
                python_api_docs = build_filtered_api_docs(selected_actions, custom_descriptions=self.tool_descriptions)
                
                # Build minimal examples for selected tools
                python_examples = ""  # Examples are included in compressed docs
                
            except Exception as e:
                console.error("Prefilter failed", str(e), 
                           task_id=task_id, agent_id=self.agent_id)
            raise
        
        # Log what we're using
        tools_info = ", ".join(selected_actions) if selected_actions else "prefiltered"
        # Extract unique tool names without :EXECUTE suffix
        selected_tools = set()
        for action in tools_info.split(", "):
            tool_name = action.split(':')[0] if ':' in action else action
            if tool_name:
                selected_tools.add(tool_name.strip())
        tools_summary = ", ".join(sorted(selected_tools)) if selected_tools else "(none)"
        

        # ========== AWAIT SQL SCHEMA (already fetching in parallel) ==========
        needs_sql = any(a.lower().startswith('sql:') for a in selected_actions)
        
        if needs_sql and schema_task:
            try:
                await self.track_tool_timing_async(task_id, "sql_schema", None, None, description=self._ui_text("fetching_schema"), is_starting=True)
                schema_start = time.time()
                sql_schema = await schema_task  # Already running — may be done already!
                schema_duration = time.time() - schema_start
                
                if sql_schema:
                    self._sql_schema_cache = sql_schema
                    self._sql_schema_last_fetch = time.time()
                
                await self.track_tool_timing_async(task_id, "sql_schema", schema_duration, None, description=self._ui_text("fetching_schema"), is_starting=False)
                console.debug("SQL schema ready", f"({schema_duration*1000:.0f}ms wait after prefilter)", task_id=task_id, agent_id=self.agent_id)
                
            except Exception as e:
                console.error("SQL schema introspection failed", f"{e}", 
                            task_id=task_id, agent_id=self.agent_id)
                sql_schema = None
        else:
            # SQL not needed — cancel optimistic fetch if running
            if schema_task and not schema_task.done():
                schema_task.cancel()
            sql_schema = None

        # Build SQL schema section NOW (after schema is fetched)
        if sql_schema:
            sql_schema_section = f"\n\n**DATABASE SCHEMA** (YAML format `table: col(type)`. Use ONLY these exact table/column names):\n{sql_schema}"
        
        # Build connection context section for the prompt
        connection_context_section = build_connection_context_for_prompt(connection_map, connections)

        from datetime import datetime, timezone
        current_dt = datetime.now(timezone.utc).astimezone()
        current_date_str = current_dt.strftime("%Y-%m-%d %H:%M %Z")

        # Build examples section
        examples_section = ""
        if python_examples:
            examples_section = f"\n\nEXAMPLES:\n{python_examples}"

        memory_tool_section = ""
        if self.memory:
            memory_guidelines = (getattr(self.memory, "guidelines", "") or "").strip()
            if not memory_guidelines:
                memory_guidelines = "Store stable user preferences, durable facts, and final decisions."
            memory_tool_section = (
                "\n\nMEMORY:\n"
                f"- `await memory.save(\"fact\", desc=\"why\")` (Markdown. Atomic facts.)\n"
                f"- Follow: {memory_guidelines}"
            )

        python_prompt = f"""Task: "{message}"{sql_schema_section}{connection_context_section}{agent_context_section}{memory_context_section}
Date: {current_date_str}

BEFORE CODING: If task is vague (missing names/dates/files), output ONLY a print() asking clarification. E.g.: `print("Need keywords to find invoice")`

{python_api_docs}{memory_tool_section}

RULES:
- ONLY Python code. Minimal code. Async (await). NO asyncio.run(); define `async def main():...` & `await main()`.
- NEVER pass connection_name (auto-detected).
- EVERY tool call MUST include `desc="..."` with a short, specific action text.
- If you call `websearch.search`, `llm.call`, `sql.query`, `gmail.read`, `sheets.write`, etc., include `desc=` explicitly in that same call.
- `desc` must describe intent (e.g., `desc="Searching AI news April 2026"`), not a generic label.
- SELF-CHECK BEFORE OUTPUT: if any tool call is missing `desc=`, rewrite the code before returning it.
- `files` tool ONLY reads Sandbox uploads. For local files, use MCP if available.
- User visibility: ONLY print() is visible. Print final answers. Use Markdown, `format_table()`. Match user language.
- Order: Wait for tool output before generating text dependent on it.
- Processing N items (emails, rows, files): ALWAYS `asyncio.gather(*[process(x) for x in items])`, NEVER sequential `for` loops with `await`.
- Libs: asyncio, json, re, datetime, time, math, statistics. NO pandas.
- WEBSEARCH: If value needed, ask "Return ONLY JSON: {{k:v}}" -> use `safe_json_loads(response)` (returns None on empty/invalid). If None, abort and print raw response. NEVER hardcode/guess facts.
{examples_section}

OUTPUT: Python code ONLY. NO comments. Only print() is visible, use markdown."""
        
        # Execute LLM to generate Python code
        try:
            # Track starting entry BEFORE LLM call (so frontend sees "Planning..." with thinking animation)
            # Use async version to properly await the callback
            await self.track_tool_timing_async(task_id, "llm_code_generation", None, self.code_generation_llm, description=self._ui_text("planning"), is_starting=True)
            
            llm_start_time = time.time()
            
            llm_result = await llm_completion_async(
                model=self.code_generation_llm,
                prompt=python_prompt,
                temperature=0.0,
                max_tokens=4000,
                response_format=None
            )
            llm_duration = time.time() - llm_start_time

            # Track completion (this updates the starting entry with duration)
            # Use async version to properly await the callback
            await self.track_tool_timing_async(task_id, "llm_code_generation", llm_duration, self.code_generation_llm, description=self._ui_text("planning"), is_starting=False)
            self.track_tool_usage(task_id, "llm_code_generation", self.code_generation_llm)
            
            response, norm_token_info = normalize_llm_result(llm_result)
            
            # Log tokens
            try: 
                self._add_tokens(task_id, norm_token_info, self.code_generation_llm, "llm_code_generation", duration=llm_duration)
            except Exception: 
                pass
            
            # Log raw response (full, without truncation)
            console.debug(
                "LLM Python generation",
                f"Generated {len(response)} chars",
                task_id=task_id,
                agent_id=self.agent_id,
            )
            
            # Extract Python code from response
            python_code = parse_python_code(response)

            if python_code and python_code.strip():
                if self.current_trace:
                    from datetime import datetime
                    cg_end_dt = datetime.now()
                    cg_start_dt = datetime.fromtimestamp(llm_start_time)
                    if not self.current_trace.code_generation:
                        self.current_trace.code_generation = CodeGenTrace(
                            started_at=cg_start_dt,
                            duration_ms=int(llm_duration * 1000),
                            model_used=self.code_generation_llm,
                            system_prompt=python_prompt if self.trace_mode == "full" else "...",
                            code_generated=python_code,
                            tokens_input=norm_token_info.get("input_tokens", 0),
                            tokens_output=norm_token_info.get("output_tokens", 0),
                            attempt=1
                        )
                        self.current_trace.add_event("codegen_complete", f"{self.current_trace.code_generation.tokens_output} tokens generated", t=cg_end_dt)
                    else:
                        self.current_trace.code_generation.attempt += 1

                # Basic validation: check for common scope errors
                # Look for common patterns where loop variables are used outside their scope
                lines = python_code.split('\n')
                common_loop_vars = ['email', 'file_path', 'attachment', 'row', 'item', 'data']
                
                for var_name in common_loop_vars:
                    in_loop = False
                    loop_start = None
                    for i, line in enumerate(lines):
                        stripped = line.strip()
                        if not stripped or stripped.startswith('#'):
                            continue
                        
                        # Detect loop start
                        if f'for {var_name} in' in stripped:
                            in_loop = True
                            loop_start = i + 1
                        
                        # Detect loop end (line with same or less indentation, not a continuation)
                        elif in_loop:
                            current_indent = len(line) - len(line.lstrip())
                            prev_indent = len(lines[i-1]) - len(lines[i-1].lstrip()) if i > 0 else 0
                            # If indentation decreased significantly, loop likely ended
                            if current_indent < prev_indent and current_indent <= 2:
                                in_loop = False
                        
                        # Check for usage outside loop
                        if not in_loop and loop_start and (f'{var_name}[' in stripped or f'{var_name}.' in stripped or f'{var_name},' in stripped or f'{var_name})' in stripped):
                            console.warning("Potential scope error detected", 
                                       f"Line {i+1}: '{stripped[:80]}' uses '{var_name}' outside loop context (loop started at line {loop_start}). This may cause NameError.",
                                       task_id=task_id, agent_id=self.agent_id)
                
                console.debug("Python code extracted", 
                             f"Ready to execute ({len(python_code)} chars)", 
                             task_id=task_id, agent_id=self.agent_id)
                return python_code.strip()
            else:
                console.error("No valid Python code extracted", 
                             "LLM response did not contain executable code",
                             task_id=task_id, agent_id=self.agent_id)
                return ""
            
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            console.error("Python code generation failed", 
                         f"{type(e).__name__}: {str(e)}\n\nTraceback:\n{error_trace}", 
                         task_id=task_id, agent_id=self.agent_id)
            return ""
