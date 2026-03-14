"""
WebSearch Tool Documentation
=============================
"""


class WebSearchDoc:
    """API documentation for the Web Search tool."""

    TOOL_NAME = "websearch"

    ACTIONS = ["SEARCH"]

    ACTION_SUMMARIES = {
        "SEARCH": "Search the web and return a comprehensive text summary of results.",
    }

    PYTHON_API = {
        "SEARCH": """\
# websearch.search() → str (summary)
results = await websearch.search("Python 2026", max_results=5, desc="Searching")
""",
    }

    EXAMPLES = {}
