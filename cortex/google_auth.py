"""
cortex.google_auth — Simplified Google authentication for Cortex connections.

Supports two auth methods, in order of priority:
  1. Service Account JSON   — for server / business deployments
  2. OAuth Client Secrets   — for personal / developer use (browser consent flow)

Usage:
    # Resolved automatically inside each Connection constructor.
    # Users never need to import this module directly.
"""

from __future__ import annotations

import hashlib
import json
import os
from delfhos.errors import ConnectionConfigurationError, ConnectionFileNotFoundError, OptionalDependencyError
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set


# ─── Action → Scope mapping ──────────────────────────────────────────────────

# Each entry: action_name → list of scope URIs required for that action.
# When `actions` is None (all allowed), the "*" key determines the broadest scope.

SCOPE_MAP: Dict[str, Dict[str, List[str]]] = {
    "gmail": {
        "read": ["https://www.googleapis.com/auth/gmail.readonly"],
        "send": ["https://www.googleapis.com/auth/gmail.send"],
        "*":    ["https://www.googleapis.com/auth/gmail.modify"],
    },
    "sheets": {
        "read":   ["https://www.googleapis.com/auth/spreadsheets.readonly"],
        "write":  ["https://www.googleapis.com/auth/spreadsheets",
                   "https://www.googleapis.com/auth/drive"],
        "create": ["https://www.googleapis.com/auth/spreadsheets",
                   "https://www.googleapis.com/auth/drive"],
        "format": ["https://www.googleapis.com/auth/spreadsheets",
                   "https://www.googleapis.com/auth/drive"],
        "chart":  ["https://www.googleapis.com/auth/spreadsheets",
                   "https://www.googleapis.com/auth/drive"],
        "batch":  ["https://www.googleapis.com/auth/spreadsheets",
                   "https://www.googleapis.com/auth/drive"],
        "*":      ["https://www.googleapis.com/auth/spreadsheets",
                   "https://www.googleapis.com/auth/drive"],
    },
    "drive": {
        "search": ["https://www.googleapis.com/auth/drive.readonly"],
        "get":    ["https://www.googleapis.com/auth/drive.readonly"],
        "create": ["https://www.googleapis.com/auth/drive"],
        "update": ["https://www.googleapis.com/auth/drive"],
        "delete": ["https://www.googleapis.com/auth/drive"],
        "list_permissions": ["https://www.googleapis.com/auth/drive.readonly"],
        "share":  ["https://www.googleapis.com/auth/drive"],
        "unshare":["https://www.googleapis.com/auth/drive"],
        "*":      ["https://www.googleapis.com/auth/drive"],
    },
    "calendar": {
        "list":   ["https://www.googleapis.com/auth/calendar.readonly"],
        "get":    ["https://www.googleapis.com/auth/calendar.readonly"],
        "create": ["https://www.googleapis.com/auth/calendar"],
        "update": ["https://www.googleapis.com/auth/calendar"],
        "delete": ["https://www.googleapis.com/auth/calendar"],
        "respond":["https://www.googleapis.com/auth/calendar"],
        "*":      ["https://www.googleapis.com/auth/calendar"],
    },
    "docs": {
        "read":   ["https://www.googleapis.com/auth/documents.readonly"],
        "create": ["https://www.googleapis.com/auth/documents",
                   "https://www.googleapis.com/auth/drive"],
        "update": ["https://www.googleapis.com/auth/documents"],
        "format": ["https://www.googleapis.com/auth/documents"],
        "delete": ["https://www.googleapis.com/auth/documents",
                   "https://www.googleapis.com/auth/drive"],
        "*":      ["https://www.googleapis.com/auth/documents",
                   "https://www.googleapis.com/auth/drive"],
    },
}

# Some broader scopes implicitly cover narrower ones for authorization checks.
_SCOPE_IMPLICATIONS: Dict[str, Set[str]] = {
    "https://www.googleapis.com/auth/drive": {
        "https://www.googleapis.com/auth/drive.readonly",
    },
    "https://www.googleapis.com/auth/spreadsheets": {
        "https://www.googleapis.com/auth/spreadsheets.readonly",
    },
    "https://www.googleapis.com/auth/calendar": {
        "https://www.googleapis.com/auth/calendar.readonly",
    },
    "https://www.googleapis.com/auth/documents": {
        "https://www.googleapis.com/auth/documents.readonly",
    },
    "https://www.googleapis.com/auth/gmail.modify": {
        "https://www.googleapis.com/auth/gmail.readonly",
    },
}

