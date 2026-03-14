"""
Sheets Tool Documentation
=========================
"""


class SheetsDoc:
    """API documentation for the Google Sheets tool."""

    TOOL_NAME = "sheets"

    ACTIONS = ["CREATE", "READ", "WRITE"]

    ACTION_SUMMARIES = {
        "CREATE": "Create a new Google Spreadsheet. Returns spreadsheet_id.",
        "READ":   "Read cell data from a spreadsheet. Returns 2D array.",
        "WRITE":  "Write data into a spreadsheet (supports List, Dict list, or CSV string).",
    }

    PYTHON_API = {
        "CREATE": """\
# sheets.create() → str (ID)
sheet_id = await sheets.create("Title", desc="Creating")
""",

        "READ": """\
# sheets.read() → List[List[Any]] (2D array)
data = await sheets.read(sheet_id, range="Sheet1!A1:D20", desc="Reading")
""",

        "WRITE": """\
# sheets.write() — auto-detects form
# List[List]: await sheets.write(sheet_id, [["Name"], ["A"]], sheet="Sheet1", cell="A1", desc="Writing")
# List[Dict]: await sheets.write(sheet_id, [{"name": "A"}], sheet="Sheet1", desc="Writing")
# CSV str: await sheets.write(sheet_id, csv_data, desc="Writing")
""",
    }

    EXAMPLES = {
        "WRITE": """\
sheet_id = await sheets.create("Sales Report", desc="Creating")
await sheets.write(sheet_id, [["Product", "Revenue"], ["Widget A", 1200]], desc="Writing")
""",
    }
