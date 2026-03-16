import unittest

from cortex._engine.agent import Agent
from cortex._engine.tools.tool_libraries import _requires_approval, _resolve_effective_confirm_policy


class TestConfirmPolicy(unittest.TestCase):
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

    def test_agent_policy_overrides_fallback(self):
        policy, hard_override = _resolve_effective_confirm_policy(
            fallback_confirm_policy="write",
            agent_confirm_policy="delete",
            tool_confirm_policy=False,
        )
        self.assertFalse(hard_override)
        self.assertEqual(policy, "delete")

    def test_tool_hard_override_beats_agent_policy(self):
        policy, hard_override = _resolve_effective_confirm_policy(
            fallback_confirm_policy="write",
            agent_confirm_policy=False,
            tool_confirm_policy=True,
        )
        self.assertTrue(hard_override)
        self.assertEqual(policy, True)

    def test_agent_default_confirm_enables_approval_without_callback(self):
        agent = Agent(tools=["websearch"], llm="gemini-3.1-flash-lite-preview")

        self.assertEqual(agent.confirm_policy, ["write", "delete"])
        self.assertTrue(agent.enable_human_approval)
        self.assertIsNotNone(agent.orchestrator.approval_manager)

    def test_summarizer_llm_defaults_and_override(self):
        default_agent = Agent(tools=["websearch"], llm="gpt-5.4")
        self.assertEqual(default_agent.light_llm, "gpt-5.4")
        self.assertEqual(default_agent.summarizer_llm, "gpt-5.4")

        custom_agent = Agent(
            tools=["websearch"],
            llm="gpt-5.4",
            summarizer_llm="openai/gpt-4.1-mini",
        )
        self.assertEqual(custom_agent.summarizer_llm, "openai/gpt-4.1-mini")


if __name__ == "__main__":
    unittest.main()
