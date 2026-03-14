import unittest

from cortex._engine.tools.tool_libraries import (
    _build_file_preview_metadata,
    _format_size_display,
    _truncate_preview_text,
)


class TestFilePreviewHelpers(unittest.TestCase):
    def test_truncate_preview_text_adds_suffix(self):
        text = "a" * 1005
        preview = _truncate_preview_text(text, limit=1000)
        self.assertTrue(preview.endswith("\n\n... (truncated)"))
        self.assertEqual(len(preview), 1017)

    def test_format_size_display(self):
        self.assertEqual(_format_size_display(512), "512 B")
        self.assertEqual(_format_size_display(2048), "2.00 KB")
        self.assertEqual(_format_size_display(2 * 1024 * 1024), "2.00 MB")

    def test_build_csv_preview_metadata(self):
        content = "name,age\nAna,30\nLuis,25"
        md = _build_file_preview_metadata(content, "people.csv")

        self.assertTrue(md["can_preview"])
        self.assertTrue(md["is_table_format"])
        self.assertIsNone(md["preview_content"])
        self.assertEqual(md["preview_table_data"][0], ["name", "age"])

    def test_build_json_object_preview_metadata(self):
        content = '{"name":"Ana","age":30}'
        md = _build_file_preview_metadata(content, "people.json")

        self.assertTrue(md["can_preview"])
        self.assertFalse(md["is_table_format"])
        self.assertIsNotNone(md["preview_content"])
        self.assertIsNone(md["preview_table_data"])

    def test_build_binary_preview_metadata(self):
        md = _build_file_preview_metadata(b"\x00\x01", "image.png")

        self.assertFalse(md["can_preview"])
        self.assertFalse(md["is_table_format"])
        self.assertIsNone(md["preview_content"])
        self.assertIsNone(md["preview_table_data"])


if __name__ == "__main__":
    unittest.main()
