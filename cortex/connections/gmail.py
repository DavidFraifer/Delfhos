"""
GmailConnection — Authenticated link to a Gmail account.

Supported actions: "read", "send"

Example (Service Account — recommended for servers):
    from cortex.connections import GmailConnection

    gmail = GmailConnection(
        service_account="path/to/service-account.json",
        delegated_user="admin@company.com",
        allowed=["read"],
    )

Example (OAuth — for personal accounts):
    gmail = GmailConnection(
        oauth_credentials="path/to/client_secrets.json",
        allowed=["read", "send"],
    )
"""

from typing import List, Optional, Dict, Any, Union
from .base import GoogleBaseConnection


class GmailConnection(GoogleBaseConnection):
    """
    Gmail connection.

    Auth methods (use one):
        service_account:   Path to SA JSON key (for servers / Workspace).
        oauth_credentials: Path to client_secrets.json (for personal accounts).

    Args:
        delegated_user: Email to impersonate (service account only).
        actions:        ["read", "send"] — restricts what the agent can do.
                        Omit to allow all actions.
        name:           Label for this connection (default: "gmail").
        metadata:       Extra info, e.g. {"description": "Work inbox"}.
    """

    TOOL_NAME = "gmail"
    ALLOWED_ACTIONS = ["read", "send"]

    def __init__(
        self,
        *,
        service_account: Optional[str] = None,
        oauth_credentials: Optional[str] = None,
        delegated_user: Optional[str] = None,
        allowed: Optional[Union[str, List[str]]] = None,
        name: str = "gmail",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            service_account=service_account,
            oauth_credentials=oauth_credentials,
            delegated_user=delegated_user,
            allowed=allowed,
            name=name,
            metadata=metadata,
        )
