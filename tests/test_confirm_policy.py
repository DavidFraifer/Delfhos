import unittest

from cortex._engine.agent import Agent
from cortex._engine.tools.tool_libraries import _requires_approval, _resolve_effective_confirm_policy
from delfhos.sandbox import MockDatabase, MockEmail


class TestConfirmPolicy(unittest.TestCase):
    def test_agent_allows_empty_tools_for_llm_only_mode(self):
        # No tools, no on_confirm → no approval manager needed
        agent = Agent(tools=[], llm="gemini-3.1-flash-lite-preview")

        self.assertEqual(agent.tools, [])
        self.assertFalse(agent.enable_human_approval)
        self.assertIsNone(agent.orchestrator.approval_manager)

    def test_string_policy_exact_match(self):
        self.assertTrue(_requires_approval("write", "write"))
        self.assertFalse(_requires_approval("write", "delete"))
        self.assertFalse(_requires_approval("write", "read"))

    def test_list_policy_matches_in(self):
        self.assertTrue(_requires_approval(["write", "delete"], "delete"))
        self.assertTrue(_requires_approval(["write", "delete"], "write"))
        self.assertFalse(_requires_approval(["write", "delete"], "read"))

    def test_all_policy_requires_any_operation(self):
        self.assertTrue(_requires_approval("all", "read"))
        self.assertTrue(_requires_approval("all", "write"))
        self.assertTrue(_requires_approval("all", "delete"))

    def test_false_policy_never_requires(self):
        self.assertFalse(_requires_approval(False, "read"))
        self.assertFalse(_requires_approval(False, "write"))
        self.assertFalse(_requires_approval(False, "delete"))

    def test_tool_hard_override_beats_agent_policy(self):
        policy, hard_override = _resolve_effective_confirm_policy(
            fallback_confirm_policy="write",
            agent_confirm_policy=False,
            tool_confirm_policy=True,
        )
        self.assertTrue(hard_override)
        self.assertEqual(policy, True)

    def test_per_tool_confirm_enables_approval_manager(self):
        # MockEmail with confirm=["send"] should enable approval manager
        mock_email = MockEmail(confirm=["send"])
        agent = Agent(tools=[mock_email], llm="gemini-3.1-flash-lite-preview")

        self.assertTrue(agent.enable_human_approval)
        self.assertIsNotNone(agent.orchestrator.approval_manager)

    def test_per_tool_confirm_on_db_enables_approval_manager(self):
        mock_db = MockDatabase(confirm=["write"])
        agent = Agent(tools=[mock_db], llm="gemini-3.1-flash-lite-preview")

        self.assertTrue(agent.enable_human_approval)
        self.assertIsNotNone(agent.orchestrator.approval_manager)

    def test_no_explicit_confirm_on_tools_still_enables_approval_manager(self):
        # Tools without explicit confirm= still enable the approval manager because
        # confirm defaults to True now
        mock_email = MockEmail()
        agent = Agent(tools=[mock_email], llm="gemini-3.1-flash-lite-preview")

        self.assertTrue(agent.enable_human_approval)
        self.assertIsNotNone(agent.orchestrator.approval_manager)

    def test_on_confirm_callback_enables_approval_without_tool_confirm(self):
        callback = lambda req_id, msg: True
        agent = Agent(
            tools=["websearch"],
            llm="gemini-3.1-flash-lite-preview",
            on_confirm=callback,
        )
        self.assertTrue(agent.enable_human_approval)
        self.assertIsNotNone(agent.orchestrator.approval_manager)

    def test_connection_confirm_list_is_stored(self):
        mock_email = MockEmail(confirm=["send"])
        self.assertEqual(mock_email.confirm, ["send"])

    def test_connection_confirm_defaults_to_true(self):
        mock_email = MockEmail()
        self.assertTrue(mock_email.confirm)
        self.assertEqual(mock_email.confirm, True)


if __name__ == "__main__":
    unittest.main()
