"""
AgentServer — a small embedded HTTP API over a Cortex/Agent.

Wraps an agent in a FastAPI app exposing four endpoints so a request's live
progress can be polled or streamed from anything that speaks HTTP:

    POST /run               body {"task": "..."}  -> {"task_id": "..."}
    GET  /tasks/{id}        -> StreamSnapshot as JSON
    GET  /tasks/{id}/stream -> Server-Sent Events (one snapshot per frame)
    GET  /health            -> {"ok": true}

Run it standalone with ``agent.serve(port=...)``, or mount ``AgentServer(agent).app``
inside an existing ASGI application. FastAPI/uvicorn are core dependencies, so no
extra install is required.
"""

import asyncio
import json

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel


class _RunRequest(BaseModel):
    task: str


class AgentServer:
    """Builds a FastAPI app that drives an agent and reports live snapshots."""

    def __init__(self, agent, stream_interval: float = 0.25, stream_timeout: float = 600.0):
        self.agent = agent
        self.stream_interval = stream_interval
        self.stream_timeout = stream_timeout
        self.app = FastAPI(title="Delfhos Agent", docs_url="/docs")
        self._register_routes()

    # ------------------------------------------------------------------ #
    #  Internals                                                           #
    # ------------------------------------------------------------------ #

    def _snapshot_dict(self, task_id: str) -> dict:
        return self.agent.poll(task_id).to_dict()

    async def _sse(self, task_id: str):
        """Yield SSE frames (data: <json>\\n\\n) until the task is terminal."""
        deadline = asyncio.get_event_loop().time() + self.stream_timeout
        while asyncio.get_event_loop().time() < deadline:
            snap = self.agent.poll(task_id)
            yield f"data: {json.dumps(snap.to_dict())}\n\n"
            if snap.is_terminal:
                return
            await asyncio.sleep(self.stream_interval)
        # Emit one final frame after timeout.
        yield f"data: {json.dumps(self.agent.poll(task_id).to_dict())}\n\n"

    # ------------------------------------------------------------------ #
    #  Routes                                                              #
    # ------------------------------------------------------------------ #

    def _register_routes(self):
        app = self.app

        @app.get("/health")
        async def health():
            return {"ok": True}

        @app.post("/run")
        async def run(req: _RunRequest):
            task_id = self.agent.run_async(req.task)
            return {"task_id": task_id}

        @app.get("/tasks/{task_id}")
        async def get_task(task_id: str):
            return JSONResponse(self._snapshot_dict(task_id))

        @app.get("/tasks/{task_id}/stream")
        async def stream_task(task_id: str):
            return StreamingResponse(
                self._sse(task_id),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
