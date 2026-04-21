"""
DockerSandbox — Execute agent code inside an isolated Docker container.

Manages the full container lifecycle: image build/cache, container creation
with resource limits, RPC communication via Unix socket, and cleanup.
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


def _image_exists() -> bool:
    """Check if the sandbox Docker image has been built."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", _full_image()],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def build_image(force: bool = False) -> None:
    """
    Build the sandbox Docker image from the bundled Dockerfile.

    Skips the build if the image already exists unless *force* is True.
    """
    if not force and _image_exists():
        logger.debug("Sandbox image %s already exists", _full_image())
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

        # 3. Start RPC server
        self._rpc_server = RPCServer(
            tool_libraries=self._libraries,
            on_print=lambda text: self._stdout_lines.append(text),
        )
        socket_path = await self._rpc_server.start()

        try:
            # 4. Create and start container
            self._container_id = self._create_container(socket_path)
            self._start_container()

            # 5. Queue execute message — sent when container connects
            self._queue_execute_message(code)

            # 6. Wait for result (with timeout)
            timeout = self._config["timeout"] + 10  # grace period
            try:
                result = await asyncio.wait_for(
                    self._rpc_server.wait_for_result(),
                    timeout=timeout,
                )
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

    def _create_container(self, socket_path: str) -> str:
        """Create a Docker container with security restrictions."""
        socket_dir = os.path.dirname(socket_path)
        socket_name = os.path.basename(socket_path)

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
            # Mount RPC socket
            "-v", f"{socket_dir}:/rpc:rw",
            # Mount uploads directory
            "-v", f"{uploads_dir}:/data:rw",
            # Mount output directory for add_to_output_files()
            "-v", f"{output_dir}:/output:rw",
        ]

        # Mount workspace files as read-only
        for host_path in self._workspace_files:
            filename = os.path.basename(host_path)
            cmd.extend(["-v", f"{host_path}:/workspace/{filename}:ro"])

        # Network isolation
        if not self._config["network"]:
            cmd.extend(["--network", "none"])

        # Container entrypoint with socket path
        cmd.extend([
            _full_image(),
            f"/rpc/{socket_name}",
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
