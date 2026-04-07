"""Type stubs for cortex.cortex — The AI agent framework."""

from typing import Any, Callable, Dict, List, Optional, Union

from delfhos.memory import Chat, Memory
from delfhos.llm_config import LLMConfig

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

class Cortex:
    """
    AI agent that executes tasks by generating and running Python code against your tools.

    Cortex orchestrates a multi-step workflow:
      1. Prefilter: Choose relevant tools for the task.
      2. Generate: Create optimized Python code using an LLM.
      3. Execute: Run code in a sandbox against real services.
      4. Iterate: Get feedback and refine until the goal succeeds.

    Args:
        tools: Service tools (Gmail, Drive, SQL, MCP, WebSearch, etc) or @tool functions.
               Per-tool approval: set confirm= on each tool, e.g. Gmail(confirm=["send"]).
        llm: Single LLM for all ops.
        light_llm: Fast LLM for prefiltering.
        heavy_llm: Stronger LLM for code generation.
        code_llm: Model used for Python code generation. Defaults to heavy_llm.
        vision_llm: Model used for image analysis and multimodal tasks. Defaults to heavy_llm.
        chat: Chat(keep=10, summarize=False) for session memory (set Chat.summarizer_llm for compression).
        memory: Persistent memory.
        system_prompt: Context/role.
        on_confirm: Approval callback (per-tool confirm= triggers it).
        verbose: Print detailed traces.
        enable_prefilter: If True, pre-filter tools before code generation (default: False).
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
        code_llm: Optional[LLMSpec] = ...,
        vision_llm: Optional[LLMSpec] = ...,
        system_prompt: Optional[str] = ...,
        on_confirm: Optional[Callable] = ...,
        providers: Optional[Dict[str, str]] = ...,
        verbose: bool = ...,
        enable_prefilter: bool = ...,
    ) -> None: ...

    def start(self) -> "Cortex": ...
    def stop(self) -> None: ...

    def run_async(self, task: str) -> None: ...
    def run(self, task: str, timeout: float = ...) -> Response: ...
    def run_chat(self, timeout: float = ...) -> None: ...
    async def arun(self, task: str, timeout: float = ...) -> Response: ...

    def get_pending_approvals(self) -> list: ...
    def approve(self, request_id: str, response: str = ...) -> bool: ...
    def reject(self, request_id: str, reason: str = ...) -> bool: ...

    def info(self) -> Dict[str, Any]: ...
    def get_llm_config_string(self) -> str: ...

    @property
    def usage(self) -> Any: ...
    @property
    def memory(self) -> Optional[Memory]: ...
    @property
    def chat(self) -> Optional[Chat]: ...
    @property
    def agent_id(self) -> str: ...

    def __enter__(self) -> "Cortex": ...
    def __exit__(self, *_: Any) -> None: ...
    async def __aenter__(self) -> "Cortex": ...
    async def __aexit__(self, *_: Any) -> None: ...
    def __str__(self) -> str: ...
