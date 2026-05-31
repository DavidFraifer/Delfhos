"""
OrchestratorStreamingMixin

Builds a single, unified StreamSnapshot for a request at any point in its
lifecycle — queued, running, or finished. Mixed into the Orchestrator alongside
the timing/scheduler/codegen mixins.

The "clever unification": while a task runs, the live source of truth is the
tool-timing ledger (`task_tool_timings`) plus the agent's printed narration
(`current_trace.utterances`); once it finishes, `task_results` holds the full
outcome and the complete `Trace`. This mixin folds whichever is available into
one ordered `events` list (phase / tool / say) plus the output produced so far.
"""

from datetime import datetime
import time

from ..types import StreamEvent, StreamSnapshot


class OrchestratorStreamingMixin:
    """Adds get_task_snapshot() — a pollable, JSON-friendly view of a request."""

    # Internal pipeline steps that should render as kind="phase" (not a tool).
    _PHASE_LABELS = {
        "memory_retrieval": "Retrieving memory",
        "prefilter": "Analyzing tools",
        "sql_schema": "Loading schema",
        "llm_code_generation": "Planning",
        "awaiting_approval": "Awaiting approval",
    }

    def _is_phase(self, tool_name: str) -> bool:
        return tool_name in self._PHASE_LABELS or tool_name.startswith("llm_")

    def _timing_to_event(self, entry: dict) -> StreamEvent:
        tool_name = entry.get("tool", "unknown")
        duration = entry.get("duration")
        raw_status = entry.get("status", "running")
        status = raw_status if raw_status in ("running", "success", "error") else "running"
        if self._is_phase(tool_name):
            kind = "phase"
            label = self._PHASE_LABELS.get(tool_name, tool_name)
        else:
            kind = "tool"
            label = entry.get("description") or tool_name
        return StreamEvent(
            kind=kind,
            label=label,
            status=status,
            started_at=float(entry.get("timestamp", time.time())),
            duration_ms=int(duration * 1000) if duration else None,
        )

    def _utterance_events(self, trace) -> list:
        if not trace or not getattr(trace, "utterances", None):
            return []
        base = trace.started_at.timestamp()
        return [
            StreamEvent(
                kind="say",
                label=utt.text,
                status="success",
                started_at=base + (utt.t_ms / 1000.0),
                duration_ms=None,
            )
            for utt in trace.utterances
        ]

    def _live_events(self, task_id: str, trace) -> list:
        events = [
            self._timing_to_event(e)
            for e in self.task_tool_timings.get(task_id, [])
            if isinstance(e, dict)
        ]
        events.extend(self._utterance_events(trace))
        events.sort(key=lambda e: e.started_at)
        return events

    def get_task_snapshot(self, task_id: str) -> StreamSnapshot:
        """Return a point-in-time StreamSnapshot for the given task id."""
        result = self.task_results.get(task_id)

        # ── Terminal: build from the stored result + full trace ──────────────
        if result is not None:
            trace = result.get("trace")
            completed = result.get("completed", False)
            task_text = getattr(trace, "task", "") if trace else ""
            output = self.task_live_output.get(task_id) or result.get("final_message", "")
            return StreamSnapshot(
                task_id=task_id,
                state="done" if completed else "error",
                task=task_text,
                elapsed_ms=int(result.get("duration", 0) * 1000),
                events=self._live_events(task_id, trace),
                output_so_far=output,
                result=result.get("final_message") if completed else None,
                error=None if completed else result.get("final_message"),
                cost_usd=result.get("cost_usd"),
                files=result.get("output_files", {}) or {},
                trace=trace,
            )

        # ── Live or queued: build from the in-flight trace + timing ledger ───
        trace = self.current_trace
        is_current = bool(trace and getattr(trace, "session_id", None) == task_id)
        has_activity = is_current or bool(self.task_tool_timings.get(task_id))

        if not has_activity:
            return StreamSnapshot(task_id=task_id, state="queued")

        elapsed_ms = 0
        task_text = ""
        if is_current:
            elapsed_ms = int((datetime.now() - trace.started_at).total_seconds() * 1000)
            task_text = getattr(trace, "task", "")

        return StreamSnapshot(
            task_id=task_id,
            state="running",
            task=task_text,
            elapsed_ms=elapsed_ms,
            events=self._live_events(task_id, trace if is_current else None),
            output_so_far=self.task_live_output.get(task_id, ""),
            trace=trace if is_current else None,
        )
