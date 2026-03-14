"""
Drive Tool Documentation
========================
"""


class DriveDoc:
    """API documentation for the Google Drive tool."""

    TOOL_NAME = "drive"

    ACTIONS = ["SEARCH", "GET", "CREATE", "UPDATE", "DELETE", "SHARE"]

    ACTION_SUMMARIES = {
        "SEARCH": "Find files/folders by name or type. Returns file_id or None.",
        "GET":    "Download/read a file by ID.",
        "CREATE": "Create folders only (NOT Docs/Sheets — use docs or sheets for those).",
        "UPDATE": "Rename or move a file.",
        "DELETE": "Trash or permanently delete a file.",
        "SHARE":  "Share a file with a user, group, or domain.",
    }

    PYTHON_API = {
        "SEARCH": """\
# drive.search() → str (ID) or None
file_id = await drive.search(name="Report", mime_type="spreadsheet", desc="Searching")
# mime_type: "spreadsheet", "document", "presentation", "folder"
""",

        "GET": """\
# drive.get() → bytes or str
content = await drive.get(file_id, desc="Downloading")
""",

        "CREATE": """\
# drive.create() — folders only
folder_id = await drive.create(name="Folder", mime_type="application/vnd.google-apps.folder", desc="Creating")
""",

        "SHARE": """\
# drive.share()
await drive.share(file_id=id, role="reader", type="user", email="x@co.com", desc="Sharing")
# role: "reader", "commenter", "writer", "owner"
""",
    }

    EXAMPLES = {}
