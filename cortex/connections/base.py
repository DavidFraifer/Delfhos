"""
Base Connection class for the Cortex SDK.

A Connection represents an authenticated link to an external service.
It wraps credentials securely and optionally restricts which actions are allowed.

The distinction between Connection and Tool:
  - Connection = a specific instance tied to credentials (e.g., personal Gmail)
  - Tool       = the abstract capability (Gmail) with a fixed Python API

Multiple connections of the same tool can coexist (e.g., work + personal Gmail).
"""

from typing import List, Optional, Dict, Any, Union
from cortex._engine.connection import Connection as _BaseConnection, AuthType, ConnectionStatus


class BaseConnection(_BaseConnection):
    """
    Typed base for all Cortex connections.

    Subclasses define the tool_name and provide a clean constructor
    that accepts service-specific arguments instead of a generic credentials dict.
    """

    # Subclasses must set this
    TOOL_NAME: str = ""
    ALLOWED_ACTIONS: Optional[List[str]] = None

    # Set to True for connections that support Google auth methods
    _GOOGLE_AUTH: bool = False

    def __init__(
        self,
        credentials: Dict[str, Any],
        allow: Optional[Union[str, List[str]]] = None,
        name: Optional[str] = None,
        auth_type: AuthType = AuthType.OAUTH2,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            credentials:  Service-specific auth credentials dict.
            allow:        List of allowed actions, e.g. ["read", "send"].
                          None means all actions are permitted.
            name:         Human-readable label for this connection, e.g. "work_gmail".
                          Defaults to the tool name.
            auth_type:    Authentication mechanism (default: OAUTH2).
            metadata:     Optional extra info (e.g. region, description).
        """
        if not self.TOOL_NAME:
            from delfhos.errors import ConnectionConfigurationError
            raise ConnectionConfigurationError(
                tool_name=self.__class__.__name__,
                detail="Subclasses must define TOOL_NAME."
            )

        super().__init__(
            tool_name=self.TOOL_NAME,
            connection_name=name or self.TOOL_NAME,
            auth_type=auth_type,
            credentials=credentials,
            allow=allow,
            metadata=metadata or {},
        )

    @classmethod
    def allowed_actions(cls) -> List[str]:
        """Return the documented action names this connection supports."""
        if not cls.ALLOWED_ACTIONS:
            return []
        return list(cls.ALLOWED_ACTIONS)

    @staticmethod
    def _normalize_action_name(action: str) -> str:
        return str(action).strip().lower().replace("-", "_")

    def inspect(self, verbose: bool = False) -> str | dict:
        """
        Return connection information.
        
        Args:
            verbose: If False (default), returns a formatted string list of actions.
                     If True, returns a complete dict with access metadata.
        """
        allowed = self.effective_allowed_actions()
        
        if not verbose:
            return f"Actions: {allowed}"
        
        else:
            return {
                "connection": self.connection_name,
                "allowed": allowed,
                "auth_type": self.auth_type.value,
                "metadata": self.metadata
            }

    def effective_allowed_actions(self) -> Union[List[str], str]:
        """
        Return the effective action policy for this connection.

        - "all" means unrestricted
        - list[str] means explicitly restricted actions
        """
        if self.allow is None:
            return "all"
        return sorted(self._normalize_action_name(a) for a in self.allow)


class GoogleBaseConnection(BaseConnection):
    """
    Base class for all Google service connections.

    Accepts two authentication methods (in priority order):
      1. service_account     — path to a service account JSON key file
      2. oauth_credentials   — path to a client_secrets.json file (browser flow)

    Example:
        # Service account (recommended for servers)
        gmail = GmailConnection(service_account="sa.json", delegated_user="admin@co.com")

        # OAuth browser flow (for personal accounts)
        gmail = GmailConnection(oauth_credentials="client_secrets.json")
    """

    _GOOGLE_AUTH = True

    def __init__(
        self,
        *,
        service_account: Optional[str] = None,
        oauth_credentials: Optional[str] = None,
        delegated_user: Optional[str] = None,
        allow: Optional[Union[str, List[str]]] = None,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            service_account:   Path to Google SA key JSON file (recommended for servers).
            oauth_credentials: Path to client_secrets.json (for personal accounts).
            delegated_user:    Email to impersonate via domain-wide delegation (SA only).
            allow:             Allowed actions, e.g. ["read", "send"]. None = all.
            name:              Human-readable label for this connection.
            metadata:          Extra info dict.
        """
        from cortex.google_auth import resolve_google_credentials, scopes_to_actions

        resolved = resolve_google_credentials(
            tool_name=self.TOOL_NAME,
            service_account=service_account,
            oauth_credentials=oauth_credentials,
            delegated_user=delegated_user,
            allow=allow,
        )

        # Determine auth type based on what was provided
        if service_account:
            auth_type = AuthType.SERVICE_ACCOUNT
        else:
            auth_type = AuthType.OAUTH2

        # For OAuth, reconcile actions_allowed with what Google actually granted.
        # The token may have fewer scopes than requested (user unchecked something
        # in the consent screen), so we derive the effective actions from the
        # real granted scopes rather than trusting the user-supplied `actions` list.
        if auth_type == AuthType.OAUTH2:
            granted_scopes = resolved.get("scopes", [])
            effective_actions = scopes_to_actions(self.TOOL_NAME, granted_scopes) or None
        else:
            # Service accounts: trust the requested actions directly
            effective_actions = allow

        super().__init__(
            credentials=resolved,
            allow=effective_actions,
            name=name or self.TOOL_NAME,
            auth_type=auth_type,
            metadata=metadata,
        )


__all__ = ["BaseConnection", "GoogleBaseConnection", "AuthType", "ConnectionStatus"]

