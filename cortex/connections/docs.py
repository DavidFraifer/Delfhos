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
        allow=["read"],
    )
"""

from typing import List, Optional, Dict, Any, Union
from .base import GoogleBaseConnection


class DocsConnection(GoogleBaseConnection):
    """
    Google Docs integration for reading and writing documents.
    
    Example:
        docs = Docs(oauth_credentials="client_secrets.json")
        agent = Agent(tools=[docs, WebSearch()], llm="gemini-3.1-flash-lite-preview")
        agent.run("Research latest Python best practices and write a guide to my Tech Doc")
    
    Authentication (choose one):
        service_account: Google Service Account JSON (for servers).
        oauth_credentials: OAuth client_secrets.json (for personal accounts).
    
    Args:
        delegated_user: Email to impersonate (service account + delegation only).
        allow: Restrict actions, e.g., ["read"] blocks editing (default: allow all).
        confirm: Require human approval before executing listed actions, e.g. ["create", "delete"].
        name: Custom label (default: "docs").
        metadata: Extra info dict for tracking/logging.
    """
    TOOL_NAME = "docs"
    ALLOWED_ACTIONS = ["read", "create", "update", "format", "delete"]

    def __init__(
        self,
        *,
        service_account: Optional[str] = None,
        oauth_credentials: Optional[str] = None,
        delegated_user: Optional[str] = None,
        allow: Optional[Union[str, List[str]]] = None,
        confirm: Union[bool, List[str], None] = True,
        name: str = "docs",
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
