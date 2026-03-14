"""
Docs Tool Documentation
========================
"""


class DocsDoc:
    """API documentation for the Google Docs tool."""

    TOOL_NAME = "docs"

    ACTIONS = ["CREATE", "READ", "UPDATE", "DELETE"]

    ACTION_SUMMARIES = {
        "CREATE": "Create a new Google Doc (visible to user). Returns document ID.",
        "READ":   "Read document content as text.",
        "UPDATE": "Append text or insert/delete content in the document.",
        "DELETE": "Delete a document.",
    }

    PYTHON_API = {
        "CREATE": """\
# docs.create() → str (ID)
doc_id = await docs.create("Title", content="Markdown", desc="Creating")
""",

        "READ": """\
# docs.read() → str (text)
content = await docs.read(doc_id, desc="Reading")
""",

        "UPDATE": """\
# docs.update() — append text
await docs.update(doc_id, "Text", desc="Appending")
""",
    }

    EXAMPLES = {}
