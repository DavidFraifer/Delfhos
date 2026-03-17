"""
SheetsConnection — Authenticated link to Google Sheets.

Supported actions: "read", "write", "create"

Example:
    sheets = SheetsConnection(
        service_account="path/to/service-account.json",
    )

    # Or with OAuth:
    sheets = SheetsConnection(
        oauth_credentials="path/to/client_secrets.json",
        allow=["read"],
    )
"""

from typing import List, Optional, Dict, Any, Union
from .base import GoogleBaseConnection


class SheetsConnection(GoogleBaseConnection):
    """
    Google Sheets integration for reading and writing spreadsheets.
    
    Example:
        sheets = Sheets(oauth_credentials="client_secrets.json")
        agent = Agent(tools=[sheets, SQL(...)], llm="gemini-3.1-flash-lite-preview")
        agent.run("Pull yesterday's sales from the DB and update the Q3 Summary sheet")
    
    Authentication (choose one):
        service_account: Google Service Account JSON (for servers).
        oauth_credentials: OAuth client_secrets.json (for personal accounts).
    
    Args:
        delegated_user: Email to impersonate (service account + delegation only).
        allow: Restrict actions, e.g., ["read"] blocks writing (default: allow all).
                Supported: "read", "write", "create", "format", "chart", "batch".
        name: Custom label (default: "sheets").
        metadata: Extra info dict for tracking/logging.
    """

    TOOL_NAME = "sheets"
    ALLOWED_ACTIONS = ["read", "write", "create", "format", "chart", "batch"]

    def __init__(
        self,
        *,
        service_account: Optional[str] = None,
        oauth_credentials: Optional[str] = None,
        delegated_user: Optional[str] = None,
        allow: Optional[Union[str, List[str]]] = None,
        name: str = "sheets",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            service_account=service_account,
            oauth_credentials=oauth_credentials,
            delegated_user=delegated_user,
            allow=allow,
            name=name,
            metadata=metadata,
        )
