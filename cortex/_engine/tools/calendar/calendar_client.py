from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from delfhos.errors import ToolExecutionError


class GoogleCalendarError(ToolExecutionError):
    """Raised when the Google Calendar tool encounters an unrecoverable error."""

    def __init__(self, message: str):
        super().__init__(tool_name="calendar", detail=message)


def _normalize_scopes(raw_scopes: Any) -> List[str]:
    """Normalize scope payloads coming from connections/env vars."""
    if not raw_scopes:
        return []
    if isinstance(raw_scopes, str):
        return [scope.strip() for scope in raw_scopes.replace(",", " ").split() if scope.strip()]
    if isinstance(raw_scopes, (list, tuple, set)):
        scopes: List[str] = []
        for item in raw_scopes:
            scopes.extend(_normalize_scopes(item))
        return scopes
    return []


def _handle_api_error(exc: HttpError, operation: str) -> None:
    error_msg = str(exc)
    if exc.resp.status == 403 and "accessNotConfigured" in error_msg:
        import re

        project_match = re.search(r"project (\d+)", error_msg)
        project_num = project_match.group(1) if project_match else None
        enable_url = (
            f"https://console.developers.google.com/apis/api/calendar-json.googleapis.com/overview?project={project_num}"
            if project_num
            else "https://console.developers.google.com/apis/library/calendar-json.googleapis.com"
        )
        raise GoogleCalendarError(
            "Google Calendar API is not enabled for this project. "
            f"Enable it here: {enable_url} or configure automatic enabling via GOOGLE_CLOUD_PROJECT_ID."
        ) from exc
    raise GoogleCalendarError(f"Calendar {operation} failed: {exc}") from exc



_CALENDAR_CLIENT_CACHE = {}

class GoogleCalendarClient:
    """Thin wrapper around the Google Calendar API for CORTEX agents."""

    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/calendar",
    ]

    def __init__(
        self,
        credentials_payload: Optional[Dict[str, Any]] = None,
        scopes: Optional[List[str]] = None,
    ):
        self._credentials_payload = credentials_payload or {}
        self._scopes_override = scopes
        self._credentials: Optional[Credentials] = None
        self._service = None

    def _build_credentials(self):
        payload = self._credentials_payload
        client_id = (
            payload.get("client_id")
            or os.getenv("GOOGLE_CLIENT_ID")
            or os.getenv("GMAIL_CLIENT_ID")
        )
        client_secret = (
            payload.get("client_secret")
            or os.getenv("GOOGLE_CLIENT_SECRET")
            or os.getenv("GMAIL_CLIENT_SECRET")
        )
        refresh_token = payload.get("refresh_token") or os.getenv("GOOGLE_REFRESH_TOKEN")
        access_token = payload.get("access_token")

        cache_key = f"{client_id}:{refresh_token}:{access_token}"
        if cache_key in _CALENDAR_CLIENT_CACHE:
            self._credentials, self._service = _CALENDAR_CLIENT_CACHE[cache_key]
            return

        token_uri = payload.get("token_uri") or "https://oauth2.googleapis.com/token"
        scopes_raw = (
            self._scopes_override
            or payload.get("scopes")
            or payload.get("scope")
            or self.DEFAULT_SCOPES
        )

        scopes = _normalize_scopes(scopes_raw) or self.DEFAULT_SCOPES
        if not all([client_id, client_secret, refresh_token]):
            raise GoogleCalendarError(
                "Google Calendar connection is missing OAuth credentials. "
                "Please reconnect Google Calendar to continue."
            )

        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
        )
        if not credentials.valid and credentials.refresh_token:
            credentials.refresh(Request())

        self._credentials = credentials
        self._service = build(
            "calendar",
            "v3",
            credentials=self._credentials,
            cache_discovery=False,
        )
        _CALENDAR_CLIENT_CACHE[cache_key] = (self._credentials, self._service)

    def _ensure_service(self):
        if not self._service:
            self._build_credentials()
        elif self._credentials and self._credentials.expired and self._credentials.refresh_token:
            self._credentials.refresh(Request())

    def list_events(
        self,
        *,
        calendar_id: str = "primary",
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        max_results: int = 10,
        q: Optional[str] = None,
        show_cancelled: bool = False,
        single_events: bool = True,
        order_by: Optional[str] = "startTime",
    ) -> Dict[str, Any]:
        try:
            self._ensure_service()
            request = self._service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                q=q,
                showDeleted=show_cancelled,
                singleEvents=single_events,
                orderBy=order_by if single_events else None,
            )
            return request.execute()
        except HttpError as exc:
            _handle_api_error(exc, "LIST")

    def get_event(self, *, calendar_id: str = "primary", event_id: str) -> Dict[str, Any]:
        try:
            self._ensure_service()
            request = self._service.events().get(calendarId=calendar_id, eventId=event_id)
            return request.execute()
        except HttpError as exc:
            _handle_api_error(exc, "GET")

    def create_event(
        self,
        *,
        calendar_id: str = "primary",
        event_body: Dict[str, Any],
        send_updates: str = "none",
        include_conference: bool = False,
    ) -> Dict[str, Any]:
        try:
            self._ensure_service()
            body = dict(event_body)
            if include_conference:
                body.setdefault(
                    "conferenceData",
                    {
                        "createConferenceRequest": {
                            "conferenceSolutionKey": {"type": "hangoutsMeet"},
                            "requestId": uuid.uuid4().hex,
                        }
                    },
                )

            request = self._service.events().insert(
                calendarId=calendar_id,
                body=body,
                conferenceDataVersion=1 if include_conference else 0,
                sendUpdates=send_updates,
            )
            return request.execute()
        except HttpError as exc:
            _handle_api_error(exc, "CREATE")

    def update_event(
        self,
        *,
        calendar_id: str = "primary",
        event_id: str,
        updates: Dict[str, Any],
        send_updates: str = "none",
        include_conference: bool = False,
    ) -> Dict[str, Any]:
        try:
            self._ensure_service()
            body = dict(updates)
            if include_conference:
                body.setdefault(
                    "conferenceData",
                    {
                        "createConferenceRequest": {
                            "conferenceSolutionKey": {"type": "hangoutsMeet"},
                            "requestId": uuid.uuid4().hex,
                        }
                    },
                )

            request = self._service.events().patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=body,
                conferenceDataVersion=1 if include_conference else 0,
                sendUpdates=send_updates,
            )
            return request.execute()
        except HttpError as exc:
            _handle_api_error(exc, "UPDATE")

    def delete_event(
        self,
        *,
        calendar_id: str = "primary",
        event_id: str,
        send_updates: str = "none",
    ) -> None:
        try:
            self._ensure_service()
            request = self._service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
                sendUpdates=send_updates,
            )
            request.execute()
        except HttpError as exc:
            _handle_api_error(exc, "DELETE")

    def respond_to_event(
        self,
        *,
        calendar_id: str = "primary",
        event_id: str,
        attendee_email: str,
        response_status: str,
        comment: Optional[str] = None,
        send_updates: str = "none",
    ) -> Dict[str, Any]:
        """Update the attendee response for the authenticated user."""
        try:
            self._ensure_service()
            attendee = {"email": attendee_email, "responseStatus": response_status}
            if comment:
                attendee["comment"] = comment

            request = self._service.events().patch(
                calendarId=calendar_id,
                eventId=event_id,
                body={"attendees": [attendee]},
                sendUpdates=send_updates,
            )
            return request.execute()
        except HttpError as exc:
            _handle_api_error(exc, "RESPOND")

