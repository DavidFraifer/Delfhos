"""
Orchestrator - Python-Based Agent Task Execution

Thin coordinator that composes three mixins:
  - OrchestratorTimingMixin    (orchestrator_timing.py)
  - OrchestratorSchedulerMixin (orchestrator_scheduler.py)
  - OrchestratorCodegenMixin   (orchestrator_codegen.py)

Responsibilities kept here:
  - __init__ / configuration
  - require_approval
  - add_tool / add_connection / set_logger
  - _process_message_async (the main execution pipeline)
"""

from typing import Any, Dict, List, Optional, Union
import asyncio
import queue
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from ..utils.logger import CORTEXLogger
from ..utils.console import console
from ..utils.llm_utils import normalize_llm_result
from ..tools.tool import ToolContainer
from ..memory.AgentMemory import AgentMemory
from delfhos.errors import (
    ApprovalRejectedError,
    CodeGenerationError,
    LLMExecutionError,
    MemoryRetrievalError,
    SandboxExecutionError,
)
from ..internal.llm import llm_completion_async
from .python_executor import parse_python_code
from .approval_manager import ApprovalManager
from ..trace import (
    Trace, MemoryRetrievalTrace, ExecutionTrace, ToolCallTrace, EnrichmentTrace,
)

from .orchestrator_timing import OrchestratorTimingMixin
from .orchestrator_scheduler import OrchestratorSchedulerMixin
from .orchestrator_codegen import OrchestratorCodegenMixin


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


