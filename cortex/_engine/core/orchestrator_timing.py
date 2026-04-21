"""
OrchestratorTimingMixin

Tool-usage tracking, per-phase timing entries, and console progress output.
Intended to be mixed into the Orchestrator class — shares `self`.
"""

from typing import Any, Dict, Optional
import asyncio, inspect, time

from ..utils.console import console


class OrchestratorTimingMixin:
    """Mixin that adds timing-tracking and phase-progress display to the Orchestrator."""

    MAX_WAIT_TIMES_ENTRIES = 100

    _VISIBLE_PHASES = {
        "memory_retrieval": "Retrieving memory",
        "prefilter": "Analyzing tools",
        "sql_schema": "Loading schema",
        "llm_code_generation": "Planning",
    }

    # ------------------------------------------------------------------ #
    #  UI helpers                                                          #
    # ------------------------------------------------------------------ #

    def _ui_text(self, key: str) -> str:
        texts = {
            "planning": "Planning",
            "retrying": "Retrying",
            "analyzing_connections": "Analyzing connections",
            "retrieving_knowledge": "Retrieving knowledge",
            "fetching_schema": "Fetching database schema",
        }
        return texts.get(key, key)

    # ------------------------------------------------------------------ #
    #  Tool-usage ledger                                                   #
    # ------------------------------------------------------------------ #

    def track_tool_usage(self, task_id: str, tool_name: str, model: str = None):
        """Track which tools are used for each task (deduplicates by tool+model)."""
        if not tool_name:
            return
        entry = {"tool": tool_name, "model": model}
        if task_id not in self.task_tools_used:
            self.task_tools_used[task_id] = []
        task_entries = self.task_tools_used[task_id]
        for existing in task_entries:
            if (
                isinstance(existing, dict)
                and existing.get("tool") == entry["tool"]
                and existing.get("model") == entry["model"]
            ):
                return
        task_entries.append(entry)

    def get_tools_used(self, task_id: str) -> list:
        tools = self.task_tools_used.get(task_id, [])
        return [entry.copy() if isinstance(entry, dict) else entry for entry in tools]

    def get_tool_timings(self, task_id: str) -> list:
        return self.task_tool_timings.get(task_id, [])

    # ------------------------------------------------------------------ #
    #  Timing entries                                                      #
    # ------------------------------------------------------------------ #

    async def track_tool_timing_async(
        self,
        task_id: str,
        tool_name: str,
        duration: float,
        model: str = None,
        description: str = None,
        is_starting: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        wait_time: float = 0.0,
    ):
        """Async version — properly awaits the timing callback."""
        timing_entry = self._track_tool_timing_internal(
            task_id, tool_name, duration, model, description, is_starting, metadata, wait_time=wait_time
        )
        if timing_entry and self.tool_timing_callback:
            try:
                if inspect.iscoroutinefunction(self.tool_timing_callback):
                    await self.tool_timing_callback(task_id, timing_entry)
                else:
                    self.tool_timing_callback(task_id, timing_entry)
            except (RuntimeError, TypeError, AttributeError) as e:
                print(f"[TRACK_TIMING_ASYNC] Callback error: {e}")  # best-effort

    def track_tool_timing(
        self,
        task_id: str,
        tool_name: str,
        duration: float,
        model: str = None,
        description: str = None,
        is_starting: bool = False,
    ):
        """Sync version — schedules async callback via create_task."""
        timing_entry = self._track_tool_timing_internal(
            task_id, tool_name, duration, model, description, is_starting
        )
        if timing_entry and self.tool_timing_callback:
            try:
                if inspect.iscoroutinefunction(self.tool_timing_callback):
                    asyncio.create_task(self.tool_timing_callback(task_id, timing_entry))
                else:
                    self.tool_timing_callback(task_id, timing_entry)
            except (RuntimeError, TypeError, AttributeError) as e:
                print(f"[TRACK_TIMING] Callback error: {e}")  # best-effort

    def _track_tool_timing_internal(
        self,
        task_id: str,
        tool_name: str,
        duration: float,
        model: str = None,
        description: str = None,
        is_starting: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        wait_time: float = 0.0,
    ):
        """Create or update a timing entry. Returns the entry if a callback should fire."""
        if task_id not in self.task_tool_timings:
            self.task_tool_timings[task_id] = []

        current_time = time.time()
        existing_entries = self.task_tool_timings[task_id]
        normalized_desc = (description or "").strip().lower()

        # ── Completion: find and update the matching "starting" entry ────────
        if not is_starting and duration is not None:
            for existing in reversed(existing_entries[-20:]):
                if not isinstance(existing, dict):
                    continue
                if (
                    existing.get("tool") == tool_name
                    and (existing.get("description") or "").strip().lower() == normalized_desc
                    and (existing.get("duration") is None or existing.get("duration") == 0)
                ):
                    existing["duration"] = duration
                    existing["status"] = "success"
                    if model:
                        existing["model"] = model
                    if metadata:
                        existing["ui_metadata"] = metadata
                    if wait_time > 0.0:
                        existing["wait_time"] = wait_time
                    self._emit_phase_progress(
                        task_id, tool_name, description,
                        is_starting=False, duration=duration,
                        metadata=existing.get("ui_metadata"), model=model,
                    )
                    return existing

        # ── Starting entry (or no match found for completion) ────────────────
        if is_starting or duration is None:
            timing_entry = {
                "tool": tool_name,
                "duration": None,
                "timestamp": current_time,
                "status": "running",
            }
            if description:
                timing_entry["description"] = description
            if model:
                timing_entry["model"] = model
            if metadata:
                timing_entry["ui_metadata"] = metadata
            self.task_tool_timings[task_id].append(timing_entry)
            self._emit_phase_progress(
                task_id, tool_name, description,
                is_starting=True, duration=None, metadata=metadata, model=model,
            )
            return timing_entry

        # ── Orphan completion: deduplicate then create ───────────────────────
        for existing in reversed(existing_entries[-10:]):
            if not isinstance(existing, dict):
                continue
            if (
                existing.get("tool") == tool_name
                and (existing.get("description") or "").strip().lower() == normalized_desc
                and abs(existing.get("timestamp", 0) - current_time) < 1.0
                and existing.get("duration") is not None
                and abs(existing.get("duration", 0) - duration) < max(duration * 0.15, 0.15)
            ):
                if abs(existing.get("duration", 0) - duration) > 0.1:
                    existing["duration"] = duration
                if model and not existing.get("model"):
                    existing["model"] = model
                return None  # Duplicate — suppress callback

        timing_entry = {
            "tool": tool_name,
            "duration": duration,
            "timestamp": current_time,
            "model": model,
            "status": "success",
        }
        if description:
            timing_entry["description"] = description
        if metadata:
            timing_entry["ui_metadata"] = metadata
        if wait_time > 0.0:
            timing_entry["wait_time"] = wait_time
        self.task_tool_timings[task_id].append(timing_entry)
        self._emit_phase_progress(
            task_id, tool_name, description,
            is_starting=False, duration=duration, metadata=metadata, model=model,
        )
        return timing_entry

    # ------------------------------------------------------------------ #
    #  Console progress output                                             #
    # ------------------------------------------------------------------ #

    def _emit_phase_progress(
        self,
        task_id: str,
        tool_name: str,
        description: Optional[str],
        is_starting: bool,
        duration: Optional[float],
        metadata: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ):
        """Emit a user-facing log line for every tool/phase call."""
        if tool_name == "awaiting_approval":
            return

        # Planning spinner is handled specially
        if tool_name == "llm_code_generation":
            loading_key = f"{task_id}:llm_code_generation"
            if is_starting:
                if loading_key not in self._active_phase_logs:
                    self._active_phase_logs[loading_key] = True
                    console.loading_start(
                        "[white]Planning[/white]  [bright_yellow]llm[/bright_yellow] [grey50]...[/grey50]",
                        loading_key,
                    )
            else:
                self._active_phase_logs.pop(loading_key, None)
                console.loading_stop(loading_key)
                if duration is not None:
                    console.tool("[white]Planning[/white]  [bright_yellow]llm[/bright_yellow]", None, task_id=task_id)
            return

        is_internal = tool_name in self._VISIBLE_PHASES
        label = description or self._VISIBLE_PHASES.get(tool_name, tool_name)

        if not is_internal and not description:
            return

        tool_color = "bright_yellow" if not is_internal else "magenta"
        formatted_label = f"[white]{label}[/white]  [{tool_color}]{tool_name}[/{tool_color}]"

        if is_internal:
            key = (task_id, tool_name)
            loading_key = f"{task_id}:{tool_name}"
        else:
            desc_norm = (label or "").strip().lower()
            key = (task_id, tool_name, desc_norm)
            loading_key = f"{task_id}:{tool_name}:{desc_norm}"

        if is_starting:
            if key in self._active_phase_logs:
                return
            self._active_phase_logs[key] = True
            console.loading_start(f"{formatted_label} [grey50]...[/grey50]", loading_key)
            return

        # ── Completion ───────────────────────────────────────────────────────
        self._active_phase_logs.pop(key, None)
        console.loading_stop(loading_key)

        if duration is None:
            return

        args = dict((metadata or {}).get("_tool_trace_args") or {})
        action = (metadata or {}).get("_tool_action") or ""

        if model and "model" not in args:
            args["model"] = model

        noisy_keys = {"prompt", "desc", "ui_metadata", "metadata", "content", "body", "html", "text"}
        preferred_keys = (
            "query", "max_results", "model", "max_tokens", "temperature",
            "sql", "range", "sheet_name", "spreadsheet_id", "to", "subject",
        )

        compact_items = []
        for k in preferred_keys:
            if k in args and k not in noisy_keys:
                compact_items.append((k, args[k]))
        for k, v in args.items():
            if k in noisy_keys or any(k == x for x, _ in compact_items):
                continue
            compact_items.append((k, v))

        param_parts = []
        if action and not is_internal:
            param_parts.append(f"action={action}")
        for k, v in compact_items[:2]:
            v_str = str(v).replace("\n", " ").strip()
            if len(v_str) > 42:
                v_str = v_str[:39] + "…"
            param_parts.append(f"{k}={v_str}")

        params_str = "  ".join(param_parts)
        tool_color = "bright_yellow" if not is_internal else "magenta"
        msg = f"[white]{label}[/white]  [{tool_color}]{tool_name}[/{tool_color}]"
        console.tool(msg, params_str or None, task_id=task_id)
