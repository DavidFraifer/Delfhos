import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from cortex._engine.core.approval_manager import ApprovalManager


class TestApprovalManager(unittest.TestCase):
    def test_warning_printed_before_confirmation_flow(self):
        manager = ApprovalManager()
        call_order = []

        async def fake_run_on_confirm(_request):
            call_order.append("confirm")

        manager._run_on_confirm = fake_run_on_confirm

        with patch("cortex._engine.core.approval_manager.console.warning", side_effect=lambda *args, **kwargs: call_order.append("warning")):
            asyncio.run(
                manager.create_request_async(
                    task_id="task-order",
                    agent_id="agent-1",
                    message="Order check",
                )
            )

        self.assertGreaterEqual(len(call_order), 2)
        self.assertEqual(call_order[0], "warning")
        self.assertEqual(call_order[1], "confirm")

    def test_on_confirm_async_callable_object_auto_approves(self):
        class AsyncApprover:
            async def __call__(self, _request):
                await asyncio.sleep(0)
                return True

        manager = ApprovalManager(on_confirm=AsyncApprover())

        request = asyncio.run(
            manager.create_request_async(
                task_id="task-on-confirm-async-callable",
                agent_id="agent-1",
                message="Auto approve via async callable object",
            )
        )

        self.assertEqual(request.status, "approved")
        self.assertTrue(manager.wait_for_approval(request.request_id))

    def test_wait_for_approval_supports_async_callback(self):
        manager = ApprovalManager()
        callback_calls = []
        manager._is_interactive_stdin = lambda: False

        async def decision_callback(status, response):
            await asyncio.sleep(0)
            callback_calls.append((status, response))

        request = asyncio.run(
            manager.create_request_async(
                task_id="task-cb-async",
                agent_id="agent-1",
                message="Need approval",
                callback=decision_callback,
            )
        )

        self.assertTrue(manager.reject(request.request_id, "Denied"))
        self.assertFalse(manager.wait_for_approval(request.request_id))
        self.assertEqual(callback_calls, [("rejected", "Denied")])


    def test_wait_for_approval_invokes_callback_only_once(self):
        manager = ApprovalManager()
        callback_calls = []
        manager._is_interactive_stdin = lambda: False

        request = asyncio.run(
            manager.create_request_async(
                task_id="task-cb-once",
                agent_id="agent-1",
                message="Need approval",
                callback=lambda status, response: callback_calls.append((status, response)),
            )
        )

        self.assertTrue(manager.approve(request.request_id, "OK"))

        first_wait = manager.wait_for_approval(request.request_id)
        second_wait = manager.wait_for_approval(request.request_id)

        self.assertTrue(first_wait)
        self.assertTrue(second_wait)
        self.assertEqual(callback_calls, [("approved", "OK")])


    def test_on_confirm_bool_auto_approves_without_manual_step(self):
        manager = ApprovalManager(on_confirm=lambda _request: True)

        request = asyncio.run(
            manager.create_request_async(
                task_id="task-on-confirm",
                agent_id="agent-1",
                message="Auto approve",
            )
        )

        self.assertEqual(request.status, "approved")
        self.assertTrue(manager.wait_for_approval(request.request_id))

    def test_on_confirm_tuple_auto_rejects_with_reason(self):
        manager = ApprovalManager(on_confirm=lambda _request: (False, "Denied by policy"))

        request = asyncio.run(
            manager.create_request_async(
                task_id="task-on-confirm-tuple",
                agent_id="agent-1",
                message="Tuple reject",
            )
        )

        self.assertEqual(request.status, "rejected")
        self.assertEqual(request.response, "Denied by policy")
        self.assertFalse(manager.wait_for_approval(request.request_id))

    def test_default_stdin_fallback_auto_approves_when_interactive(self):
        manager = ApprovalManager()
        manager._is_interactive_stdin = lambda: True

        with patch.object(manager, "_stdin_confirm", AsyncMock(return_value=True)):
            request = asyncio.run(
                manager.create_request_async(
                    task_id="task-stdin-default",
                    agent_id="agent-1",
                    message="Need default stdin approval",
                )
            )

        self.assertEqual(request.status, "approved")
        self.assertTrue(manager.wait_for_approval(request.request_id))

    def test_on_confirm_is_serialized_for_concurrent_requests(self):
        active = 0
        max_active = 0

        async def on_confirm(_request):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.02)
            active -= 1
            return True

        manager = ApprovalManager(on_confirm=on_confirm)

        async def _create_many():
            return await asyncio.gather(
                manager.create_request_async("task-1", "agent-1", "approve 1"),
                manager.create_request_async("task-2", "agent-1", "approve 2"),
                manager.create_request_async("task-3", "agent-1", "approve 3"),
            )

        requests = asyncio.run(_create_many())

        self.assertEqual(max_active, 1)
        self.assertTrue(all(r.status == "approved" for r in requests))


if __name__ == "__main__":
    unittest.main()
