"""
Sandbox — Pluggable code-execution backends for Delfhos agents.

Provides a unified interface for running LLM-generated Python code in
isolated environments.  The default ``SandboxExecutor`` automatically
selects the best available backend:

* **docker** – full container isolation (recommended for production)
* **local**  – in-process ``exec()`` with restricted builtins (current behaviour)
"""

from .base import BaseSandbox
from .executor import SandboxExecutor
from .local import LocalSandbox

__all__ = [
    "BaseSandbox",
    "SandboxExecutor",
    "LocalSandbox",
]
