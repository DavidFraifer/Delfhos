"""
cortex.connections — Typed connections to external services.

Each connection class wraps authentication credentials and optionally
restricts which actions the agent is allowed to perform.

The same tool can have multiple connections (e.g. two Gmail accounts):
    work_gmail    = GmailConnection(credentials=work_creds,    name="work")
    personal_gmail = GmailConnection(credentials=personal_creds, name="personal")

    agent = Cortex(connections=[work_gmail, personal_gmail, db])

Usage:
    from cortex.connections import GmailConnection, SQLConnection, WebSearchConnection

Available connections:
    GmailConnection       — Gmail via OAuth2
    SheetsConnection      — Google Sheets via OAuth2
    DriveConnection       — Google Drive via OAuth2
    CalendarConnection    — Google Calendar via OAuth2
    DocsConnection        — Google Docs via OAuth2
    SQLConnection         — PostgreSQL database via connection URL
    WebSearchConnection   — Web search (no auth required)
"""

from .gmail import GmailConnection
from .sql import SQLConnection
from .sheets import SheetsConnection
from .drive import DriveConnection
from .calendar import CalendarConnection
from .docs import DocsConnection
from .websearch import WebSearchConnection
from .base import BaseConnection, GoogleBaseConnection, AuthType, ConnectionStatus
from .mcp import MCP

__all__ = [
    "GmailConnection",
    "SQLConnection",
    "SheetsConnection",
    "DriveConnection",
    "CalendarConnection",
    "DocsConnection",
    "WebSearchConnection",
    "MCP",
    "BaseConnection",
    "GoogleBaseConnection",
    "AuthType",
    "ConnectionStatus",
]
