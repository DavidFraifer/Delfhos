from dataclasses import dataclass, field

@dataclass
class TokenCount:
    """Represents split tracking of input and output tokens."""
    input: int = 0
    output: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output

    def add(self, token_info: dict):
        """Safely increments counts from an LLM token_info dictionary."""
        if not token_info:
            return
        self.input += token_info.get("input_tokens", 0)
        self.output += token_info.get("output_tokens", 0)

    def __str__(self) -> str:
        return f"{self.total} (in: {self.input}, out: {self.output})"

@dataclass
class TokenUsage:
    """Tracks token consumption across different agent lifecycle phases."""
    task: TokenCount = field(default_factory=TokenCount)
    summarizer: TokenCount = field(default_factory=TokenCount)
    extractor: TokenCount = field(default_factory=TokenCount)

    @property
    def total(self) -> int:
        return self.task.total + self.summarizer.total + self.extractor.total

from typing import Optional, Any, Dict, List

@dataclass
class Response:
    """Unified response object for agent run execution."""
    text: str
    status: bool
    error: Optional[str] = None
    cost_usd: Optional[float] = None
    duration_ms: int = 0
    trace: Any = None
    files: Dict[str, str] = field(default_factory=dict)


@dataclass
class StreamEvent:
    """One item in a request's unified live timeline.

    Unifies the existing trace channels into a single ordered stream:
      - kind="phase": internal pipeline step (planning, prefilter, schema, memory)
      - kind="tool":  a tool call (label is the `desc=` or tool name)
      - kind="say":   a line the agent printed (its spoken "voice")
    """
    kind: str          # "phase" | "tool" | "say"
    label: str
    status: str        # "running" | "success" | "error"
    started_at: float  # unix epoch seconds
    duration_ms: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
        }


@dataclass
class StreamSnapshot:
    """A point-in-time view of a running (or finished) request.

    Returned by ``agent.poll(task_id)``. Carries the request state, the unified
    live timeline (``events``), the output produced so far, and — once terminal —
    the final result, cost, tokens, files, and full ``trace``.
    """
    task_id: str
    state: str                 # "queued" | "running" | "done" | "error"
    task: str = ""
    elapsed_ms: int = 0
    events: List[StreamEvent] = field(default_factory=list)
    output_so_far: str = ""
    result: Optional[str] = None
    error: Optional[str] = None
    cost_usd: Optional[float] = None
    tokens_used: Optional[int] = None
    files: Dict[str, str] = field(default_factory=dict)
    trace: Any = None

    @property
    def is_terminal(self) -> bool:
        return self.state in ("done", "error")

    def to_dict(self) -> dict:
        """JSON-serializable view (used by the HTTP server)."""
        return {
            "task_id": self.task_id,
            "state": self.state,
            "task": self.task,
            "elapsed_ms": self.elapsed_ms,
            "events": [e.to_dict() for e in self.events],
            "output_so_far": self.output_so_far,
            "result": self.result,
            "error": self.error,
            "cost_usd": self.cost_usd,
            "tokens_used": self.tokens_used,
            "files": self.files,
            "is_terminal": self.is_terminal,
        }
