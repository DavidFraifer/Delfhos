"""
Human Approval Manager for CORTEX Agent
Handles human-in-the-loop confirmations during task execution
"""

import uuid
import time
import threading
import asyncio
import sys
import inspect
import json
from typing import Dict, Optional, Callable, Any
from ..utils.console import console


class ApprovalRequest:
    """Represents a single approval request"""
    
    def __init__(self, task_id: str, agent_id: str, message: str, context: str = ""):
        # Use full UUID for consistency with database
        self.request_id = str(uuid.uuid4())
        self.task_id = task_id
        self.agent_id = agent_id
        self.message = message
        self.context = context  # Full context for debugging
        self.created_at = time.time()
        self.status = "pending"  # pending, approved, rejected
        self.response = None
        self.responded_at = None
        self._lock = threading.Lock()
    
    def approve(self, response: str = "Approved"):
        """Approve the request"""
        with self._lock:
            if self.status == "pending":
                self.status = "approved"
                self.response = response
                self.responded_at = time.time()
                return True
        return False
    
    def reject(self, reason: str = "Rejected"):
        """Reject the request"""
        with self._lock:
            if self.status == "pending":
                self.status = "rejected"
                self.response = reason
                self.responded_at = time.time()
                return True
        return False
    
    def is_pending(self) -> bool:
        """Check if request is still pending"""
        return self.status == "pending"
    
    def get_info(self) -> dict:
        """Get request information"""
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "message": self.message,
            "context": self.context,  # Full context for debugging
            "status": self.status,
            "response": self.response,
            "created_at": self.created_at,
            "responded_at": self.responded_at,
            "wait_time": (self.responded_at or time.time()) - self.created_at
        }


