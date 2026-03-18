import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Union, Any, Dict

@dataclass
class TokenUsage:
    task: int = 0
    execution: int = 0
    prefilter: int = 0
    summarizer: int = 0
    extractor: int = 0

    @property
    def total(self) -> int:
        return self.task + self.execution + self.prefilter + self.summarizer + self.extractor

    @property
    def overhead_percent(self) -> float:
        if self.total == 0:
            return 0.0
        overhead = self.summarizer + self.extractor
        return round((overhead / self.total) * 100, 1)

@dataclass
class TimelineEvent:
    t_ms: int
    event: str
    detail: str

@dataclass
class MemoryRetrievalTrace:
    started_at: datetime
    duration_ms: int = 0
    query: str = ""
    facts_retrieved: int = 0
    context_injected: str = ""
    embedding_backend: str = ""

@dataclass
class PrefilterTrace:
    started_at: datetime
    duration_ms: int = 0
    model_used: str = ""
    tools_available: int = 0
    tools_selected: List[str] = field(default_factory=list)
    tools_rejected: List[str] = field(default_factory=list)
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: Optional[float] = None
    ran_parallel_with: Optional[str] = None

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output

@dataclass
class MergeTrace:
    tools_added_by_memory: List[str] = field(default_factory=list)
    final_tools: List[str] = field(default_factory=list)

@dataclass
class CodeGenTrace:
    started_at: datetime
    duration_ms: int = 0
    model_used: str = ""
    system_prompt: str = ""
    code_generated: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: Optional[float] = None
    attempt: int = 1

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output

@dataclass
class ToolCallTrace:
    tool_name: str
    arguments: Dict[str, Any]
    started_at: datetime
    duration_ms: int = 0
    outcome: str = "success"  # success | error
    result: str = ""
    error: Optional[str] = None

@dataclass
class ExecutionTrace:
    started_at: datetime
    duration_ms: int = 0
    code_executed: str = ""
    stdout: str = ""
    outcome: str = "success"  # success | error
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    traceback: Optional[str] = None
    retry_reason: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: Optional[float] = None

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output

@dataclass
class ChatCompressionTrace:
    triggered_at: datetime
    model_used: str = ""
    messages_before: int = 0
    messages_after: int = 0
    summary_generated: str = ""
    duration_ms: int = 0
    tokens_input: int = 0
    tokens_output: int = 0

    @property
    def tokens_used(self) -> int:
        return self.tokens_input + self.tokens_output

@dataclass
class SessionCloseTrace:
    started_at: datetime
    duration_ms: int = 0
    model_used: str = ""
    combined: bool = False
    summary_generated: str = ""
    facts_extracted: int = 0
    facts_written: int = 0
    facts_deduplicated: int = 0
    tokens_input: int = 0
    tokens_output: int = 0

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output

