import unittest

from cortex._engine.tools.tool_registry import build_prefilter_prompt


class FakeConn:
    def __init__(self, connection_name, tool_name, description=""):
        self.connection_name = connection_name
        self.tool_name = tool_name
        self.metadata = {"description": description}


class TestPrefilterCompaction(unittest.TestCase):
    def test_prompt_compacts_long_task(self):
        long_task = "A" * 3000
        prompt = build_prefilter_prompt(long_task, {"gmail": {"READ"}}, connections=[])
        self.assertIn("...[truncated]", prompt)

    def test_prompt_keeps_output_contract(self):
        prompt = build_prefilter_prompt("Read inbox", {"gmail": {"READ"}}, connections=[])
        self.assertIn("ANSWER:", prompt)
        self.assertIn("<ConnectionOrTool>:ACTION", prompt)

    def test_connection_description_is_compacted(self):
        long_desc = "x" * 200
        conns = [FakeConn("Work Gmail", "gmail", long_desc)]
        prompt = build_prefilter_prompt("Read inbox", {"gmail": {"READ"}}, connections=conns)
        self.assertIn("Work Gmail", prompt)
        self.assertIn("...", prompt)


if __name__ == "__main__":
    unittest.main()
