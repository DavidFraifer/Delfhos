"""delfhos.tools — Pre-built service integrations (Gmail, Drive, Sheets, SQL, etc).

These are high-level tool wrappers that handle authentication and API calls.
All support the `allow` parameter to restrict permissions::

    from delfhos.tools import Gmail, Drive, Sheets, SQL

    gmail = Gmail(oauth_credentials="secrets.json", allow=["read"])  # read-only
    drive = Drive(oauth_credentials="secrets.json", allow=["search", "get"])  # no delete
    sheets = Sheets(oauth_credentials="secrets.json", allow=["read", "write"])
    db = SQL(url="postgresql://user:pass@localhost/mydb", allow=["schema", "query"])

See cortex.connections for internal implementation details.

Short names (Gmail, Drive) are preferred over long names (GmailTool, DriveTool).
"""

from delfhos.tool import tool, ToolException

# Built-in native tools
from .native import (
    Gmail,
    SQL,
    Sheets,
    Drive,
    Calendar,
    Docs,
    WebSearch,
    GmailTool,
    SQLTool,
    SheetsTool,
    DriveTool,
    CalendarTool,
    DocsTool,
    WebSearchTool,
)

# MCP tools
from .mcp import MCP

__all__ = [
    # Base
    "tool",
    "ToolException",
    # Service tools (short names)
    "Gmail",
    "SQL",
    "Sheets",
    "Drive",
    "Calendar",
    "Docs",
    "WebSearch",
    "MCP",
    # Service tools (long names)
    "GmailTool",
    "SQLTool",
    "SheetsTool",
    "DriveTool",
    "CalendarTool",
    "DocsTool",
    "WebSearchTool",
]