# Default directory for cached OAuth tokens
DEFAULT_TOKEN_DIR = Path.home() / ".cortex" / "tokens"


def actions_to_scopes(tool_name: str, actions: Optional[List[str]] = None) -> List[str]:
    """
    Convert user-friendly action names to Google OAuth scopes.

    Args:
        tool_name: e.g. "gmail", "drive"
        actions:   e.g. ["read", "send"]. None means all actions allowed.

    Returns:
        Deduplicated list of OAuth scope URIs.
    """
    tool_scopes = SCOPE_MAP.get(tool_name.lower())
    if not tool_scopes:
        return []

    if actions is None:
        # All actions → union of all concrete action scopes.
        scopes: set = set()
        for action_name, action_scopes in tool_scopes.items():
            if action_name == "*":
                continue
            scopes.update(action_scopes)
        if scopes:
            return sorted(scopes)
        return sorted(tool_scopes.get("*", []))

    scopes: set = set()
    for action in actions:
        action_lower = action.lower()
        action_scope_list = tool_scopes.get(action_lower)
        if not action_scope_list:
            valid_actions = sorted(k for k in tool_scopes.keys() if k != "*")
            raise ConnectionConfigurationError(
                tool_name=tool_name,
                detail=(
                    f"Unknown action '{action}' for Google tool '{tool_name}'. "
                    f"Valid actions: {valid_actions}"
                ),
            )
        scopes.update(action_scope_list)

    return sorted(scopes)


def _expand_granted_scopes(granted_scopes: Iterable[str]) -> Set[str]:
    """Expand granted scopes with known broader->narrower implications."""
    expanded = set(granted_scopes)
    for scope in list(expanded):
        expanded.update(_SCOPE_IMPLICATIONS.get(scope, set()))
    return expanded


def scopes_to_actions(
    tool_name: str,
    granted_scopes: Iterable[str],
    requested_actions: Optional[List[str]] = None,
) -> List[str]:
    """
    Convert granted OAuth scopes back to user-facing action names.

    Used after an OAuth flow to determine which actions were actually
    authorised by the user, so the connection's `actions_allowed` can
    be restricted to match reality.

    Args:
        tool_name:      e.g. "gmail"
        granted_scopes: Iterable of scope URIs that Google actually granted.

    Returns:
        Sorted list of action names that are fully covered by the granted scopes.
    """
    tool_scopes = SCOPE_MAP.get(tool_name.lower(), {})
    granted_set = _expand_granted_scopes(granted_scopes)
    requested_set: Optional[Set[str]] = None
    if requested_actions is not None:
        requested_set = {str(a).strip().lower() for a in requested_actions}
    allowed: List[str] = []
    for action, required in tool_scopes.items():
        if action == "*":
            continue
        if requested_set is not None and action not in requested_set:
            continue
        if set(required).issubset(granted_set):
            allowed.append(action)
    return sorted(allowed)


# ─── Credential resolution ───────────────────────────────────────────────────

