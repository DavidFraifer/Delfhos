import unittest
import asyncio

from delfhos.tool import Tool, ToolException, tool


class TestCustomToolConfirm(unittest.TestCase):
    def test_direct_tool_constructor_is_disabled(self):
        def sample(name: str) -> str:
            return name

        with self.assertRaises(TypeError):
            Tool(name="sample", func=sample)

    def test_decorator_sets_confirm_and_kind(self):
        @tool(confirm=True)
        def remove_item(item_id: str) -> str:
            return item_id

        self.assertTrue(remove_item.confirm)

    def test_decorator_defaults_do_require_confirm(self):
        @tool
        def read_item(item_id: str) -> str:
            return item_id

        self.assertTrue(read_item.confirm)

    def test_return_errors_alias_maps_to_tool_error_result(self):
        @tool(return_errors=True)
        def fail_tool() -> str:
            raise ToolException("boom")

        result = asyncio.run(fail_tool.execute())
        self.assertEqual(result, "Tool error: boom")


if __name__ == "__main__":
    unittest.main()
