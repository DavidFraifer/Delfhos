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
        actions=["read"],
    )
"""

from typing import List, Optional, Dict, Any, Union
from .base import GoogleBaseConnection


class SheetsConnection(GoogleBaseConnection):
    """
    Google Sheets connection.

    Auth methods (use one):
        service_account:   Path to SA JSON key.
        oauth_credentials: Path to client_secrets.json.

    Args:
        actions: ["read", "write", "create"] — omit to allow all.
        name:    Label (default: "sheets").
    """

    TOOL_NAME = "sheets"

    def __init__(
        self,
        *,
        service_account: Optional[str] = None,
        oauth_credentials: Optional[str] = None,
        delegated_user: Optional[str] = None,
        actions: Optional[List[str]] = None,
        name: str = "sheets",
        metadata: Optional[Dict[str, Any]] = None,
        confirm: Union[str, bool] = False,
    ):
        super().__init__(
            service_account=service_account,
            oauth_credentials=oauth_credentials,
            delegated_user=delegated_user,
            actions=actions,
            name=name,
            metadata=metadata,
            confirm=confirm,
        )
