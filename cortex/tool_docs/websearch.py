"""
WebSearch Tool Documentation
=============================
"""


class WebSearchDoc:
    """API documentation for the Web Search tool."""

    TOOL_NAME = "websearch"

    ACTIONS = ["SEARCH"]

    ACTION_SUMMARIES = {
        "SEARCH": "Search the web. Request specific output formats (JSON, numbers, lists, etc.) in the query for structured results.",
    }

    PYTHON_API = {
        "SEARCH": """\
# Basic search
results = await websearch.search("Python async best practices", desc="Researching")

# Structured extraction for downstream logic (recommended)
raw = await websearch.search(
    "Current 30-year mortgage rate USA. Return ONLY JSON: {\"interest_rate_percent\": number}",
    desc="Getting rate"
)
rate = float(json.loads(raw)["interest_rate_percent"])
""",
    }

    EXAMPLES = {}

