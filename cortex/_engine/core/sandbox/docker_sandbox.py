"""
DockerSandbox — Execute agent code inside an isolated Docker container.

Manages the full container lifecycle: image build/cache, container creation
with resource limits, RPC communication via TCP loopback, and cleanup.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .base import BaseSandbox
from .rpc_server import RPCServer
from . import rpc_protocol as proto

logger = logging.getLogger(__name__)

# Path to the container/ directory that holds the Dockerfile + scripts
_CONTAINER_DIR = Path(__file__).parent / "container"

# Docker image name and tag
_IMAGE_NAME = "delfhos-sandbox"


def _get_image_tag() -> str:
    """Read the project version from pyproject.toml for image tagging."""
    try:
        toml_path = Path(__file__).resolve().parents[4] / "pyproject.toml"
        for line in toml_path.read_text().splitlines():
            if line.strip().startswith("version"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "latest"


def _full_image() -> str:
    return f"{_IMAGE_NAME}:{_get_image_tag()}"

# Default resource limits
_DEFAULTS = {
    "memory_limit": "512m",
    "cpu_limit": 1.0,
    "timeout": 300,
    "network": False,
    "pids_limit": 64,
    "tmpfs_size": "50m",
}


def _image_created_at() -> Optional[float]:
    """Return the cached image's creation timestamp, or None if missing."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Created}}", _full_image()],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    # Format: "2024-05-01T12:34:56.789Z"
    import datetime as _dt
    try:
        s = result.stdout.strip().replace("Z", "+00:00")
        # Trim sub-microsecond precision Docker sometimes emits
        if "." in s:
            head, _, tail = s.partition(".")
            frac, _, tz = tail.partition("+")
            frac = (frac + "000000")[:6]
            s = f"{head}.{frac}+{tz}" if tz else f"{head}.{frac}"
        return _dt.datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def _image_is_stale() -> bool:
    """True if any bundled container source file is newer than the image."""
    created = _image_created_at()
    if created is None:
        return True
    for path in _CONTAINER_DIR.iterdir():
        try:
            if path.stat().st_mtime > created:
                return True
        except OSError:
            continue
    return False


