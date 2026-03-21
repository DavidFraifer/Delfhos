import unittest

from cortex._engine.tools.tool_registry import build_prefilter_prompt, filter_selected_actions


class FakeConn:
    def __init__(self, connection_name, tool_name, description="", allow=None):
        self.connection_name = connection_name
        self.tool_name = tool_name
        self.metadata = {"description": description}
        self.allow = allow


class TestPrefilterCompaction(unittest.TestCase):
    def test_prompt_compacts_long_task(self):
        long_task = "A" * 3000
        prompt = build_prefilter_prompt(long_task, {"gmail": {"READ"}}, connections=[])
        self.assertIn("...[truncated]", prompt)

    def test_prompt_keeps_output_contract(self):
        prompt = build_prefilter_prompt("Read inbox", {"gmail": {"READ"}}, connections=[])
        self.assertIn("ANSWER:", prompt)
        self.assertIn("<Tool>:<METHOD or ACTION>", prompt)

    def test_connection_description_is_compacted(self):
        long_desc = "x" * 200
        conns = [FakeConn("Work Gmail", "gmail", long_desc)]
        prompt = build_prefilter_prompt("Read inbox", {"gmail": {"READ"}}, connections=conns)
        self.assertIn("Work Gmail", prompt)
        self.assertIn("...", prompt)

    def test_connection_prompt_respects_per_connection_allow(self):
        conns = [
            FakeConn("ReadOnly Gmail", "gmail", allow=["read"]),
            FakeConn("SendOnly Gmail", "gmail", allow=["send"]),
        ]
        prompt = build_prefilter_prompt(
            "Read and send",
            {"gmail": {"READ", "SEND"}},
            connections=conns,
        )
        self.assertIn("ReadOnly Gmail (tool=gmail) call: read()", prompt)
        self.assertIn("SendOnly Gmail (tool=gmail) call: send()", prompt)

    def test_filter_selected_actions_blocks_disallowed(self):
        selected = ["gmail:READ", "gmail:SEND", "llm:CALL"]
        allowed_map = {
            "gmail": {"READ"},
            "llm": {"CALL"},
        }
        allowed, blocked = filter_selected_actions(selected, allowed_map)
        self.assertEqual(allowed, ["gmail:READ", "llm:CALL"])
        self.assertEqual(blocked, ["gmail:SEND"])


if __name__ == "__main__":
    unittest.main()
