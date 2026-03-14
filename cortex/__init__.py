"""
Cortex SDK — AI agent framework with typed connections.

Usage:
    from cortex import Cortex
    from cortex.connections import GmailConnection, SQLConnection

    gmail = GmailConnection(credentials={...})
    db    = SQLConnection(url="postgresql://user:pass@host/mydb")

    agent = Cortex(connections=[gmail, db])
    agent.run("Summarize unread emails and cross-reference active users in the DB.")
    agent.stop()

Or with a context manager (auto-start/stop):
    with Cortex(connections=[gmail, db]) as agent:
        agent.run("Send a weekly report to the team.")
        agent.run_and_wait("Upload results to Drive.", timeout=60)

To add a custom connection, see: examples/custom_connection.py
"""

# Suppress noisy TF warnings (may be triggered by transitive deps)
import os
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

from .cortex import Cortex
from .connections import (
    GmailConnection,
    SQLConnection,
    SheetsConnection,
    DriveConnection,
    CalendarConnection,
    DocsConnection,
    WebSearchConnection,
)

__all__ = [
    # Core
    "Cortex",
    # Connections
    "GmailConnection",
    "SQLConnection",
    "SheetsConnection",
    "DriveConnection",
    "CalendarConnection",
    "DocsConnection",
    "WebSearchConnection",
]