class Orchestrator(OrchestratorTimingMixin, OrchestratorSchedulerMixin, OrchestratorCodegenMixin):
    """
    Orchestrates agent task execution using Python code generation.

    Flow:
    1. Receive task message
    2. Retrieve long-term memory (embedding-based)
    3. Run prefilter to select relevant tools (optional)
    4. Pre-fetch SQL schema in parallel if needed
    5. Generate Python code via LLM
    6. Execute code in sandbox; auto-retry on failure
    7. Return result
    """

    SQL_SCHEMA_CACHE_TTL = 600  # 10 minutes

    def __init__(
        self,
        light_llm: str,
        heavy_llm: str,
        logger: CORTEXLogger,
        agent_id: str = "unknown",
        on_confirm=None,
        approval_enabled: bool = False,
        system_prompt: Optional[str] = None,
        prefilter_llm: Optional[str] = None,
        code_generation_llm: Optional[str] = None,
        vision_llm: Optional[str] = None,
        token_usage=None,
        memory=None,
        trace_mode: Union[str, bool] = "full",
        trace_callback=None,
        llm_config: Optional[str] = None,
        verbose: str = "low",
        enable_prefilter: bool = False,
        retry_count: int = 1,
        sandbox: str = "auto",
        sandbox_config: Optional[Dict] = None,
        files: Optional[List[str]] = None,
    ):
        approval_enabled = on_confirm is not None or approval_enabled

        # ── Core config ────────────────────────────────────────────────────
        self.trace_mode = trace_mode
        self.trace_callback = trace_callback
        self.current_trace = None
        self.api_enrichment_info = None  # Set by Agent._configure_tools() for APITool enrichment
        self.logger = logger
        self.light_llm = light_llm
        self.heavy_llm = heavy_llm
        self.llm_config = llm_config
        self.verbose = verbose
        self.enable_prefilter = enable_prefilter
        self.retry_count = retry_count

        # ── Model overrides ────────────────────────────────────────────────
        self.prefilter_llm = prefilter_llm or self.light_llm
        self.code_generation_llm = code_generation_llm or self.heavy_llm
        self.vision_llm = vision_llm or self.heavy_llm

        self.agent_id = agent_id
        self.enable_human_approval = approval_enabled
        self.confirm_policy = None
        self.system_prompt = system_prompt
        self.agent_context = {"system_prompt": system_prompt} if system_prompt else {}
        self.token_usage = token_usage
        self.memory = memory

        # ── Sandbox ────────────────────────────────────────────────────────
        self.sandbox_mode = sandbox
        self.sandbox_config = sandbox_config
        self.workspace_files = files or []

        # ── Tools ──────────────────────────────────────────────────────────
        self.tools = ToolContainer(logger=self.logger)
        self.tool_descriptions: Dict[str, str] = {}
        from ..tools.internal_tools import internal_tools
        for tool_name, tool_func in internal_tools.items():
            self.tools.add_tool(tool_name, tool_func)

        # ── Scheduler state (used by OrchestratorSchedulerMixin) ───────────
        self.message_queue = queue.Queue()  # Legacy compat (unused by scheduler)
        self._async_queue: asyncio.Queue = None
        self._scheduler_loop: asyncio.AbstractEventLoop = None
        self._scheduler_ready = threading.Event()
        self.scheduler_thread = None
        self.running = False

        # ── Per-task state ─────────────────────────────────────────────────
        self.agent_memory = AgentMemory(f"Orchestrator-Agent-{agent_id}", max_tasks=50)
        self.wait_times: Dict[str, float] = {}
        self.task_results: Dict[str, dict] = {}
        self.task_tools_used: Dict[str, list] = {}
        self.task_tool_timings: Dict[str, list] = {}
        self.tool_timing_callback = None
        self.on_task_complete = None
        self.detected_language = "en"
        self._active_phase_logs: Dict = {}

        # ── SQL schema cache ───────────────────────────────────────────────
        self._sql_schema_cache = None
        self._sql_schema_last_fetch = 0

        # ── Approval ──────────────────────────────────────────────────────
        self.approval_manager = ApprovalManager(on_confirm=on_confirm) if approval_enabled else None

    # ------------------------------------------------------------------ #
    #  Token accounting                                                    #
    # ------------------------------------------------------------------ #

    def _add_tokens(
        self,
        task_id: str,
        token_info: dict,
        model=None,
        function_name: str = None,
        duration: float = None,
    ):
        if model is not None and not isinstance(model, str):
            model = getattr(model, "model", str(model))
        if self.token_usage and token_info:
            self.token_usage.task.add(token_info)
        if self.logger:
            self.logger.add_tokens(task_id, token_info, model, function_name, duration)

    def _safe_add_tokens(
        self,
        task_id: str,
        token_info: dict,
        model: str = None,
        function_name: str = None,
        duration: float = None,
    ):
        try:
            self._add_tokens(task_id, token_info, model, function_name, duration=duration)
        except (AttributeError, TypeError, KeyError):
            pass  # best-effort: token accounting must not interrupt execution

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def set_logger(self, logger):
        self.logger = logger

    def add_tool(self, name: str, func, description: str = None):
        self.tools.add_tool(name, func)
        if description:
            self.tool_descriptions[name] = description

    def add_connection(self, connection, agent_id: str = None):
        self.tools.add_connection(connection, agent_id=agent_id or self.agent_id)

    # ------------------------------------------------------------------ #
    #  Approval flow                                                       #
    # ------------------------------------------------------------------ #

    async def require_approval(
        self,
        task_id: str,
        message: str,
        context: str = "",
        ui_metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Request human approval. Raises ApprovalRejectedError if denied."""
        if not self.approval_manager:
            return True

        start_time = time.time()
        request = await self.approval_manager.create_request_async(
            task_id=task_id,
            agent_id=self.agent_id,
            message=message,
            context=context or "",
        )

        try:
            timing_metadata = {"approval_request_id": request.request_id}
            if ui_metadata:
                timing_metadata.update(ui_metadata)
            await self.track_tool_timing_async(
                task_id, "awaiting_approval", None, None,
                description=message, is_starting=True, metadata=timing_metadata,
            )
        except (RuntimeError, AttributeError, TypeError):
            pass  # best-effort: timing must not block the approval gate

        loop = asyncio.get_running_loop()
        approved = await loop.run_in_executor(
            None, self.approval_manager.wait_for_approval, request.request_id
        )

        duration = time.time() - start_time
        self.wait_times[task_id] = self.wait_times.get(task_id, 0.0) + max(duration, 0.0)
        try:
            end_metadata = {"approval_request_id": request.request_id, "approved": bool(approved)}
            if ui_metadata:
                end_metadata.update(ui_metadata)
            await self.track_tool_timing_async(
                task_id, "awaiting_approval", duration, None,
                description=message, is_starting=False, metadata=end_metadata,
            )
        except (RuntimeError, AttributeError, TypeError):
            pass  # best-effort: timing must not block the approval gate

        if not approved:
            raise ApprovalRejectedError(operation=message)
        return approved

    # ------------------------------------------------------------------ #
    #  Main execution pipeline                                             #
    # ------------------------------------------------------------------ #

    async def _process_message_async(self, message):
        """Process a task message through the full Python-execution pipeline."""
        start_time = time.time()

        task_id, payload = self._unpack_message(message)
        self.wait_times[task_id] = 0.0
        self.logger.start_task(task_id, message, self.agent_id)
        self._init_trace(task_id, payload)

        try:
            memory_context = await self._retrieve_memory(task_id, payload)
            python_code = await self.llm_generate_python(
                payload, task_id=task_id,
                sql_schema=None,
                relevant_connections=None,
                memory_context=memory_context,
            )

            if not python_code or not python_code.strip():
                result = {
                    "success": False,
                    "result": (
                        "Unable to generate code for this task. "
                        "Please ensure all required tools are configured and try again."
                    ),
                    "error": "No executable Python code was generated.",
                    "execution_time": 0,
                }
            else:
                result = await self._execute_code(task_id, payload, python_code)

            await self._finalize_task(task_id, payload, result, start_time)

        except Exception as e:
            self._handle_task_error(task_id, e, start_time)

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _unpack_message(message) -> tuple:
        """Return (task_id, payload) from a raw message."""
        task_id = None
        payload = message
        if isinstance(message, dict) and "task_id" in message and "payload" in message:
            task_id = message["task_id"]
            payload = message["payload"]
        if not task_id:
            task_id = str(uuid.uuid4())
        return task_id, payload

    def _init_trace(self, task_id: str, payload):
        if not self.trace_mode:
            return
        self.current_trace = Trace(
            session_id=task_id,
            task=payload if isinstance(payload, str) else str(payload),
            started_at=datetime.now(),
            trace_mode=self.trace_mode if isinstance(self.trace_mode, str) else "full",
        )
        self.current_trace.add_event("session_start", "task received")

        if self.api_enrichment_info:
            info = self.api_enrichment_info
            self.current_trace.api_enrichment = EnrichmentTrace(
                started_at=datetime.now(),
                duration_ms=info.get("duration_ms", 0),
                model_used=info.get("model", ""),
                endpoints_enriched=info.get("endpoints_enriched", 0),
                cached=info.get("cached", False),
                tokens_input=info.get("tokens_input", 0),
                tokens_output=info.get("tokens_output", 0),
                cost_usd=info.get("cost_usd"),
            )

        if self.trace_callback:
            self.trace_callback(self.current_trace)

    async def _retrieve_memory(self, task_id: str, payload) -> Optional[str]:
        """Run embedding-based memory retrieval. Returns context string or None."""
        if not self.memory:
            return None

        console.info("Step", "Retrieving memories...", task_id=task_id, agent_id=self.agent_id)
        mem_start = time.time()
        mem_start_dt = datetime.now()
        if self.current_trace:
            self.current_trace.add_event("memory_start", "retrieving memory")

        await self.track_tool_timing_async(
            task_id, "memory_retrieval", None, None,
            description="Retrieving memory", is_starting=True,
        )
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
                    context_injected=(
                        memory_context if (memory_context and self.trace_mode == "full") else ""
                    ),
                    embedding_backend="local",
                )
                self.current_trace.add_event("memory_complete", f"{facts_n} facts retrieved")

            await self.track_tool_timing_async(
                task_id, "memory_retrieval", mem_duration, None,
                description="Retrieving memory", is_starting=False,
            )
            console.debug(
                "Memory retrieval",
                f"Retrieved {facts_n} relevant facts ({mem_duration*1000:.0f}ms)",
                task_id=task_id, agent_id=self.agent_id,
            )
            return memory_context
        except (IOError, RuntimeError, ValueError, AttributeError) as mem_err:
            # MemoryRetrievalError — non-critical; task continues without memory context
            mem_duration = time.time() - mem_start
            await self.track_tool_timing_async(
                task_id, "memory_retrieval", mem_duration, None,
                description="Retrieving memory", is_starting=False,
            )
            console.warning(
                "Memory retrieval failed",
                f"{type(mem_err).__name__}: {mem_err}",
                task_id=task_id, agent_id=self.agent_id,
            )
            return None

    async def _execute_code(self, task_id: str, payload, python_code: str) -> dict:
        """Execute generated code in sandbox, with optional verbose display and auto-retry."""
        if self.verbose == "high":
            from rich.panel import Panel
            from rich.syntax import Syntax
            code_syntax = Syntax(python_code, "python", theme="github-dark", line_numbers=True)
            code_panel = Panel(
                code_syntax, title="[bold]Generated Code[/bold]",
                border_style="dim", expand=False,
            )
            console.console.print(code_panel)
            console.console.print()

        from .sandbox import SandboxExecutor
        executor = SandboxExecutor(
            mode=getattr(self, "sandbox_mode", "auto"),
            sandbox_config=getattr(self, "sandbox_config", None),
            workspace_files=getattr(self, "workspace_files", []),
            tool_manager=self.tools,
            task_id=task_id,
            agent_id=self.agent_id,
            light_llm=self.light_llm,
            heavy_llm=self.heavy_llm,
            orchestrator=self,
            vision_model=self.vision_llm,
        )

        if self.current_trace:
            self.current_trace.add_event("exec_start", "sandbox ready")

        exec_start = time.time()
        result = await executor.execute(python_code)
        exec_duration = time.time() - exec_start

        if self.current_trace:
            ex_start_dt = datetime.fromtimestamp(exec_start)
            self.current_trace.execution = ExecutionTrace(
                started_at=ex_start_dt,
                duration_ms=int(exec_duration * 1000),
                code_executed=python_code,
                stdout=result.get("output", ""),
                outcome="success" if result.get("success") else "error",
                error_type=None,
                error_message=result.get("error", None),
                retry_reason=None,
            )
            self.current_trace.add_event(
                "exec_complete", "success" if result.get("success") else "error"
            )

        result = await self._auto_retry(task_id, payload, python_code, result, executor)
        return result

    async def _auto_retry(
        self, task_id: str, payload, python_code: str, result: dict, executor
    ) -> dict:
        """Auto-retry on recoverable execution errors (up to self.retry_count times)."""
        retryable_errors = (
            "TypeError", "KeyError", "NameError", "AttributeError",
            "IndexError", "ValueError", "RuntimeError", "SyntaxError",
        )

        for _ in range(self.retry_count):
            if result.get("success") or not result.get("error"):
                break

            error_msg = result["error"]
            disallowed = ("ERR-TOL-007" in error_msg) or ("Action not allowed" in error_msg)
            if not (disallowed or any(err in error_msg for err in retryable_errors)):
                break

            warning_prefix = ""
            if disallowed:
                warning_prefix = (
                    "WARNING: Generated code attempted a disallowed action. "
                    "Execution was blocked; regenerating with stricter permission constraints."
                )
                console.warning(
                    "Blocked disallowed action", warning_prefix,
                    task_id=task_id, agent_id=self.agent_id,
                )

            console.debug(
                "Auto-retry", f"Retrying after error: {error_msg[:200]}",
                task_id=task_id, agent_id=self.agent_id,
            )

            retry_prompt = self._build_retry_prompt(
                payload, python_code, error_msg, result, executor, disallowed, retryable_errors
            )

            try:
                await self.track_tool_timing_async(
                    task_id, "llm_code_generation", None, self.code_generation_llm,
                    description=self._ui_text("retrying"), is_starting=True,
                )
                retry_llm_start = time.time()
                retry_llm_result = await llm_completion_async(
                    model=self.code_generation_llm,
                    prompt=retry_prompt,
                    temperature=0.0,
                    max_tokens=4000,
                    response_format=None,
                )
                retry_llm_duration = time.time() - retry_llm_start
                await self.track_tool_timing_async(
                    task_id, "llm_code_generation", retry_llm_duration, self.code_generation_llm,
                    description=self._ui_text("retrying"), is_starting=False,
                )
                self.track_tool_usage(task_id, "llm_code_generation", self.code_generation_llm)

                retry_response, retry_token_info = normalize_llm_result(retry_llm_result)
                self._safe_add_tokens(
                    task_id, retry_token_info, self.code_generation_llm,
                    "llm_retry", duration=retry_llm_duration,
                )

                retry_code = parse_python_code(retry_response)
                if not retry_code or not retry_code.strip():
                    continue

                console.debug(
                    "Executing retry code", f"{len(retry_code)} chars",
                    task_id=task_id, agent_id=self.agent_id,
                )

                if self.current_trace and self.current_trace.code_generation:
                    self.current_trace.code_generation.attempt += 1
                    self.current_trace.code_generation.tokens_input += retry_token_info.get("input_tokens", 0)
                    self.current_trace.code_generation.tokens_output += retry_token_info.get("output_tokens", 0)
                    self.current_trace.execution.retry_reason = next(
                        (err for err in retryable_errors if err in error_msg), "Unknown"
                    )
                    self.current_trace.execution.code_executed += "\n# --- RETRY ---\n" + retry_code

                retry_exec_start = time.time()
                retry_result = await executor.execute(retry_code)
                retry_exec_duration = time.time() - retry_exec_start

                if self.current_trace and self.current_trace.execution:
                    self.current_trace.execution.duration_ms += int(retry_exec_duration * 1000)
                    self.current_trace.execution.stdout += "\n" + retry_result.get("output", "")
                    self.current_trace.execution.outcome = (
                        "success" if retry_result.get("success") else "error"
                    )
                    self.current_trace.execution.error_message = retry_result.get("error", None)

                combined_output = self._merge_outputs(
                    result.get("output", ""), retry_result.get("output", ""),
                    retry_result.get("success", False), warning_prefix,
                )
                result = retry_result
                result["output"] = combined_output
                result["execution_time"] = result.get("execution_time", 0) + retry_exec_duration

            except (LLMExecutionError, SandboxExecutionError, RuntimeError, ValueError) as retry_error:
                console.error(
                    "Auto-retry failed", f"{retry_error}",
                    task_id=task_id, agent_id=self.agent_id,
                )
                result["error"] += f"\n\nRetry failed: {str(retry_error)}"

        return result

    def _build_retry_prompt(
        self, payload, python_code: str, error_msg: str, result: dict,
        executor, disallowed: bool, retryable_errors: tuple,
    ) -> str:
        partial_output = result.get("output", "").strip()

        completed_steps = []
        for entry in self.task_tool_timings.get(getattr(executor, "task_id", ""), []):
            if entry.get("duration") is not None and entry.get("tool") not in (
                "llm_code_generation", "prefilter", "sql_schema"
            ):
                desc = entry.get("description", entry.get("tool", "unknown"))
                completed_steps.append(f"  - {desc} ({entry.get('duration', 0):.1f}s)")

        completed_section = (
            "\n\nSTEPS ALREADY COMPLETED SUCCESSFULLY (do NOT repeat these):\n"
            + "\n".join(completed_steps)
            if completed_steps
            else ""
        )
        output_section = (
            f"\n\nPARTIAL OUTPUT (already printed to user):\n{partial_output[:500]}"
            if partial_output
            else ""
        )

        baseline_keys = getattr(executor, "_baseline_keys", set())
        namespace = getattr(executor, "namespace", None) or {}
        user_vars = sorted(
            k for k in namespace
            if k not in baseline_keys and not k.startswith("_")
        )
        state_section = (
            "\n\nPRESERVED VARIABLES (these exist in memory and can be used directly — do NOT re-fetch them):\n"
            + ", ".join(user_vars)
            + "\nAny variable NOT listed above was never assigned and must be fetched/computed."
            if user_vars
            else "\n\nNO variables were preserved from the previous run — start fresh."
        )

        if disallowed:
            instructions = (
                "INSTRUCTIONS: The previous attempt called at least one DISALLOWED action and was blocked. "
                "Regenerate code that uses only permitted actions from the tool APIs shown in prompt context. "
                "Never call blocked actions again. If a required action is not permitted, print a clear message "
                "requesting permission change instead of attempting it. Output Python code ONLY."
            )
        else:
            instructions = (
                "INSTRUCTIONS: Fix the error and generate ONLY the code needed to complete the remaining work. "
                "CRITICAL: If the error occurred inside a loop, you MUST rewrite and execute the ENTIRE loop from scratch "
                "(using the preserved data like fetched lists/results). Do NOT try to resume a loop from the middle. "
                "Steps already completed BEFORE the failure should NOT be repeated — use their results if needed. "
                "Output Python code ONLY."
            )

        return (
            f'TASK: "{payload}"\n\n'
            f"PREVIOUS CODE THAT FAILED:\n```python\n{python_code}\n```\n\n"
            f"ERROR:\n{error_msg}"
            f"{completed_section}{output_section}{state_section}\n\n"
            f"{instructions}"
        )

    @staticmethod
    def _merge_outputs(
        original_output: str, new_output: str, retry_succeeded: bool, warning_prefix: str
    ) -> str:
        if retry_succeeded and new_output.strip():
            combined = new_output
        elif original_output.strip() and new_output.strip():
            combined = original_output.rstrip() + "\n\n--- Auto-Retry Executed ---\n" + new_output.lstrip()
        elif new_output.strip():
            combined = new_output
        else:
            combined = original_output
        if warning_prefix:
            combined = f"WARNING: {warning_prefix}\n\n" + (combined or "")
        return combined

    async def _finalize_task(
        self, task_id: str, payload, result: dict, start_time: float
    ):
        """Compute metrics, emit summaries, store result, fire callbacks."""
        task_duration = time.time() - start_time
        total_wait_time = self.wait_times.get(task_id, 0.0)
        computational_time = max(min(task_duration - total_wait_time, task_duration), 0.0)

        task_data = self.logger.active_tasks.get(task_id, {})
        token_info = {
            "tokens_used": task_data.get("tokens_used", 0),
            "input_tokens": task_data.get("input_tokens", 0),
            "output_tokens": task_data.get("output_tokens", 0),
            "llm_calls": task_data.get("llm_calls", 0),
            "total_cost_usd": (
                round(task_data.get("total_cost_usd"), 8)
                if task_data.get("total_cost_usd") is not None
                else None
            ),
            "pricing_path": task_data.get("pricing_path"),
        }
        llm_breakdown = task_data.get("llm_breakdown", [])

        self._log_llm_summary(task_id, token_info, llm_breakdown)
        tool_entries = self.task_tool_timings.get(task_id, [])
        completed_tools = self._log_timing_summary(
            task_id, tool_entries, task_duration, computational_time
        )
        self._update_trace_tool_calls(task_id, completed_tools)

        if self.verbose == "high":
            self._print_verbose_timeline(task_id, completed_tools, llm_breakdown, task_duration)

        self._update_trace_costs(task_id, token_info, llm_breakdown)

        final_message, task_status = self._build_final_message(result)

        status_label = task_status.upper()
        console.info(status_label, "Task has being completed", task_id=task_id, agent_id=self.agent_id)

        tools_used = [
            entry.get("tool") if isinstance(entry, dict) else str(entry)
            for entry in self.get_tools_used(task_id)
        ]
        console.task_summary(
            task_id, task_duration, token_info, "completed", final_message,
            computational_time, wait_time=total_wait_time, agent_id=self.agent_id,
            task_status=task_status, tools=tools_used, llm_config=self.llm_config,
        )

        self.logger.complete_task(task_id, task_status, computational_time)
        self.task_results[task_id] = {
            "status": task_status,
            "completed": result.get("success", False),
            "final_message": final_message,
            "duration": task_duration,
            "compute_time": computational_time,
            "tokens_used": token_info.get("tokens_used", 0),
            "cost_usd": token_info.get("total_cost_usd"),
            "trace": self.current_trace,
            "output_files": result.get("output_files", {}),
        }

        if self.current_trace:
            self.current_trace.ended_at = datetime.now()
            self.current_trace.outcome = "success" if result.get("success", False) else "failed"
            self.current_trace.add_event("session_end", f"outcome: {self.current_trace.outcome}")

        if self.on_task_complete and task_status == "success":
            try:
                self.on_task_complete(task_id, final_message)
            except (RuntimeError, TypeError, AttributeError):
                pass  # best-effort: callback errors must not fail task delivery

        self._cleanup_task_state(task_id)

    # ---- finalize helpers ----------------------------------------------

    @staticmethod
    def _build_final_message(result: dict) -> tuple:
        """Return (final_message, task_status)."""
        if result.get("success"):
            output = (result.get("output") or "").strip()
            result_value = (result.get("result") or "").strip()
            if output and output != result_value:
                msg = output
            elif result_value and result_value != output:
                msg = result_value
            elif output:
                msg = output
            elif result_value:
                msg = result_value
            else:
                msg = "Task completed successfully"
            return msg, "success"

        error_msg = result.get("error", "Unknown error")
        output_msg = result.get("output", "")
        if "Tool not found" in error_msg or "tool" in error_msg.lower():
            msg = (
                f"Task failed: {error_msg}\n\nTip: Make sure all required tools "
                "(gmail, files, sheets, llm) are configured for this agent."
            )
        elif "No Python code generated" in error_msg or "Unable to generate code" in error_msg:
            msg = (
                f"Task failed: {error_msg}\n\nTip: The task may require specific tools. "
                "Ensure gmail, files, sheets, and llm tools are available."
            )
        elif output_msg and output_msg.strip():
            msg = f"Task failed: {error_msg}\n\nOutput:\n{output_msg}"
        else:
            msg = f"Task failed: {error_msg}"
        return msg, "error"

    def _log_llm_summary(self, task_id: str, token_info: dict, llm_breakdown: list):
        if not llm_breakdown:
            return
        summary_lines = ["LLM Call Summary:"]
        for i, call in enumerate(llm_breakdown, 1):
            model = call.get("model", "unknown")
            in_t = call.get("input_tokens", 0)
            out_t = call.get("output_tokens", 0)
            cost = call.get("cost_usd")
            fn = call.get("function_name", "unknown")
            dur = call.get("duration")
            dur_str = f" in {dur:.2f}s" if dur is not None else ""
            cost_str = f"${cost:.6f}" if cost is not None else "None"
            summary_lines.append(f"  {i}. {fn} ({model}){dur_str}: {in_t} in, {out_t} out | {cost_str}")
        total_dur = sum(c.get("duration") or 0.0 for c in llm_breakdown)
        total_dur_str = f" in {total_dur:.2f}s" if total_dur > 0 else ""
        tot_cost = token_info.get("total_cost_usd")
        tot_cost_str = f"${tot_cost:.6f}" if tot_cost is not None else "None"
        summary_lines.append(
            f"Total: {token_info['llm_calls']} calls{total_dur_str}, "
            f"{token_info['input_tokens']} in, {token_info['output_tokens']} out, {tot_cost_str}"
        )
        console.debug("LLM Calls Summary", "\n".join(summary_lines), task_id=task_id, agent_id=self.agent_id)

        if self.current_trace and self.current_trace.execution:
            reserved = {"prefilter", "llm_connection_filtering", "llm_rag_retrieval", "llm_code_generation", "llm_retry"}
            exec_calls = [c for c in llm_breakdown if c.get("function_name") not in reserved]
            self.current_trace.execution.tokens_input = sum(c.get("input_tokens", 0) for c in exec_calls)
            self.current_trace.execution.tokens_output = sum(c.get("output_tokens", 0) for c in exec_calls)

    def _log_timing_summary(
        self, task_id: str, tool_entries: list, task_duration: float, computational_time: float
    ) -> list:
        completed_tools = [e for e in tool_entries if e.get("duration") is not None]
        if not completed_tools:
            return completed_tools
        timing_lines = ["Task Phases Timing Summary:"]
        for i, entry in enumerate(completed_tools, 1):
            tool_n = entry.get("tool", "unknown")
            desc = entry.get("description", "")
            dur = entry.get("duration", 0.0)
            desc_str = f" - {desc}" if desc else ""
            is_waiting = isinstance(tool_n, str) and (
                tool_n == "awaiting_approval" or tool_n.startswith("awaiting_")
            )
            perc_base = task_duration if is_waiting else computational_time
            perc = (dur / perc_base * 100) if perc_base > 0 else 0
            timing_lines.append(f"  {i}. {tool_n}{desc_str}: {dur:.2f}s ({perc:.1f}%)")
        console.debug("Task Timing Summary", "\n".join(timing_lines), task_id=task_id, agent_id=self.agent_id)
        return completed_tools

    def _update_trace_tool_calls(self, task_id: str, completed_tools: list):
        if not self.current_trace:
            return
        for entry in completed_tools:
            tool_n = entry.get("tool", "unknown")
            if tool_n in ("llm_code_generation", "prefilter", "memory_retrieval") or tool_n.startswith("llm_"):
                continue
            meta = entry.get("ui_metadata") or {}
            args = meta.get("_tool_trace_args", {})
            action = meta.get("_tool_action", "")
            dur = entry.get("duration", 0.0)
            start_dt = datetime.fromtimestamp(entry.get("timestamp", time.time()))
            dur_ms = int(dur * 1000)
            tc = ToolCallTrace(
                tool_name=f"{tool_n}.{action}" if action else tool_n,
                arguments=args,
                started_at=start_dt,
                duration_ms=dur_ms,
                outcome="success" if entry.get("status") == "success" else "error",
                result=meta.get("_tool_trace_result", ""),
                error=meta.get("_tool_trace_error", None),
            )
            self.current_trace.tool_calls.append(tc)
            arg_strs = [
                f"{k}={repr(v) if isinstance(v, str) else str(v)}"
                for k, v in (args or {}).items()
            ]
            arg_summary = ", ".join(arg_strs)
            if len(arg_summary) > 25:
                arg_summary = arg_summary[:22] + "..."
            self.current_trace.add_event("tool_call_start", f"{tc.tool_name}({arg_summary})", t=start_dt)
            end_dt = start_dt + timedelta(milliseconds=dur_ms)
            self.current_trace.add_event("tool_call_end", f"{tc.tool_name} → {tc.outcome} {dur_ms}ms", t=end_dt)

    def _update_trace_costs(self, task_id: str, token_info: dict, llm_breakdown: list):
        if not self.current_trace:
            return
        task_cost = token_info.get("total_cost_usd")
        enrichment_cost = 0.0
        if self.current_trace.api_enrichment and self.current_trace.api_enrichment.cost_usd:
            enrichment_cost = self.current_trace.api_enrichment.cost_usd
        if task_cost is not None:
            self.current_trace.total_cost_usd = round(task_cost + enrichment_cost, 8)
        elif enrichment_cost > 0:
            self.current_trace.total_cost_usd = round(enrichment_cost, 8)
        else:
            self.current_trace.total_cost_usd = None
        self.current_trace.pricing_path = token_info.get("pricing_path", "") or ""

        cost_by_fn: Dict[str, float] = {}
        for call in llm_breakdown:
            fn = call.get("function_name", "unknown")
            c_val = call.get("cost_usd")
            if c_val is not None:
                cost_by_fn[fn] = cost_by_fn.get(fn, 0.0) + float(c_val)
        self.current_trace.cost_by_function = {k: round(v, 8) for k, v in cost_by_fn.items()}

        def _sum(*fns):
            costs = [cost_by_fn[f] for f in fns if f in cost_by_fn]
            return round(sum(costs), 8) if costs else None

        if self.current_trace.prefilter:
            self.current_trace.prefilter.cost_usd = _sum(
                "prefilter", "llm_connection_filtering", "llm_rag_retrieval"
            )
        if self.current_trace.code_generation:
            self.current_trace.code_generation.cost_usd = _sum("llm_code_generation", "llm_retry")
        if self.current_trace.execution:
            reserved = {"prefilter", "llm_connection_filtering", "llm_rag_retrieval", "llm_code_generation", "llm_retry"}
            self.current_trace.execution.cost_usd = _sum(
                *[fn for fn in cost_by_fn if fn not in reserved]
            )

    def _print_verbose_timeline(
        self, task_id: str, completed_tools: list, llm_breakdown: list, task_duration: float
    ):
        from rich.table import Table
        import rich.box as rich_box
        from cortex._engine.core.python_executor import _parallel_group_descs

        def _ts(raw):
            if isinstance(raw, (int, float)):
                return float(raw)
            if isinstance(raw, str):
                try:
                    return datetime.fromisoformat(raw).timestamp()
                except (ValueError, OverflowError):
                    return 0.0
            return 0.0

        duplicated = {"prefilter", "llm_code_generation", "llm_connection_filtering", "llm_rag_retrieval"}
        hidden_fn = {"llm", "web_search", "gmail_dsl_parsing"}
        llm_fn_names = {c.get("function_name", "") for c in llm_breakdown if isinstance(c, dict)} - hidden_fn

        _LLM_LABELS = {
            "llm_code_generation": "Planning",
            "prefilter": "Prefilter",
            "llm_connection_filtering": "Connection filter",
            "llm_rag_retrieval": "RAG retrieval",
        }

        timeline_items = []

        for call in llm_breakdown:
            fn = call.get("function_name", "unknown")
            if fn in hidden_fn:
                continue
            label = _LLM_LABELS.get(fn, fn)
            model = call.get("model", "")
            timeline_items.append({
                "type": "llm", "timestamp": _ts(call.get("timestamp", 0)),
                "tool": "llm", "description": label,
                "params": f"model={model}" if model else "",
                "duration": call.get("duration", 0) or 0,
                "wait_time": 0, "status": "ok",
            })

        seen_group_headers: set = set()
        for entry in completed_tools:
            tn = entry.get("tool", "unknown")
            if tn in duplicated or tn in llm_fn_names or tn == "awaiting_approval":
                continue
            meta = entry.get("ui_metadata") or {}
            args = meta.get("_tool_trace_args") or {}
            action = meta.get("_tool_action") or ""

            group_id = meta.get("parallel_group_id")
            if group_id and group_id in _parallel_group_descs and group_id not in seen_group_headers:
                seen_group_headers.add(group_id)
                timeline_items.append({
                    "type": "group_header", "timestamp": _ts(entry.get("timestamp", 0)) - 0.0001,
                    "tool": "⟳ parallel", "description": _parallel_group_descs[group_id],
                    "params": "", "duration": 0, "wait_time": 0, "status": "ok",
                })

            param_parts = []
            if action:
                param_parts.append(f"action={action}")
            for k, v in list(args.items())[:6]:
                v_s = str(v)
                if len(v_s) > 80:
                    v_s = v_s[:77] + "…"
                param_parts.append(f"{k}={v_s}")

            timeline_items.append({
                "type": "tool", "timestamp": _ts(entry.get("timestamp", 0)),
                "tool": tn, "description": entry.get("description", ""),
                "params": "  ".join(param_parts),
                "duration": entry.get("duration", 0) or 0,
                "wait_time": entry.get("wait_time", 0) or 0,
                "status": entry.get("status", "unknown"),
            })

        timeline_items.sort(key=lambda x: x["timestamp"])

        table = Table(
            title="[bold]Execution Timeline[/bold]",
            show_header=True, header_style="bold",
            box=rich_box.SIMPLE_HEAD, show_lines=True, expand=True, padding=(0, 1),
        )
        table.add_column("Description", ratio=4)
        table.add_column("Tool", min_width=12, style="bright_yellow", no_wrap=True)
        table.add_column("Params", ratio=5, style="dim")
        table.add_column("Duration", min_width=8, no_wrap=True)

        for item in timeline_items:
            dur = item["duration"]
            dur_str = f"{dur:.2f}s" if dur > 0 else "[dim]—[/dim]"
            if item["type"] == "group_header":
                table.add_row(
                    f"[bold cyan]{item['description']}[/bold cyan]",
                    f"[cyan]{item['tool']}[/cyan]", "", "",
                )
                continue
            icon = (
                "[dim]~[/dim]" if item["type"] == "llm"
                else ("[green]✓[/green]" if item["status"] in ("ok", "success") else "[red]✗[/red]")
            )
            table.add_row(
                item["description"] or "[dim]—[/dim]",
                f"{icon} {item['tool']}",
                item["params"] or "[dim]—[/dim]",
                dur_str,
            )

        console.console.print(table)
        console.console.print()

    def _cleanup_task_state(self, task_id: str):
        for active_key in list(self._active_phase_logs.keys()):
            if active_key[0] == task_id:
                self._active_phase_logs.pop(active_key, None)
        self.wait_times.pop(task_id, None)
        self._cleanup_wait_times_if_needed()

    def _handle_task_error(self, task_id: str, e: Exception, start_time: float):
        elapsed = time.time() - start_time
        total_wait_time = self.wait_times.get(task_id, 0.0)
        comp_time = max(elapsed - total_wait_time, 0.0)
        console.print_exception(e, title="Task Execution Failed")
        if self.logger:
            self.logger.complete_task(task_id, "error", comp_time)
        self.task_results[task_id] = {
            "status": "error",
            "completed": False,
            "final_message": f"Task failed: {type(e).__name__}: {str(e)}",
            "duration": elapsed,
            "compute_time": comp_time,
            "tokens_used": 0,
            "trace": self.current_trace,
        }
        self._cleanup_task_state(task_id)
