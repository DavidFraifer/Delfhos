"""
CalendarConnection — Authenticated link to Google Calendar.

Supported actions: "list", "create", "update", "delete"

Example:
    calendar = CalendarConnection(
        service_account="path/to/service-account.json",
        delegated_user="admin@company.com",
        allow=["list"],  # read-only
    )
"""

from typing import List, Optional, Dict, Any, Union
from .base import GoogleBaseConnection


class CalendarConnection(GoogleBaseConnection):
    """
    Google Calendar integration for reading and managing events.
    
    Example:
        calendar = Calendar(oauth_credentials="client_secrets.json")
        agent = Agent(tools=[calendar, Gmail()], llm="gemini-3.1-flash-lite-preview")
        agent.run("Find a 1-hour slot next Tuesday and schedule meeting with alice@co.com")
    
    Authentication (choose one):
        service_account: Google Service Account JSON (for servers).
        oauth_credentials: OAuth client_secrets.json (for personal accounts).
    
    Args:
        delegated_user: Email to impersonate (service account + delegation only).
        allow: Restrict actions, e.g., ["list"] blocks creating events (default: allow all).
        confirm: Require human approval before executing listed actions, e.g. ["create", "delete"].
        name: Custom label (default: "calendar").
        metadata: Extra info dict for tracking/logging.
    """
    TOOL_NAME = "calendar"
    ALLOWED_ACTIONS = ["list", "get", "create", "update", "delete", "respond"]

    def __init__(
        self,
        *,
        service_account: Optional[str] = None,
        oauth_credentials: Optional[str] = None,
        delegated_user: Optional[str] = None,
        allow: Optional[Union[str, List[str]]] = None,
        confirm: Union[bool, List[str], None] = True,
        name: str = "calendar",
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