@dataclass
class Trace:
    session_id: str
    task: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    outcome: str = "success"  # success | failed | partial
    trace_mode: str = "full"  # full | minimal

    # Layers
    memory_retrieval: Optional[MemoryRetrievalTrace] = None
    prefilter: Optional[PrefilterTrace] = None
    merge: Optional[MergeTrace] = None
    code_generation: Optional[CodeGenTrace] = None
    execution: Optional[ExecutionTrace] = None
    tool_calls: List[ToolCallTrace] = field(default_factory=list)
    chat_compression: Optional[ChatCompressionTrace] = None
    session_close: Optional[SessionCloseTrace] = None
    total_cost_usd: Optional[float] = None
    pricing_path: str = ""
    cost_by_function: Dict[str, float] = field(default_factory=dict)

    _timeline_events: List[TimelineEvent] = field(default_factory=list, repr=False)
    def __str__(self):
        return self.summary()
    @property
    def duration_ms(self) -> int:
        if not self.ended_at:
            return 0
        return int((self.ended_at - self.started_at).total_seconds() * 1000)

    @property
    def usage(self) -> TokenUsage:
        return TokenUsage(
            task=self.code_generation.tokens_total if self.code_generation else 0,
            execution=self.execution.tokens_total if self.execution else 0,
            prefilter=self.prefilter.tokens_total if self.prefilter else 0,
            summarizer=self.chat_compression.tokens_used if self.chat_compression else 0,
            extractor=self.session_close.tokens_total if self.session_close else 0,
        )

    def add_event(self, event: str, detail: str, t: Optional[datetime] = None):
        if not t:
            t = datetime.now()
        t_ms = int((t - self.started_at).total_seconds() * 1000)
        self._timeline_events.append(TimelineEvent(t_ms=t_ms, event=event, detail=detail))

    @property
    def timeline(self) -> List[TimelineEvent]:
        # Return sorted by timestamp
        return sorted(self._timeline_events, key=lambda e: e.t_ms)

    def summary(self) -> str:
        lines = []
        lines.append(f"╔══ Delfhos Trace {'═' * 42}╗")
        
        # Format task wrapping
        import textwrap
        task_str = self.task.replace('\n', ' ').strip()
        wrapped_task = textwrap.wrap(task_str, width=45) if task_str else [""]
        lines.append(f"║ Task     {wrapped_task[0]}".ljust(60)+"║")
        for tw in wrapped_task[1:3]: # max 2 extra lines
            lines.append(f"║          {tw}".ljust(60)+"║")
        if len(wrapped_task) > 3:
            lines.append(f"║          ...".ljust(60)+"║")
            
        lines.append(f"║ Outcome  {self.outcome}".ljust(60)+"║")
        lines.append(f"║ Duration {self.duration_ms:,}ms".ljust(60)+"║")
        lines.append(f"╠{'═' * 59}╣")
        
        if self.memory_retrieval:
            lines.append(f"║ MEMORY RETRIEVAL          {self.memory_retrieval.duration_ms:,}ms".ljust(60)+"║")
            lines.append(f"║   Facts retrieved         {self.memory_retrieval.facts_retrieved}".ljust(60)+"║")
            lines.append(f"║   Context injected        {len(self.memory_retrieval.context_injected.split())} tokens".ljust(60)+"║")
            lines.append(f"║".ljust(60)+"║")

        if self.prefilter:
            parallel_str = f"  (parallel with {self.prefilter.ran_parallel_with})" if self.prefilter.ran_parallel_with else ""
            lines.append(f"║ PREFILTER                 {self.prefilter.duration_ms:,}ms{parallel_str}".ljust(60)+"║")
            lines.append(f"║   Model                   {self.prefilter.model_used}".ljust(60)+"║")
            lines.append(f"║   Cost USD                {'None' if self.prefilter.cost_usd is None else f'${self.prefilter.cost_usd:.6f}'}".ljust(60)+"║")
            lines.append(f"║   Tools available         {self.prefilter.tools_available}".ljust(60)+"║")
            
            sel = ", ".join(self.prefilter.tools_selected)
            if len(sel) > 32: sel = sel[:29] + "..."
            lines.append(f"║   Tools selected          {sel}".ljust(60)+"║")
            
            if self.merge and self.merge.tools_added_by_memory:
                added = ", ".join(self.merge.tools_added_by_memory)
                if len(added) > 32: added = added[:29] + "..."
                lines.append(f"║   Tools added by memory   {added}".ljust(60)+"║")
            lines.append(f"║".ljust(60)+"║")

        if self.code_generation:
            lines.append(f"║ CODE GENERATION           {self.code_generation.duration_ms:,}ms".ljust(60)+"║")
            lines.append(f"║   Model                   {self.code_generation.model_used}".ljust(60)+"║")
            lines.append(f"║   Tokens in/out           {self.code_generation.tokens_input:,} / {self.code_generation.tokens_output:,}".ljust(60)+"║")
            lines.append(f"║   Cost USD                {'None' if self.code_generation.cost_usd is None else f'${self.code_generation.cost_usd:.6f}'}".ljust(60)+"║")
            lines.append(f"║".ljust(60)+"║")

        if self.execution:
            lines.append(f"║ EXECUTION                 {self.execution.duration_ms:,}ms".ljust(60)+"║")
            lines.append(f"║   Cost USD                {'None' if self.execution.cost_usd is None else f'${self.execution.cost_usd:.6f}'}".ljust(60)+"║")
            lines.append(f"║   Tool calls              {len(self.tool_calls)}".ljust(60)+"║")
            for tc in self.tool_calls:
                status_char = '✓' if tc.outcome == 'success' else '✗'
                
                arg_strs = []
                for k, v in (tc.arguments or {}).items():
                    val_str = repr(v) if isinstance(v, str) else str(v)
                    arg_strs.append(f"{k}={val_str}")
                arg_summary = ", ".join(arg_strs)
                
                if len(arg_summary) > 25: arg_summary = arg_summary[:22] + "..."
                if not arg_summary: arg_summary = "()"
                
                lines.append(f"║   {status_char} {tc.tool_name:<15} {arg_summary}".ljust(50)+f"{tc.duration_ms:,}ms".rjust(10)+"║")
                
                if tc.outcome == 'success' and tc.result:
                    res_summary = str(tc.result).replace('\n', ' ')
                    if len(res_summary) > 40: res_summary = res_summary[:37] + "..."
                    lines.append(f"║       → {res_summary}".ljust(60)+"║")
                elif tc.outcome != 'success' and tc.error:
                    err_summary = str(tc.error).replace('\n', ' ')
                    if len(err_summary) > 40: err_summary = err_summary[:37] + "..."
                    lines.append(f"║       → [ERROR] {err_summary}".ljust(60)+"║")
            lines.append(f"║{'':<59}║")

        if self.session_close:
            lines.append(f"║ SESSION CLOSE             {self.session_close.duration_ms:,}ms".ljust(60) + "║")
            lines.append(f"║   Model                   {self.session_close.model_used}".ljust(60) + "║")
            lines.append(f"║   Facts extracted         {self.session_close.facts_extracted}".ljust(60) + "║")
            lines.append(f"║   Facts deduplicated      {self.session_close.facts_deduplicated}".ljust(60) + "║")
            lines.append(f"║   Facts written           {self.session_close.facts_written}".ljust(60) + "║")
            lines.append(f"║{'':<59}║")

        if self.chat_compression:
            lines.append(f"║ CHAT COMPRESSION          {self.chat_compression.duration_ms:,}ms".ljust(60) + "║")
            lines.append(f"║   Model                   {self.chat_compression.model_used}".ljust(60) + "║")
            lines.append(f"║   Messages reduced        {self.chat_compression.messages_before} -> {self.chat_compression.messages_after}".ljust(60) + "║")

        lines.append(f"╠{'═' * 59}╣")
        usage = self.usage
        
        task_str = f"{usage.task:,} (in: {self.code_generation.tokens_input:,} / out: {self.code_generation.tokens_output:,})" if self.code_generation else "0"
        pref_str = f"{usage.prefilter:,} (in: {self.prefilter.tokens_input:,} / out: {self.prefilter.tokens_output:,})" if self.prefilter else "0"
        exec_str = f"{usage.execution:,} (in: {self.execution.tokens_input:,} / out: {self.execution.tokens_output:,})" if self.execution else "0"
        ext_str = f"{usage.extractor:,} (in: {self.session_close.tokens_input:,} / out: {self.session_close.tokens_output:,})" if self.session_close else "0"
        summ_str = f"{usage.summarizer:,}" if self.chat_compression else "0"

        lines.append(f"║ TOKENS (Total / Input / Output)".ljust(60)+"║")
        lines.append(f"║   Task (code gen)         {task_str}".ljust(60)+"║")
        lines.append(f"║   Task (execution)        {exec_str}".ljust(60)+"║")
        lines.append(f"║   Prefilter               {pref_str}".ljust(60)+"║")
        lines.append(f"║   Memory Extractor        {ext_str}".ljust(60)+"║")
        lines.append(f"║   Chat Summarizer         {summ_str}".ljust(60)+"║")
        lines.append(f"║   Total                   {usage.total:,}".ljust(60)+"║")
        lines.append(f"║   Cost USD                {'None' if self.total_cost_usd is None else f'${self.total_cost_usd:.6f}'}".ljust(60)+"║")
        if self.pricing_path:
            lines.append(f"║   Pricing source          {self.pricing_path}".ljust(60)+"║")
        lines.append(f"║   Overhead                {usage.overhead_percent}%".ljust(60)+"║")
        lines.append(f"╚{'═' * 59}╝")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        def _serialize(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            if hasattr(obj, '__dict__'):
                return str(obj)
            return obj
            
        return json.loads(json.dumps(asdict(self), default=_serialize))

    def to_json(self, file_path: str):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
