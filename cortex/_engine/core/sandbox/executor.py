"""
SandboxExecutor — Backend selector and lifecycle manager.

Picks the best available execution backend based on configuration and
runtime availability, then delegates all ``execute()`` calls to it.
"""

import shutil
import logging
from typing import Any, Dict, Literal, Optional

from .base import BaseSandbox
from .local import LocalSandbox

logger = logging.getLogger(__name__)

SandboxMode = Literal["auto", "docker", "local"]


def _docker_available() -> bool:
    """Return True if the Docker CLI is on PATH and the daemon is reachable."""
    if shutil.which("docker") is None:
        return False
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


class SandboxExecutor(BaseSandbox):
    """
    Transparent proxy that selects the best sandbox backend.

    Parameters
    ----------
    mode
        ``"auto"``   – Docker if available, else local  (default)
        ``"docker"`` – require Docker, raise if unavailable
        ``"local"``  – always use in-process PythonExecutor
    sandbox_config
        Extra options forwarded to the Docker backend (memory_limit,
        cpu_limit, timeout, network).  Ignored for the local backend.
    **executor_kwargs
        Forwarded to the backend constructor (tool_manager, task_id, …).
    """

    def __init__(
        self,
        mode: SandboxMode = "auto",
        sandbox_config: Optional[Dict[str, Any]] = None,
        workspace_files: Optional[list] = None,
        **executor_kwargs,
    ):
        self._mode = mode
        self._sandbox_config = sandbox_config or {}
        self._workspace_files = workspace_files or []
        self._executor_kwargs = executor_kwargs
        self._backend: Optional[BaseSandbox] = None

    # ------------------------------------------------------------------
    # Lazy initialisation – the backend is created on first execute()
    # so we don't probe Docker at import time.
    # ------------------------------------------------------------------

    def _resolve_backend(self) -> BaseSandbox:
        if self._mode == "local":
            logger.info("Sandbox: using local (in-process) backend")
            return LocalSandbox(**self._executor_kwargs)

        if self._mode == "docker" or self._mode == "auto":
            if _docker_available():
                # Deferred import to avoid hard dependency on docker package
                from .docker_sandbox import DockerSandbox
                logger.info("Sandbox: using Docker backend")
                return DockerSandbox(
                    sandbox_config=self._sandbox_config,
                    workspace_files=self._workspace_files,
                    **self._executor_kwargs,
                )
            elif self._mode == "docker":
                raise RuntimeError(
                    "Sandbox mode is 'docker' but Docker is not available. "
                    "Install Docker and ensure the daemon is running, or set "
                    "sandbox='auto' to allow fallback."
                )
            else:
                return LocalSandbox(**self._executor_kwargs)

        raise ValueError(f"Unknown sandbox mode: {self._mode!r}")

    # ------------------------------------------------------------------
    # BaseSandbox interface
    # ------------------------------------------------------------------

    @property
    def namespace(self):
        return getattr(self._backend, "namespace", None)

    @property
    def _baseline_keys(self):
        return getattr(self._backend, "_baseline_keys", set())

    async def execute(self, code: str) -> Dict[str, Any]:
        if self._backend is None:
            self._backend = self._resolve_backend()
        return await self._backend.execute(code)

    async def cleanup(self) -> None:
        if self._backend is not None:
            await self._backend.cleanup()
            self._backend = None
