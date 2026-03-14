"""
SQL Tool Documentation
======================

Defines the Python API that the Cortex engine injects into code-generation prompts.
This is the "contract" between the LLM and the SQL tool implementation.

To add or modify SQL capabilities, edit PYTHON_API and ACTIONS below.
"""


class SQLDoc:
    """API documentation for the SQL (database) tool."""

    TOOL_NAME = "sql"

    ACTIONS = ["SCHEMA", "QUERY"]

    # ── Compact summaries used by the prefilter LLM ─────────────────────────
    ACTION_SUMMARIES = {
        "SCHEMA": "Get database structure — tables, columns, types, primary/foreign keys",
        "QUERY":  "Execute a read-only SELECT query. Returns list of row dicts or CSV string.",
    }

    # ── Full Python API injected into code-generation prompts ───────────────
    PYTHON_API = {
        "SCHEMA": """\
# sql.schema() → str
schema = await sql.schema(desc="Getting schema")
""",

        "QUERY": """\
# sql.query() → List[Dict] ([{"col": val, ...}])
rows = await sql.query("SELECT * FROM x", desc="Querying")
# CSV export: csv_data = await sql.query("SELECT *", as_csv=True, desc="Exporting") → str
# RULES: Use EXACT column names. Read-only PostgreSQL.
""",
    }

    # ── Short examples ───────────────────────────────────────────────────────
    EXAMPLES = {
        "QUERY": """\
# Get top 10 users and load into Sheets
csv_data = await sql.query("SELECT * FROM users ORDER BY created_at DESC LIMIT 10",
                            as_csv=True, desc="Fetching users")
sheet_id = await sheets.create("User Report", desc="Creating sheet")
await sheets.write(sheet_id, csv_data, desc="Loading data")
""",
    }
