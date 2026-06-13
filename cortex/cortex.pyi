"""Type stubs for cortex.cortex — The AI agent framework."""

from typing import Any, Callable, Dict, List, Optional, Union

from delfhos.memory import Chat, Memory
from delfhos.llm_config import LLMConfig
from cortex._engine.types import StreamSnapshot as StreamSnapshot

# LLMSpec: a model string or a fully configured LLMConfig for custom/local endpoints
LLMSpec = Union[str, LLMConfig]

class Response:
    """Unified response object for agent run execution."""
    text: str
    status: bool
    error: Optional[str]
    cost_usd: Optional[float]
    duration_ms: int
    trace: Any
    files: Dict[str, str]

class Cortex:
    """
    AI agent that executes tasks by generating and running Python code against your tools.

    Cortex orchestrates a multi-step workflow:
      1. Prefilter: Choose relevant tools for the task.
      2. Generate: Create optimized Python code using an LLM.
      3. Execute: Run code in a sandbox against real services.
      4. Iterate: Get feedback and refine until the goal succeeds.

    Args:
        tools: Service tools (Gmail, Drive, SQL, APITool, WebSearch, etc) or @tool functions.
               Per-tool approval: set confirm= on each tool, e.g. Gmail(confirm=["send"]).
        llm: Single LLM for all ops.
        light_llm: Fast LLM for prefiltering.
        heavy_llm: Stronger LLM for code generation.
        vision_llm: Model used for image analysis and multimodal tasks. Defaults to heavy_llm.
        chat: Chat(keep=10, summarize=False) for session memory (set Chat.summarizer_llm for compression).
        memory: Persistent memory.
        system_prompt: Context/role.
        on_confirm: Approval callback (per-tool confirm= triggers it).
        verbose: Print detailed traces.
        prefilter_mode: Tool prefilter strategy: "auto" (default) | "filter" | "search" | "off".
        retry_count: Auto-retries on execution failure (default: 1).
        rerun_count: Max rerun() iterations per task (default: 2).
        sandbox: Execution isolation mode: "auto" | "docker" | "local".
        sandbox_config: Resource limit overrides for Docker mode.
        budget_usd: Hard spending cap in USD across all run() calls.
        files: Absolute host paths injected as read-only workspace files.
        allowed_libs: PyPI package names added to the sandbox import allowlist.
        providers: API key overrides.
    """
    def __init__(
        self,
        tools: Optional[List[Union[Any, Callable]]] = ...,
        chat: Optional[Chat] = ...,
        memory: Optional[Memory] = ...,
        llm: Optional[LLMSpec] = ...,
        light_llm: Optional[LLMSpec] = ...,
        heavy_llm: Optional[LLMSpec] = ...,
        vision_llm: Optional[LLMSpec] = ...,
        system_prompt: Optional[str] = ...,
        on_confirm: Optional[Callable] = ...,
        providers: Optional[Dict[str, str]] = ...,
        verbose: bool = ...,
        prefilter_mode: str = ...,
        retry_count: int = ...,
        rerun_count: int = ...,
        sandbox: str = ...,
        sandbox_config: Optional[Dict[str, Any]] = ...,
        budget_usd: Optional[float] = ...,
        files: Optional[List[str]] = ...,
        allowed_libs: Optional[List[str]] = ...,
    ) -> None: ...

    def start(self) -> "Cortex": ...
    def stop(self) -> None: ...

    def submit(self, task: str) -> str: ...
    def run(self, task: str, timeout: float = ...) -> Response: ...
    def run_chat(self, timeout: float = ...) -> None: ...
    async def arun(self, task: str, timeout: float = ...) -> Response: ...
    def poll(self, task_id: str) -> StreamSnapshot: ...

    def serve(self, host: str = ..., port: int = ..., api_key: Optional[Union[str, List[str]]] = ..., allow_origins: Optional[List[str]] = ...) -> None: ...
    def asgi_app(self, api_key: Optional[Union[str, List[str]]] = ..., allow_origins: Optional[List[str]] = ...) -> Any: ...

    def get_pending_approvals(self) -> list: ...
    def approve(self, request_id: str, response: str = ...) -> bool: ...
    def reject(self, request_id: str, reason: str = ...) -> bool: ...

    def info(self) -> Dict[str, Any]: ...
    def status(self) -> Dict[str, Any]: ...
    def get_llm_config_string(self) -> str: ...
    def reset_budget(self, budget_usd: Optional[float] = ...) -> None: ...

    @property
    def usage(self) -> Any: ...
    @property
    def memory(self) -> Optional[Memory]: ...
    @property
    def chat(self) -> Optional[Chat]: ...
    @property
    def agent_id(self) -> str: ...
    @property
    def total_cost_usd(self) -> float: ...
    @property
    def retry_count(self) -> int: ...
    @retry_count.setter
    def retry_count(self, value: int) -> None: ...
    @property
    def rerun_count(self) -> int: ...
    @rerun_count.setter
    def rerun_count(self, value: int) -> None: ...
    @property
    def orchestrator(self) -> Any: ...

    def __enter__(self) -> "Cortex": ...
    def __exit__(self, *_: Any) -> None: ...
    async def __aenter__(self) -> "Cortex": ...
    async def __aexit__(self, *_: Any) -> None: ...
    def __str__(self) -> str: ...
