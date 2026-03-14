"""
Gmail Tool Documentation
========================

Defines the Python API that the Cortex engine injects into code-generation prompts.
This is the "contract" between the LLM and the Gmail tool implementation.

To add or modify Gmail capabilities, edit PYTHON_API and ACTIONS below.
"""


class GmailDoc:
    """API documentation for the Gmail tool."""

    TOOL_NAME = "gmail"

    ACTIONS = ["READ", "SEND"]

    # ── Compact summaries used by the prefilter LLM (~10 tokens each) ──────────
    ACTION_SUMMARIES = {
        "READ": "Search/read emails → list of email dicts with id, subject, from_email, body, date",
        "SEND": "Send an email to one or more recipients",
    }

    # ── Full Python API injected into code-generation prompts ──────────────────
    PYTHON_API = {
        "READ": """\
# gmail.read() → List[Dict] (includes attachments)
emails = await gmail.read(max_results=10, query="is:unread", desc="Reading")
# Returns: [{id, subject, from_email, to, date, body, snippet,
#            attachments: [{attachment_id, filename, mime_type, size}]}]
# Queries: "from:x" "subject:x" "has:attachment" "newer_than:Y-M-D" "in:sent" "label:work"
# Download: paths = await gmail.download_attachments(email, desc="Downloading")
# NOTE: UI card shown automatically—NO need to print full body.
""",

        "SEND": """\
# gmail.send() → dict (confirmation)
await gmail.send(to="x@co.com", subject="Hi", body="Text", cc="y@co.com", bcc="z@co.com", attachments=["/path"], desc="Sending")
""",
    }

    # ── Short examples used alongside the API docs ─────────────────────────────
    EXAMPLES = {
        "READ": """\
# Read unread emails with attachments
emails = await gmail.read(max_results=5, query="is:unread has:attachment", desc="Fetching")
for email in emails:
    paths = await gmail.download_attachments(email, desc="Downloading")
""",

        "SEND": """\
# Reply to the last email
emails = await gmail.read(max_results=1, desc="Finding last email")
if emails:
    await gmail.send(to=emails[0]["from_email"], subject="Re: " + emails[0]["subject"],
                     body="Thanks!", desc="Replying")
""",
    }
