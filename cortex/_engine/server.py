"""
AgentServer — a small embedded HTTP API over a Cortex/Agent.

Wraps an agent in a FastAPI app exposing a handful of endpoints so a request's
live progress (state, traces, tool calls, tokens, output) can be polled from
anything that speaks HTTP:

    POST /run               body {"task": "..."}  -> {"task_id": "..."}
    GET  /tasks/{id}        -> StreamSnapshot as JSON (poll until is_terminal)
    GET  /health            -> {"ok": true}   (always public)

Run it standalone with ``agent.serve(port=...)``, or mount ``AgentServer(agent).app``
inside an existing ASGI application. FastAPI/uvicorn are core dependencies, so no
extra install is required.

Security
--------
Pass ``api_key=`` (a string or list of strings) to require callers to
authenticate. When unset, the ``DELFHOS_API_KEY`` env var is used (comma-separated
for multiple keys). Authenticated requests send the key as either::

    Authorization: Bearer <key>
    X-API-Key: <key>

If no key is configured at all, the API is left open (a warning is logged) so
local development still works out of the box. ``/health`` is always public so
load balancers can probe it without credentials.
"""

import hmac
import os

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class _RunRequest(BaseModel):
    task: str


def _resolve_api_keys(api_key) -> set:
    """Normalize the configured key(s) into a set of non-empty strings.

    Accepts a single string, a list/tuple of strings, or None (in which case the
    DELFHOS_API_KEY env var is consulted, comma-separated for multiple keys).
    """
    if api_key is None:
        env_value = os.getenv("DELFHOS_API_KEY", "")
        candidates = env_value.split(",")
    elif isinstance(api_key, str):
        candidates = [api_key]
    else:
        candidates = list(api_key)
    return {k.strip() for k in candidates if k and k.strip()}


class AgentServer:
    """Builds a FastAPI app that drives an agent and reports live snapshots."""

    def __init__(self, agent, api_key=None, allow_origins=None):
        self.agent = agent
        self._api_keys = _resolve_api_keys(api_key)
        self.app = FastAPI(title="Delfhos Agent", docs_url="/docs")

        # Allow cross-origin calls so the API is easy to reach from browsers and
        # other services. Defaults to "*" since access is gated by the API key.
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins if allow_origins is not None else ["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        if not self._api_keys:
            try:
                from .utils.console import console
                console.warning(
                    "AGENT SERVER",
                    "No API key configured — the HTTP API is OPEN. Set api_key= or "
                    "the DELFHOS_API_KEY env var to require authentication.",
                )
            except Exception:
                pass

        self._register_routes()

    # ------------------------------------------------------------------ #
    #  Auth                                                                #
    # ------------------------------------------------------------------ #

    def _check_auth(self, authorization, x_api_key) -> None:
        """Raise 401 unless a valid key is presented (no-op when auth is off)."""
        if not self._api_keys:
            return

        presented = None
        if x_api_key:
            presented = x_api_key.strip()
        elif authorization and authorization.lower().startswith("bearer "):
            presented = authorization[7:].strip()

        if not presented:
            raise HTTPException(
                status_code=401,
                detail="Missing API key. Send 'Authorization: Bearer <key>' or 'X-API-Key: <key>'.",
            )

        # Constant-time comparison against every configured key.
        if not any(hmac.compare_digest(presented, valid) for valid in self._api_keys):
            raise HTTPException(status_code=401, detail="Invalid API key.")

    # ------------------------------------------------------------------ #
    #  Internals                                                           #
    # ------------------------------------------------------------------ #

    def _snapshot_dict(self, task_id: str) -> dict:
        return self.agent.poll(task_id).to_dict()

    # ------------------------------------------------------------------ #
    #  Routes                                                              #
    # ------------------------------------------------------------------ #

    def _register_routes(self):
        app = self.app

        async def auth(
            authorization: str = Header(default=None),
            x_api_key: str = Header(default=None),
        ):
            self._check_auth(authorization, x_api_key)

        @app.get("/health")
        async def health():
            return {"ok": True}

        @app.post("/run", dependencies=[Depends(auth)])
        async def run(req: _RunRequest):
            task_id = self.agent.submit(req.task)
            return {"task_id": task_id}

        @app.get("/tasks/{task_id}", dependencies=[Depends(auth)])
        async def get_task(task_id: str):
            return JSONResponse(self._snapshot_dict(task_id))
