"""
GmailConnection — Authenticated link to a Gmail account.

Supported actions: "read", "send"

Example (Service Account — recommended for servers):
    from cortex.connections import GmailConnection

    gmail = GmailConnection(
        service_account="path/to/service-account.json",
        delegated_user="admin@company.com",
        allow=["read"],
    )

Example (OAuth — for personal accounts):
    gmail = GmailConnection(
        oauth_credentials="path/to/client_secrets.json",
        allow=["read", "send"],
    )
"""

from typing import List, Optional, Dict, Any, Union
from .base import GoogleBaseConnection


class GmailConnection(GoogleBaseConnection):
    """
    Gmail integration for reading emails and sending messages via agent.
    
    Example (service account):
        gmail = Gmail(service_account="sa.json", delegated_user="user@workspace.com")
        agent = Agent(tools=[gmail], llm="gemini-3.1-flash-lite-preview")
        agent.run("Reply to all unread emails with a summary of today's meetings")
    
    Example (personal OAuth):
        gmail = Gmail(oauth_credentials="client_secrets.json")
        agent.run("Forward important emails to alice@co.com")
    
    Authentication (choose one):
        service_account: Path to Google Service Account JSON (for Workspace/servers).
        oauth_credentials: Path to OAuth client_secrets.json (for personal accounts).
    
    Args:
        delegated_user: Email to impersonate (service account only; requires delegation).
        allow: Restrict actions, e.g., ["read"] prevents sending (default: allow all).
        confirm: Require human approval before executing listed actions, e.g. ["send"].
        name: Custom label (default: "gmail").
        metadata: Extra info dict for tracking/logging.
    """

    TOOL_NAME = "gmail"
    ALLOWED_ACTIONS = ["read", "send"]

    def __init__(
        self,
        *,
        service_account: Optional[str] = None,
        oauth_credentials: Optional[str] = None,
        delegated_user: Optional[str] = None,
        allow: Optional[Union[str, List[str]]] = None,
        confirm: Union[bool, List[str], None] = True,
        name: str = "gmail",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            service_account=service_account,
            oauth_credentials=oauth_credentials,
            delegated_user=delegated_user,
            allow=allow,
            confirm=confirm,
            name=name,
            metadata=metadata,
        )
