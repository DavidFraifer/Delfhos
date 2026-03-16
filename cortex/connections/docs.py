"""
DocsConnection — Authenticated link to Google Docs.

Supported actions: "read", "create", "update", "delete"

Example:
    docs = DocsConnection(
        service_account="path/to/service-account.json",
    )

    # Or with OAuth:
    docs = DocsConnection(
        oauth_credentials="path/to/client_secrets.json",
        allowed=["read"],
    )
"""

from typing import List, Optional, Dict, Any, Union
from .base import GoogleBaseConnection


class DocsConnection(GoogleBaseConnection):
    """
    Google Docs connection.

    Auth methods (use one):
        service_account:   Path to SA JSON key.
        oauth_credentials: Path to client_secrets.json.

    Args:
        actions: ["read", "create", "update", "delete"] — omit to allow all.
        name:    Label (default: "docs").
    """

    TOOL_NAME = "docs"
    ALLOWED_ACTIONS = ["read", "create", "update", "format", "delete"]

    def __init__(
        self,
        *,
        service_account: Optional[str] = None,
        oauth_credentials: Optional[str] = None,
        delegated_user: Optional[str] = None,
        allowed: Optional[Union[str, List[str]]] = None,
        name: str = "docs",
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
