"""Type stubs for cortex — AI agent framework with typed connections."""

from .cortex import Cortex as Cortex
from .connections import (
    GmailConnection as GmailConnection,
    SQLConnection as SQLConnection,
    SheetsConnection as SheetsConnection,
    DriveConnection as DriveConnection,
    CalendarConnection as CalendarConnection,
    DocsConnection as DocsConnection,
    WebSearchConnection as WebSearchConnection,
)

__all__ = [
    "Cortex",
    "GmailConnection",
    "SQLConnection",
    "SheetsConnection",
    "DriveConnection",
    "CalendarConnection",
    "DocsConnection",
    "WebSearchConnection",
]
