from cortex.connections.gmail import GmailConnection as Gmail
from cortex.connections.sql import SQLConnection as SQL
from cortex.connections.sheets import SheetsConnection as Sheets
from cortex.connections.drive import DriveConnection as Drive
from cortex.connections.calendar import CalendarConnection as Calendar
from cortex.connections.docs import DocsConnection as Docs
from cortex.connections.websearch import WebSearchConnection as WebSearch

# Keep full names available too for clarity
GmailTool = Gmail
SQLTool = SQL
SheetsTool = Sheets
DriveTool = Drive
CalendarTool = Calendar
DocsTool = Docs
WebSearchTool = WebSearch

__all__ = [
    "Gmail",
    "SQL",
    "Sheets",
    "Drive",
    "Calendar",
    "Docs",
    "WebSearch",
    "GmailTool",
    "SQLTool",
    "SheetsTool",
    "DriveTool",
    "CalendarTool",
    "DocsTool",
    "WebSearchTool",
]