def build_image(force: bool = False) -> None:
    """
    Build the sandbox Docker image from the bundled Dockerfile.

    Skips the build if the image exists and is up-to-date relative to the
    bundled container sources, unless *force* is True.
    """
    if not force and not _image_is_stale():
        logger.debug("Sandbox image %s is up to date", _full_image())
        return

    logger.info("Building sandbox Docker image %s …", _full_image())
    result = subprocess.run(
        ["docker", "build", "-t", _full_image(), str(_CONTAINER_DIR)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to build sandbox image:\n{result.stderr}"
        )
    logger.info("Sandbox image built successfully")


class DockerSandbox(BaseSandbox):
    """
    Run agent code in a disposable Docker container with full OS isolation.

    Parameters
    ----------
    tool_manager, task_id, agent_id, …
        Same as :class:`PythonExecutor` — used to create real tool libraries
        on the *host* side for RPC dispatch.
    sandbox_config
        Override default resource limits (memory_limit, cpu_limit, timeout,
        network, pids_limit).
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
        sandbox_config: Optional[Dict[str, Any]] = None,
        workspace_files: Optional[list] = None,
    ):
        self._tool_manager = tool_manager
        self._task_id = task_id
        self._agent_id = agent_id
        self._light_llm = light_llm
        self._heavy_llm = heavy_llm
        self._orchestrator = orchestrator
        self._vision_model = vision_model
        self._config = {**_DEFAULTS, **(sandbox_config or {})}
        self._workspace_files = workspace_files or []

        # Lazily created
        self._libraries: Optional[dict] = None
        self._rpc_server: Optional[RPCServer] = None
        self._container_id: Optional[str] = None
        self._stdout_lines: list[str] = []

    # ------------------------------------------------------------------
    # BaseSandbox interface
    # ------------------------------------------------------------------

    async def execute(self, code: str) -> Dict[str, Any]:
        # 1. Ensure image exists
        build_image()

        # 2. Create host-side tool libraries (once)
        if self._libraries is None:
            self._libraries = self._create_libraries()

        # 3. Start RPC server (TCP loopback)
        self._rpc_server = RPCServer(
            tool_libraries=self._libraries,
            on_print=lambda text: self._stdout_lines.append(text),
        )
        port = await self._rpc_server.start()

        try:
            # 4. Create and start container
            self._container_id = self._create_container(port)
            self._start_container()

            # 5. Queue execute message — sent when container connects
            self._queue_execute_message(code)

            # 6. Wait for result, but fail fast if the container exits first.
            # Without this, a container that crashes during startup would
            # leave us waiting the full timeout for an RPC reply that will
            # never arrive.
            timeout = self._config["timeout"] + 10  # grace period
            try:
                result = await self._wait_for_result_or_exit(timeout)
            except asyncio.TimeoutError:
                result = {
                    "success": False,
                    "result": None,
                    "output": "\n".join(self._stdout_lines),
                    "error": f"Container execution timeout after {self._config['timeout']}s",
                    "execution_time": self._config["timeout"],
                }

            # Merge any streamed print output
            if self._stdout_lines:
                existing_output = result.get("output", "")
                streamed = "\n".join(self._stdout_lines)
                if streamed and streamed not in existing_output:
                    result["output"] = streamed + ("\n" + existing_output if existing_output else "")

            # Remap container output_files {name: filename} → {name: host_abs_path}
            container_files = result.pop("output_files", {}) or {}
            output_dir = getattr(self, "_output_dir", None)
            host_files = {}
            if output_dir and container_files:
                for name, filename in container_files.items():
                    host_path = os.path.join(output_dir, filename)
                    if os.path.isfile(host_path):
                        host_files[name] = host_path
            result["output_files"] = host_files

            return result

        finally:
            # 7. Cleanup
            await self._cleanup_container()
            self._stdout_lines.clear()

    async def cleanup(self) -> None:
        await self._cleanup_container()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_libraries(self) -> dict:
        """Create the real tool libraries on the host side."""
        from cortex._engine.core.python_executor import ToolExecutionTracker
        from cortex._engine.tools.tool_libraries import create_tool_libraries

        tool_tracker = ToolExecutionTracker(self._orchestrator, self._task_id)
        return create_tool_libraries(
            self._tool_manager,
            self._task_id,
            self._agent_id,
            self._light_llm,
            self._heavy_llm,
            tool_tracker=tool_tracker,
            vision_llm=self._vision_model,
            memory=self._orchestrator.memory if self._orchestrator else None,
        )

    def _create_container(self, rpc_port: int) -> str:
        """Create a Docker container with security restrictions."""
        # Build the uploads and output directory paths for this task
        uploads_dir = os.path.join(os.getcwd(), "uploads", self._task_id)
        os.makedirs(uploads_dir, exist_ok=True)
        output_dir = os.path.join(uploads_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        self._output_dir = output_dir

        cmd = [
            "docker", "create",
            # Resource limits
            "--memory", str(self._config["memory_limit"]),
            "--cpus", str(self._config["cpu_limit"]),
            "--pids-limit", str(self._config["pids_limit"]),
            # Security
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--read-only",
            # Temp filesystem
            "--tmpfs", f"/tmp:size={self._config['tmpfs_size']},noexec",
            # Mount uploads directory
            "-v", f"{uploads_dir}:/data:rw",
            # Mount output directory for add_to_output_files()
            "-v", f"{output_dir}:/output:rw",
            # Make host reachable as host.docker.internal on all platforms.
            # macOS/Windows Docker Desktop provide this alias automatically,
            # but on Linux it must be added explicitly.
            "--add-host", "host.docker.internal:host-gateway",
        ]

        # Mount workspace files as read-only
        for host_path in self._workspace_files:
            filename = os.path.basename(host_path)
            cmd.extend(["-v", f"{host_path}:/workspace/{filename}:ro"])

        # Note: we no longer use `--network none` because the container needs
        # a TCP route back to the host RPC server. Agent code is still
        # constrained by the `allowed_imports` allowlist (no urllib/requests/
        # httpx/socket), so it cannot make arbitrary network calls itself.

        # Container entrypoint with host:port RPC endpoint
        cmd.extend([
            _full_image(),
            f"host.docker.internal:{rpc_port}",
        ])

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create container: {result.stderr}")

        container_id = result.stdout.strip()
        logger.debug("Created container %s", container_id[:12])
        return container_id

    def _start_container(self) -> None:
        """Start the created container."""
        result = subprocess.run(
            ["docker", "start", self._container_id],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start container: {result.stderr}")
        logger.debug("Started container %s", self._container_id[:12])

    def _queue_execute_message(self, code: str) -> None:
        """
        Queue the execute message on the RPC server.

        When the container connects, the server sends this as the first
        message so the runner knows what code to execute.
        """
        available_tools = list(self._libraries.keys()) if self._libraries else []
        manifest = {
            "task_id": self._task_id,
            "agent_id": self._agent_id,
            "available_tools": available_tools,
            "agent_context": (
                self._orchestrator.agent_context
                if self._orchestrator and hasattr(self._orchestrator, "agent_context")
                else {}
            ),
            "allowed_imports": [
                "asyncio", "datetime", "json", "math", "pathlib",
                "re", "statistics", "time",
            ],
            "timeout": self._config["timeout"],
        }
        self._rpc_server._pending_execute = proto.msg_execute(code, manifest)

    async def _wait_for_result_or_exit(self, timeout: float) -> Dict[str, Any]:
        """Await the RPC result, but bail out if the container exits first.

        Polls `docker inspect` every 500ms in parallel with the RPC wait.
        If the container terminates before producing a result, captures its
        logs and returns a failure dict so the caller can surface the real
        error instead of timing out.
        """
        result_task = asyncio.create_task(self._rpc_server.wait_for_result())
        exit_task = asyncio.create_task(self._poll_container_exit())
        try:
            done, _ = await asyncio.wait(
                {result_task, exit_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise asyncio.TimeoutError
            if result_task in done:
                return result_task.result()
            # Container exited before sending a result.
            exit_info = exit_task.result()
            logs = self._collect_container_logs()
            return {
                "success": False,
                "result": None,
                "output": "\n".join(self._stdout_lines),
                "error": (
                    f"Sandbox container exited with code {exit_info.get('exit_code')} "
                    f"before producing a result.\n\nContainer logs:\n{logs}"
                ),
                "execution_time": 0,
            }
        finally:
            for t in (result_task, exit_task):
                if not t.done():
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass

    async def _poll_container_exit(self) -> Dict[str, Any]:
        """Poll `docker inspect` until the container is no longer running."""
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(0.5)
            if not self._container_id:
                continue
            info = await loop.run_in_executor(None, self._inspect_container)
            if info is None:
                continue
            if info.get("status") and info["status"] != "running":
                return info

    def _inspect_container(self) -> Optional[Dict[str, Any]]:
        try:
            result = subprocess.run(
                [
                    "docker", "inspect",
                    "--format", "{{.State.Status}}|{{.State.ExitCode}}",
                    self._container_id,
                ],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return {"status": "missing", "exit_code": -1}
        status, _, exit_code = result.stdout.strip().partition("|")
        try:
            exit_code_int = int(exit_code)
        except (TypeError, ValueError):
            exit_code_int = -1
        return {"status": status, "exit_code": exit_code_int}

    def _collect_container_logs(self, max_chars: int = 4000) -> str:
        if not self._container_id:
            return "(no container)"
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", "200", self._container_id],
                capture_output=True, text=True, timeout=5,
            )
        except Exception as e:
            return f"(failed to read logs: {e})"
        combined = (result.stdout or "") + (result.stderr or "")
        combined = combined.strip()
        if len(combined) > max_chars:
            combined = "…" + combined[-max_chars:]
        return combined or "(empty)"

    async def _cleanup_container(self) -> None:
        """Stop and remove the container, clean up RPC server."""
        if self._rpc_server:
            await self._rpc_server.stop()
            self._rpc_server = None

        if self._container_id:
            # Force-stop and remove
            try:
                subprocess.run(
                    ["docker", "rm", "-f", self._container_id],
                    capture_output=True, timeout=15,
                )
                logger.debug("Removed container %s", self._container_id[:12])
            except Exception:
                logger.warning("Failed to remove container %s", self._container_id[:12])
            self._container_id = None
