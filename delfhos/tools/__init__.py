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

# All tool names that are lazily forwarded to .native or .mcp
_LAZY_NAMES = {
    "Gmail", "SQL", "Sheets", "Drive", "Calendar", "Docs", "WebSearch",
    "GmailTool", "SQLTool", "SheetsTool", "DriveTool", "CalendarTool", "DocsTool", "WebSearchTool",
    "MCP", "APITool",
}


def __getattr__(name):
    if name in _LAZY_NAMES:
        if name == "MCP":
            from .mcp import MCP
            globals()["MCP"] = MCP
            return MCP
        if name == "APITool":
            from cortex.connections.api import APITool
            globals()["APITool"] = APITool
            return APITool
        # Forward to native module (which itself is lazy)
        from . import native
        klass = getattr(native, name)
        globals()[name] = klass
        return klass
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted({"tool", "ToolException"} | _LAZY_NAMES)


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
    "APITool",
    # Service tools (long names)
    "GmailTool",
    "SQLTool",
    "SheetsTool",
    "DriveTool",
    "CalendarTool",
    "DocsTool",
    "WebSearchTool",
]