class ApprovalManager:
    """Manages human approval requests for agent actions"""
    
    def __init__(self, on_confirm: Optional[Callable[..., Any]] = None):
        self.requests: Dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()
        self._callbacks: Dict[str, Callable] = {}  # request_id -> callback
        self.on_confirm = on_confirm

    def _is_interactive_stdin(self) -> bool:
        stdin = getattr(sys, "stdin", None)
        return bool(stdin and hasattr(stdin, "isatty") and stdin.isatty())

    @staticmethod
    def _short_repr(value: Any, max_len: int = 140) -> str:
        try:
            text = repr(value)
        except Exception:
            text = str(value)
        if len(text) > max_len:
            return text[:max_len - 3] + "..."
        return text

    def _build_stdin_preview(self, request: ApprovalRequest) -> Dict[str, str]:
        tool_name = "unknown"
        method_name = None
        args = {}

        try:
            context_obj = json.loads(request.context) if request.context else {}
        except Exception:
            context_obj = {}

        if isinstance(context_obj, dict):
            tool_name = str(context_obj.get("tool") or tool_name)
            method_name = context_obj.get("method")

            reserved_keys = {
                "action",
                "tool",
                "method",
                "operation_kind",
                "confirm_policy",
                "connection",
            }
            args = {k: v for k, v in context_obj.items() if k not in reserved_keys}

            # Prefer readable argument blocks when present.
            if isinstance(context_obj.get("draft"), dict):
                args = context_obj.get("draft")
            elif isinstance(context_obj.get("params"), dict):
                args = context_obj.get("params")

        target = f"{tool_name}.{method_name}" if method_name else tool_name
        args_str = ", ".join(f"{k}={self._short_repr(v)}" for k, v in args.items())
        code_preview = f"await {target}({args_str})" if args_str else f"await {target}(...)"

        return {
            "tool": target,
            "arguments": args_str or "(not provided)",
            "code": code_preview,
        }

    async def _stdin_confirm(self, request: ApprovalRequest) -> bool:
        """Default built-in confirmation flow for interactive terminals."""
        preview = self._build_stdin_preview(request)
        out = getattr(sys, "__stdout__", sys.stdout)
        loop = asyncio.get_running_loop()

        out.write("\n")
        out.write("⚠️  Confirmation required\n")
        out.write(f"    Tool:      {preview['tool']}\n")
        out.write(f"    Arguments: {preview['arguments']}\n")
        out.write(f"    Code:      {preview['code']}\n")
        out.write("\n")
        out.flush()

        def _read_choice() -> str:
            return input("    Approve? [y/n]: ").strip().lower()

        while True:
            try:
                choice = await loop.run_in_executor(None, _read_choice)
            except (EOFError, KeyboardInterrupt):
                return False

            if choice in {"y", "yes"}:
                return True
            if choice in {"n", "no"}:
                return False
            out.write("    Please answer 'y' or 'n'.\n")
            out.flush()

    def _on_confirm_is_async(self) -> bool:
        if asyncio.iscoroutinefunction(self.on_confirm):
            return True
        call_method = getattr(self.on_confirm, "__call__", None)
        return bool(call_method and asyncio.iscoroutinefunction(call_method))

    def _apply_decision(self, request: ApprovalRequest, decision: Any, source: str) -> None:
        if isinstance(decision, bool):
            if decision:
                request.approve(f"Approved via {source}")
            else:
                request.reject(f"Rejected via {source}")
            return

        # Explicit form: (approved: bool, reason: str)
        if (
            isinstance(decision, tuple)
            and len(decision) == 2
            and isinstance(decision[0], bool)
            and isinstance(decision[1], str)
        ):
            approved, reason = decision
            if approved:
                request.approve(reason or f"Approved via {source}")
            else:
                request.reject(reason or f"Rejected via {source}")
            return

        if isinstance(decision, dict) and isinstance(decision.get("approved"), bool):
            response = decision.get("response") or f"Decision via {source}"
            if decision["approved"]:
                request.approve(response)
            else:
                request.reject(response)

    async def _invoke_on_confirm_with_live_stdio(self, request: ApprovalRequest):
        """Run on_confirm using real stdio so interactive prompts are visible immediately."""
        previous_stdout, previous_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

            if self._on_confirm_is_async():
                return await self.on_confirm(request)

            loop = asyncio.get_running_loop()

            def _sync_invoke():
                nested_previous_stdout, nested_previous_stderr = sys.stdout, sys.stderr
                try:
                    sys.stdout = sys.__stdout__
                    sys.stderr = sys.__stderr__
                    return self.on_confirm(request)
                finally:
                    sys.stdout = nested_previous_stdout
                    sys.stderr = nested_previous_stderr

            decision = await loop.run_in_executor(None, _sync_invoke)
            if inspect.isawaitable(decision):
                return await decision
            return decision
        finally:
            sys.stdout = previous_stdout
            sys.stderr = previous_stderr

    async def _run_on_confirm(self, request: ApprovalRequest):
        """
        Invoke optional user callback when a confirmation request is created.

        Supported callback returns:
        - True / False -> auto approve/reject
        - (bool, str) -> auto approve/reject with explicit response/reason
        - dict with {"approved": bool, "response": str}
        - None -> no auto decision
        """
        if not self.on_confirm:
            # Built-in interactive fallback for CLI usage.
            if self._is_interactive_stdin():
                try:
                    decision = await self._stdin_confirm(request)
                    self._apply_decision(request, decision, "stdin")
                except Exception as e:
                    console.error("stdin confirmation failed", str(e), task_id=request.task_id, agent_id=request.agent_id)
            return

        try:
            decision = await self._invoke_on_confirm_with_live_stdio(request)
        except Exception as e:
            console.error("on_confirm callback failed", str(e), task_id=request.task_id, agent_id=request.agent_id)
            return

        self._apply_decision(request, decision, "on_confirm")

    def _invoke_callback_sync(self, callback: Callable, *args):
        """Invoke callback from sync code, supporting async callback returns."""
        result = callback(*args)
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result
    
    async def create_request_async(self, task_id: str, agent_id: str, message: str, 
                                   context: str = "", callback: Optional[Callable] = None) -> ApprovalRequest:
        """Create a new approval request"""
        request = ApprovalRequest(task_id, agent_id, message, context)
        
        with self._lock:
            self.requests[request.request_id] = request
            if callback:
                self._callbacks[request.request_id] = callback
        
        # Optional custom confirmation hook (e.g. Slack workflow).
        await self._run_on_confirm(request)
        
        console.warning(
            "🤚 APPROVAL REQUIRED",
            f"Request ID: {request.request_id} | {message}",
            task_id=task_id,
            agent_id=agent_id
        )
        
        return request
    
    def create_request(self, task_id: str, agent_id: str, message: str, 
                      context: str = "", callback: Optional[Callable] = None) -> ApprovalRequest:
        """Create a new approval request (sync wrapper)"""
        # For backward compatibility - run async version
        coro = self.create_request_async(task_id, agent_id, message, context, callback)

        try:
            asyncio.get_running_loop()
            loop_running = True
        except RuntimeError:
            loop_running = False

        if not loop_running:
            return asyncio.run(coro)

        # Running inside an event loop in this thread: execute on a dedicated
        # thread/loop to avoid blocking the current loop.
        result_container = []
        error_container = []

        def _runner():
            try:
                result_container.append(asyncio.run(coro))
            except Exception as e:
                error_container.append(e)

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join()

        if error_container:
            raise error_container[0]
        return result_container[0]
    
    def wait_for_approval(self, request_id: str) -> bool:
        """Wait for approval indefinitely. Returns True if approved, False if rejected"""
        with self._lock:
            request = self.requests.get(request_id)
        
        if not request:
            return False
        
        # Wait indefinitely until user responds
        while request.is_pending():
            time.sleep(0.5)  # Check every 500ms
        
        # Execute callback if exists
        with self._lock:
            callback = self._callbacks.pop(request_id, None)
            if callback:
                try:
                    self._invoke_callback_sync(callback, request.status, request.response)
                except Exception as e:
                    console.error("Approval callback failed", str(e), 
                                task_id=request.task_id, agent_id=request.agent_id)
        
        if request.status == "approved":
            console.success(
                "✅ APPROVED",
                f"Request: {request.request_id} | Response: {request.response}",
                task_id=request.task_id,
                agent_id=request.agent_id
            )
            return True
        else:
            console.warning(
                "❌ REJECTED",
                f"Request: {request.request_id} | Reason: {request.response}",
                task_id=request.task_id,
                agent_id=request.agent_id
            )
            return False
    
    def get_pending_requests(self, agent_id: Optional[str] = None) -> list:
        """Get all pending approval requests, optionally filtered by agent"""
        with self._lock:
            pending = [
                req for req in self.requests.values() 
                if req.is_pending() and (agent_id is None or req.agent_id == agent_id)
            ]
        return [req.get_info() for req in pending]
    
    def get_pending_count(self, agent_id: Optional[str] = None) -> int:
        """Get count of pending approval requests"""
        return len(self.get_pending_requests(agent_id))
    
    def approve(self, request_id: str, response: str = "Approved") -> bool:
        """Approve a request by ID"""
        with self._lock:
            request = self.requests.get(request_id)
        if request:
            return request.approve(response)
        return False
    
    def reject(self, request_id: str, reason: str = "Rejected") -> bool:
        """Reject a request by ID"""
        with self._lock:
            request = self.requests.get(request_id)
        if request:
            return request.reject(reason)
        return False
    
    def get_request(self, request_id: str) -> Optional[dict]:
        """Get request information by ID"""
        with self._lock:
            request = self.requests.get(request_id)
        return request.get_info() if request else None
    
    def cleanup_old_requests(self, max_age_seconds: int = 3600):
        """Remove old completed/timeout requests"""
        with self._lock:
            current_time = time.time()
            to_remove = [
                rid for rid, req in self.requests.items()
                if req.status != "pending" and (current_time - req.created_at) > max_age_seconds
            ]
            for rid in to_remove:
                del self.requests[rid]
                self._callbacks.pop(rid, None)
            
            if to_remove:
                console.debug("Approval cleanup", f"Removed {len(to_remove)} old requests")
