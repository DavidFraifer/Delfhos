"""
LocalSandbox — In-process execution backend (wraps the existing PythonExecutor).

This is the fallback when Docker is unavailable.  It provides the same
restricted-builtins / import-whitelist sandbox that Delfhos has always used.
"""

from typing import Any, Dict, Optional

from .base import BaseSandbox
from ..python_executor import PythonExecutor


class LocalSandbox(BaseSandbox):
    """
    Execute agent code in-process using :class:`PythonExecutor`.

    Parameters match the existing ``PythonExecutor`` constructor so the
    orchestrator can create a ``LocalSandbox`` as a drop-in replacement.
    """

    def __init__(
        self,
        tool_manager,
        task_id: str,
        agent_id: str,
        light_llm: str,
        heavy_llm: str,
        orchestrator=None,
        vision_model: Optional[str] = None,
    ):
        self._executor = PythonExecutor(
            tool_manager=tool_manager,
            task_id=task_id,
            agent_id=agent_id,
            light_llm=light_llm,
            heavy_llm=heavy_llm,
            orchestrator=orchestrator,
            vision_model=vision_model,
        )

    @property
    def namespace(self):
        return self._executor.namespace

    @property
    def _baseline_keys(self):
        return getattr(self._executor, "_baseline_keys", set())

    async def execute(self, code: str) -> Dict[str, Any]:
        return await self._executor.execute(code)

    async def cleanup(self) -> None:
        # In-process executor holds no external resources.
        pass