def resolve_google_credentials(
    *,
    tool_name: str,
    service_account: Optional[str] = None,
    oauth_credentials: Optional[str] = None,
    delegated_user: Optional[str] = None,
    actions: Optional[List[str]] = None,
    token_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Resolve Google credentials from supported auth methods into the
    credentials dict that the Cortex engine expects.

    Priority: service_account > oauth_credentials.

    Args:
        tool_name:          e.g. "gmail", "drive"
        service_account:    Path to service account JSON key file.
        oauth_credentials:  Path to OAuth client_secrets.json file.
        delegated_user:     Email to impersonate (service account only).
        actions:            User-specified action restrictions.
        token_dir:          Where to cache OAuth tokens. Default: ~/.cortex/tokens/

    Returns:
        Dict with keys the engine expects: access_token, refresh_token,
        client_id, client_secret, scopes, etc.

    Raises:
        ValueError: If no auth method is provided.
        FileNotFoundError: If a credentials file path doesn't exist.
    """
    scopes = actions_to_scopes(tool_name, actions)

    # Path 1: Service Account JSON
    if service_account:
        return _load_service_account(service_account, scopes, delegated_user)

    # Path 2: OAuth Client Secrets JSON
    if oauth_credentials:
        return _load_oauth_client(oauth_credentials, scopes, tool_name, token_dir)

    raise ConnectionConfigurationError(
        tool_name=tool_name,
        detail=f"No authentication provided. Use one of:\n  • service_account='path/to/service-account.json'  (recommended for servers)\n  • oauth_credentials='path/to/client_secrets.json' (for personal accounts)"
    )


# ─── Service Account loader ──────────────────────────────────────────────────

def _load_service_account(
    sa_path: str,
    scopes: List[str],
    delegated_user: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Load a Google Service Account JSON key and return a credentials dict
    with a valid access_token that the engine can use directly.

    Args:
        sa_path:        Path to the service account JSON key file.
        scopes:         OAuth scopes to request.
        delegated_user: Optional email to impersonate via domain-wide delegation.

    Returns:
        Dict with access_token (and service_account marker for the engine).
    """
    from google.oauth2 import service_account as sa_module
    from google.auth.transport.requests import Request

    sa_path_resolved = Path(sa_path).expanduser().resolve()
    if not sa_path_resolved.exists():
        raise ConnectionFileNotFoundError(
            tool_name="Google",
            detail=f"Service account file not found: {sa_path}\nDownload it from: https://console.cloud.google.com/iam-admin/serviceaccounts"
        )

    creds = sa_module.Credentials.from_service_account_file(
        str(sa_path_resolved),
        scopes=scopes or ["https://www.googleapis.com/auth/cloud-platform"],
    )

    if delegated_user:
        creds = creds.with_subject(delegated_user)

    # Pre-fetch a valid access token
    creds.refresh(Request())

    return {
        "access_token": creds.token,
        "scopes": scopes,
        "_service_account_credentials": creds,  # engine can use this directly
        "_auth_type": "service_account",
    }


# ─── OAuth Client Secrets loader ─────────────────────────────────────────────

def _load_oauth_client(
    client_secrets_path: str,
    scopes: List[str],
    tool_name: str,
    token_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Load OAuth credentials using Google's InstalledAppFlow.

    On first run:   Opens a browser for user consent.
    On subsequent:  Loads the cached token from disk and refreshes if needed.

    Args:
        client_secrets_path:  Path to client_secrets.json from Cloud Console.
        scopes:               OAuth scopes to request.
        tool_name:            Used to namespace the cached token file.
        token_dir:            Directory to store cached tokens.

    Returns:
        Dict with access_token, refresh_token, client_id, client_secret, scopes.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    cs_path = Path(client_secrets_path).expanduser().resolve()
    if not cs_path.exists():
        raise ConnectionFileNotFoundError(
            tool_name="Google",
            detail=f"OAuth client secrets file not found: {client_secrets_path}\nDownload it from: https://console.cloud.google.com/apis/credentials"
        )

    # Determine token cache path
    cache_dir = token_dir or DEFAULT_TOKEN_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Create a unique token filename based on client_secrets path + scopes
    scope_hash = hashlib.md5(
        (str(cs_path) + "|" + ",".join(sorted(scopes))).encode()
    ).hexdigest()[:8]
    token_path = cache_dir / f"{tool_name}_{scope_hash}.json"

    creds = None

    # Try to load cached token
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        except Exception:
            creds = None

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None  # Force re-auth

    # Run browser consent flow if needed
    if not creds or not creds.valid:
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            raise OptionalDependencyError(
                package="google-auth-oauthlib",
                detail="google-auth-oauthlib is required for OAuth browser flow."
            )

        flow = InstalledAppFlow.from_client_secrets_file(str(cs_path), scopes)
        creds = flow.run_local_server(port=0, open_browser=True)

    # ── Verify what Google actually granted ──────────────────────────────────
    # `creds.scopes` contains the real granted scopes (may differ from requested).
    granted_scopes: List[str] = sorted(creds.scopes) if creds.scopes else scopes
    denied_scopes = [s for s in scopes if s not in granted_scopes]

    if denied_scopes:
        import warnings
        warnings.warn(
            f"[Cortex/{tool_name}] The following OAuth scopes were requested but "
            f"NOT granted by the user:\n"
            + "\n".join(f"  - {s}" for s in denied_scopes)
            + "\nActions requiring those scopes will fail at runtime. "
            "Re-run to grant all permissions, or reduce your `actions` list.",
            stacklevel=4,
        )

    # Cache the token for next time
    token_path.write_text(creds.to_json())

    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "token_uri": creds.token_uri or "https://oauth2.googleapis.com/token",
        "scopes": granted_scopes,          # ← actual granted, not requested
        "_requested_scopes": scopes,       # ← keep requested for debugging
        "_denied_scopes": denied_scopes,   # ← what was denied
        "_auth_type": "oauth_client",
    }
