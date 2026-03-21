"""
Base Connection class for the Cortex SDK.

A Connection represents an authenticated link to an external service.
It wraps credentials securely and optionally restricts which actions are allowed.

The distinction between Connection and Tool:
  - Connection = a specific instance tied to credentials (e.g., personal Gmail)
  - Tool       = the abstract capability (Gmail) with a fixed Python API

Multiple connections of the same tool can coexist (e.g., work + personal Gmail).
"""

import json
from typing import List, Optional, Dict, Any, Union
from cortex._engine.connection import Connection as _BaseConnection, AuthType, ConnectionStatus


class _PrettyInspectDict(dict):
    """Dict that pretty-prints as indented JSON when printed."""

    def __str__(self) -> str:
        methods = self.get("methods")
        if not isinstance(methods, list):
            return json.dumps(self, indent=2, ensure_ascii=False)

        is_mcp = "server" in self
        label = "MCP Server" if is_mcp else "Tool"
        target = str(self.get("server") if is_mcp else self.get("tool", "tool"))
        total = self.get("total", len(methods))
        auth_type = str(self.get("auth_type", "none"))
        allowed = self.get("allowed", None)

        lines = [f"\n📋 {label}: {target}", "=" * 70]

        if allowed is not None:
            if isinstance(allowed, list):
                allow_text = ", ".join(allowed) if allowed else "(none)"
            else:
                allow_text = str(allowed)
            lines.append(f"🔐 Allowed: {allow_text}")
            lines.append("")

        # Detailed mode: methods is list[dict{name, description}]
        if methods and isinstance(methods[0], dict):
            for i, method in enumerate(methods):
                name = str(method.get("name", ""))
                description = str(method.get("description", ""))
                styled_name = f"\033[1m\033[96m{i+1:2}. {name}\033[0m"
                lines.append(f"  {styled_name}")
                if description:
                    wrapped = self._wrap_text(description, indent=6, width=64)
                    lines.append(wrapped)
                lines.append("")
        else:
            # Compact mode: methods is list[str]
            for name in methods:
                lines.append(f"  • {name}")

        lines.extend(["", "=" * 70, f"Total: {total} actions | Auth: {auth_type}", ""])
        return "\n".join(lines)

    @staticmethod
    def _wrap_text(text: str, indent: int = 6, width: int = 64) -> str:
        """Wrap long text at width with indentation."""
        import textwrap
        indent_str = " " * indent
        wrapped = textwrap.fill(
            text,
            width=width,
            initial_indent=indent_str,
            subsequent_indent=indent_str,
        )
        return wrapped

    def __repr__(self) -> str:
        return self.__str__()


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

    @classmethod
    def inspect(cls, verbose: bool = False) -> dict:
        """
        Inspect available actions for this tool without instantiation.
        
        This class method allows developers to see what actions are available
        without needing to provide credentials.
        
        Args:
            verbose: If False (default), returns available method names.
                     If True, returns allowed methods and descriptions.
        
        Returns:
            dict with tool information and available actions
        
        Example::
        
            print(Gmail.inspect())  # See available Gmail actions
            print(Sheets.inspect(verbose=True))  # See detailed descriptions
        """
        available_actions = list(cls.ALLOWED_ACTIONS or [])
        
        if not verbose:
            return _PrettyInspectDict(
                {
                    "tool": cls.TOOL_NAME,
                    "methods": available_actions,
                    "total": len(available_actions),
                }
            )

        descriptions: Dict[str, str] = {}
        try:
            from cortex._engine.tools.tool_registry import TOOL_ACTION_SUMMARIES
            descriptions = TOOL_ACTION_SUMMARIES.get(cls.TOOL_NAME.lower(), {})
        except Exception:
            descriptions = {}

        methods = [
            {
                "name": action,
                "description": descriptions.get(action.upper(), ""),
            }
            for action in available_actions
        ]
        return _PrettyInspectDict(
            {
                "tool": cls.TOOL_NAME,
                "allowed": "all",
                "methods": methods,
                "total": len(available_actions),
            }
        )

    def __init__(
        self,
        credentials: Dict[str, Any],
        allow: Optional[Union[str, List[str]]] = None,
        confirm: Union[bool, List[str], None] = True,
        name: Optional[str] = None,
        auth_type: AuthType = AuthType.OAUTH2,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            credentials:  Service-specific auth credentials dict.
            allow:        List of allowed actions, e.g. ["read", "send"].
                          None means all actions are permitted.
            confirm:      List of action names requiring human approval before execution,
                          e.g. ["send", "delete"]. None = no confirmation required.
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
            confirm=confirm,
            metadata=metadata or {},
        )

    @staticmethod
    def _normalize_action_name(action: str) -> str:
        return str(action).strip().lower().replace("-", "_")

    def inspect_instance(self, verbose: bool = False) -> dict:
        """
        Return instance-specific connection information.
        
        Args:
            verbose: If False (default), returns available method names.
                     If True, returns allowed methods and descriptions.
        """
        available_actions = list(type(self).ALLOWED_ACTIONS or [])
        allowed = self.effective_allowed_actions()

        if not verbose:
            return _PrettyInspectDict(
                {
                    "tool": self.tool_name,
                    "methods": available_actions,
                    "total": len(available_actions),
                    "auth_type": self.auth_type.value,
                }
            )

        descriptions: Dict[str, str] = {}
        try:
            from cortex._engine.tools.tool_registry import TOOL_ACTION_SUMMARIES
            descriptions = TOOL_ACTION_SUMMARIES.get(self.tool_name.lower(), {})
        except Exception:
            descriptions = {}

        methods = [
            {
                "name": action,
                "description": descriptions.get(action.upper(), ""),
            }
            for action in available_actions
        ]
        return _PrettyInspectDict(
            {
                "tool": self.tool_name,
                "allowed": allowed,
                "methods": methods,
                "total": len(available_actions),
                "auth_type": self.auth_type.value,
                "metadata": self.metadata,
            }
        )
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
        confirm: Union[bool, List[str], None] = True,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            service_account:   Path to Google SA key JSON file (recommended for servers).
            oauth_credentials: Path to client_secrets.json (for personal accounts).
            delegated_user:    Email to impersonate via domain-wide delegation (SA only).
            allow:             Allowed actions, e.g. ["read", "send"]. None = all.
            confirm:           List of action names requiring approval, e.g. ["send", "delete"].
            name:              Human-readable label for this connection.
            metadata:          Extra info dict.
        """
        from cortex.google_auth import resolve_google_credentials, scopes_to_actions

        requested_actions: Optional[List[str]]
        if allow is None:
            requested_actions = None
        elif isinstance(allow, str):
            requested_actions = [self._normalize_action_name(allow)]
        else:
            requested_actions = [self._normalize_action_name(a) for a in allow]

        # Keep allowed actions aligned with this connection's declared capability set.
        if requested_actions is not None and self.ALLOWED_ACTIONS is not None:
            supported = {self._normalize_action_name(a) for a in self.ALLOWED_ACTIONS}
            unknown = sorted({a for a in requested_actions if a not in supported})
            if unknown:
                from delfhos.errors import ConnectionConfigurationError

                raise ConnectionConfigurationError(
                    tool_name=self.TOOL_NAME,
                    detail=(
                        f"Unknown allowed action(s): {unknown}. "
                        f"Supported actions: {sorted(supported)}"
                    ),
                )

            # Dedupe while preserving user-specified order.
            requested_actions = list(dict.fromkeys(requested_actions))

        resolved = resolve_google_credentials(
            tool_name=self.TOOL_NAME,
            service_account=service_account,
            oauth_credentials=oauth_credentials,
            delegated_user=delegated_user,
            actions=requested_actions,
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
            effective_actions = scopes_to_actions(
                self.TOOL_NAME,
                granted_scopes,
                requested_actions=requested_actions,
            )
            if requested_actions is None and not effective_actions:
                effective_actions = None
        else:
            # Service accounts: trust the requested actions directly
            effective_actions = requested_actions

        super().__init__(
            credentials=resolved,
            allow=effective_actions,
            confirm=confirm,
            name=name or self.TOOL_NAME,
            auth_type=auth_type,
            metadata=metadata,
        )


__all__ = ["BaseConnection", "GoogleBaseConnection", "AuthType", "ConnectionStatus"]

