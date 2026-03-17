"""
DriveConnection — Authenticated link to Google Drive.

Supported actions: "search", "get", "create", "update", "delete", "share"

Example:
    drive = DriveConnection(
        service_account="path/to/service-account.json",
        allow=["search", "get"],   # read-only
    )
"""

from typing import List, Optional, Dict, Any, Union
from .base import GoogleBaseConnection


class DriveConnection(GoogleBaseConnection):
    """
    Google Drive integration for managing files and folders.
    
    Example:
        drive = Drive(oauth_credentials="client_secrets.json")
        agent = Agent(tools=[drive, Gmail()], llm="gemini-3.1-flash-lite-preview")
        agent.run("Archive Q3 reports into Completed/Q3 folder and send summary to finance@co.com")
    
    Authentication (choose one):
        service_account: Google Service Account JSON (for servers).
        oauth_credentials: OAuth client_secrets.json (for personal accounts).
    
    Args:
        delegated_user: Email to impersonate (service account + delegation only).
        allow: Restrict actions, e.g., ["search", "get"] blocks create/delete (default: allow all).
        name: Custom label (default: "drive").
        metadata: Extra info dict for tracking/logging.
    """

    TOOL_NAME = "drive"
    ALLOWED_ACTIONS = ["search", "get", "create", "update", "delete", "list_permissions", "share", "unshare"]

    def __init__(
        self,
        *,
        service_account: Optional[str] = None,
        oauth_credentials: Optional[str] = None,
        delegated_user: Optional[str] = None,
        allow: Optional[Union[str, List[str]]] = None,
        name: str = "drive",
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
