"""
BaseSandbox — Abstract interface that every execution backend must implement.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseSandbox(ABC):
    """
    Abstract base class for code-execution sandboxes.

    Every backend (local ``exec()``, Docker container, …) exposes the same
    two-method interface so the orchestrator can swap backends transparently.
    """

    @abstractmethod
    async def execute(self, code: str) -> Dict[str, Any]:
        """
        Execute *code* and return a result dict.

        Returns
        -------
        dict
            ``success``  : bool
            ``result``   : Any   – return value of the agent code (may be None)
            ``output``   : str   – captured stdout
            ``error``    : str | None – error message on failure
            ``execution_time`` : float – wall-clock seconds
        """

    @abstractmethod
    async def cleanup(self) -> None:
        """Release resources held by this sandbox (containers, temp dirs, …)."""
