"""
DriveConnection — Authenticated link to Google Drive.

Supported actions: "search", "get", "create", "update", "delete", "share"

Example:
    drive = DriveConnection(
        service_account="path/to/service-account.json",
        allowed=["search", "get"],   # read-only
    )
"""

from typing import List, Optional, Dict, Any, Union
from .base import GoogleBaseConnection


class DriveConnection(GoogleBaseConnection):
    """
    Google Drive connection.

    Auth methods (use one):
        service_account:   Path to SA JSON key.
        oauth_credentials: Path to client_secrets.json.

    Args:
        actions: List of permitted actions. Omit to allow all.
        name:    Label (default: "drive").
    """

    TOOL_NAME = "drive"
    ALLOWED_ACTIONS = ["search", "get", "create", "update", "delete", "list_permissions", "share", "unshare"]

    def __init__(
        self,
        *,
        service_account: Optional[str] = None,
        oauth_credentials: Optional[str] = None,
        delegated_user: Optional[str] = None,
        allowed: Optional[Union[str, List[str]]] = None,
        name: str = "drive",
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
