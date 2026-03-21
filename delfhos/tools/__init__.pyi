"""Type stubs for delfhos.tools — Pre-built service integrations."""

from delfhos.tool import ToolException as ToolException, tool as tool
from delfhos.tools.native import (
    Calendar as Calendar,
    CalendarTool as CalendarTool,
    Docs as Docs,
    DocsTool as DocsTool,
    Drive as Drive,
    DriveTool as DriveTool,
    Gmail as Gmail,
    GmailTool as GmailTool,
    SQL as SQL,
    SQLTool as SQLTool,
    Sheets as Sheets,
    SheetsTool as SheetsTool,
    WebSearch as WebSearch,
    WebSearchTool as WebSearchTool,
)
from delfhos.tools.mcp import MCP as MCP

__all__ = [
    "tool",
    "ToolException",
    "Gmail",
    "SQL",
    "Sheets",
    "Drive",
    "Calendar",
    "Docs",
    "WebSearch",
    "MCP",
    "GmailTool",
    "SQLTool",
    "SheetsTool",
    "DriveTool",
    "CalendarTool",
    "DocsTool",
    "WebSearchTool",
]
