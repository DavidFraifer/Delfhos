"""
delfhos.connections — Internal re-exports of cortex service connection classes.

Prefer importing from delfhos.tools instead:
    from delfhos.tools import Gmail, SQL, Sheets, WebSearch
"""

# Re-export everything from the internal cortex.connections package
from cortex.connections.gmail import GmailConnection
from cortex.connections.sql import SQLConnection
from cortex.connections.sheets import SheetsConnection
from cortex.connections.drive import DriveConnection
from cortex.connections.calendar import CalendarConnection
from cortex.connections.docs import DocsConnection
from cortex.connections.websearch import WebSearchConnection
from cortex.connections.base import BaseConnection, GoogleBaseConnection, AuthType, ConnectionStatus

__all__ = [
    "GmailConnection",
    "SQLConnection",
    "SheetsConnection",
    "DriveConnection",
    "CalendarConnection",
    "DocsConnection",
    "WebSearchConnection",
    "BaseConnection",
    "GoogleBaseConnection",
    "AuthType",
    "ConnectionStatus",
]
