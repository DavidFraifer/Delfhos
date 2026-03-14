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
