"""
Files Tool Documentation
=========================

The Files tool is built-in — no Connection required.
Used to read uploaded files (CSV, Excel, PDF, images) and save intermediate outputs.
"""


class FilesDoc:
    """API documentation for the built-in Files tool."""

    TOOL_NAME = "files"

    ACTIONS = ["READ", "SAVE", "LIST"]

    ACTION_SUMMARIES = {
        "READ": "Read an uploaded file. CSV → List[Dict], Excel → List[Dict], image → bytes for LLM.",
        "SAVE": "Save an output file locally (HIDDEN from user — use docs/sheets/print to share results).",
        "LIST": "List all uploaded files available for this task.",
    }

    PYTHON_API = {
        "READ": """\
# files.read()
data = await files.read("data.csv", desc="Reading CSV") # → List[Dict]
data = await files.read("report.xlsx", desc="Reading Excel") # → List[Dict]
img = await files.read("photo.png", for_llm=True, desc="Image") # → bytes (for llm)
""",

        "SAVE": """\
# files.save() — HIDDEN from user without docs/sheets/print
await files.save("output.csv", [{"name": "A"}], desc="Saving")
# Auto-converts: list[dict] → CSV/Excel, dict → JSON. NO pandas.
""",

        "LIST": """\
# files.list() → List[Dict] [{filename, file_type, size_bytes, path}]
uploaded = await files.list()
""",
    }

    EXAMPLES = {}
