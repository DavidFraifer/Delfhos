"""
Calendar Tool Documentation
============================
"""


class CalendarDoc:
    """API documentation for the Google Calendar tool."""

    TOOL_NAME = "calendar"

    ACTIONS = ["LIST", "CREATE", "UPDATE", "DELETE"]

    ACTION_SUMMARIES = {
        "LIST":   "List events in a date range. Returns list of event dicts.",
        "CREATE": "Create a calendar event (supports Meet link, attendees, reminders).",
        "UPDATE": "Modify an existing event's title, times, or attendees.",
        "DELETE": "Remove an event from the calendar.",
    }

    PYTHON_API = {
        "LIST": """\
# calendar.list() → List[Dict] ([{id, summary, start: {dateTime, timeZone}, end: {dateTime, timeZone}, attendees, location}])
events = await calendar.list(start="2026-02-01T00:00:00Z", end="2026-02-28T23:59:59Z", desc="Listing")
""",

        "CREATE": """\
# calendar.create()
await calendar.create(summary="X", start="2026-02-20T09:00:00Z", end="2026-02-20T09:30:00Z", attendees=["x@co.com"], conference=True, desc="Creating")
""",

        "UPDATE": """\
# calendar.update()
await calendar.update(id, summary="New", start="...", end="...", desc="Updating")
""",

        "DELETE": """\
# calendar.delete()
await calendar.delete(id, desc="Deleting")
""",
    }

    EXAMPLES = {}
