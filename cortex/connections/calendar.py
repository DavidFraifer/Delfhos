"""
CalendarConnection — Authenticated link to Google Calendar.

Supported actions: "list", "create", "update", "delete"

Example:
    calendar = CalendarConnection(
        service_account="path/to/service-account.json",
        delegated_user="admin@company.com",
        actions=["list"],  # read-only
    )
"""

from typing import List, Optional, Dict, Any, Union
from .base import GoogleBaseConnection


class CalendarConnection(GoogleBaseConnection):
    """
    Google Calendar connection.

    Auth methods (use one):
        service_account:   Path to SA JSON key.
        oauth_credentials: Path to client_secrets.json.

    Args:
        actions: ["list", "create", "update", "delete"] — omit to allow all.
        name:    Label (default: "calendar").
    """

    TOOL_NAME = "calendar"

    def __init__(
        self,
        *,
        service_account: Optional[str] = None,
        oauth_credentials: Optional[str] = None,
        delegated_user: Optional[str] = None,
        actions: Optional[List[str]] = None,
        name: str = "calendar",
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
