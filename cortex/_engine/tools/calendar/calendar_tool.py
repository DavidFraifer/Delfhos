from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from typing import List, Optional, Tuple, Callable
from delfhos.errors import ToolExecutionError
from zoneinfo import ZoneInfo

from ...utils.console import console
from .calendar_client import GoogleCalendarClient, GoogleCalendarError

# Optional automatic API enablement
_api_manager = None
_has_api_manager = False
try:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    api_path = os.path.join(project_root, "api")
    if os.path.exists(api_path) and project_root not in sys.path:
        sys.path.insert(0, project_root)
    from api.utils.google_api_manager import get_api_manager

    _has_api_manager = True
except (ImportError, Exception):
    _has_api_manager = False


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_datetime(value: Any, timezone_hint: Optional[str] = None) -> Optional[Dict[str, str]]:
    """
    Convert various time formats into Google Calendar's expected payload.
    Supports dict payloads (already formatted), ISO strings, or YYYY-MM-DD dates.
    """
    if not value:
        return None

    if isinstance(value, dict):
        if "dateTime" in value or "date" in value:
            return value
        if "date_time" in value:
            payload = {"dateTime": value["date_time"]}
            if "timeZone" in value:
                payload["timeZone"] = value["timeZone"]
            return payload

    if isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value, tz=timezone.utc)
        return {"dateTime": dt.isoformat()}

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None

        if len(text) == 10 and text.count("-") == 2:
            # Looks like YYYY-MM-DD → all-day event
            return {"date": text}

        # Attempt ISO parsing
        try:
            if "T" not in text:
                # Accept "YYYY-MM-DD HH:MM" by replacing space with T
                text = text.replace(" ", "T", 1)
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None

        if dt.tzinfo is None:
            tz = timezone_hint or "UTC"
            try:
                dt = dt.replace(tzinfo=ZoneInfo(tz))
            except Exception:
                dt = dt.replace(tzinfo=timezone.utc)

        return {"dateTime": dt.isoformat()}

    return None


async def _auto_enable_calendar_api() -> bool:
    """Try to auto-enable the Calendar API using the configured GoogleAPIManager."""
    if not _has_api_manager:
        return False

    try:
        api_manager = get_api_manager()
        if not api_manager:
            return False

        enabled = api_manager.ensure_api_enabled("calendar")
        if enabled:
            # Allow short propagation time before retrying the Calendar request
            await asyncio.sleep(0.5)
        return enabled
    except Exception:
        return False


async def _execute_calendar_call(operation: Callable[[], Any]):
    """Execute a calendar client call, auto-enabling the API and retrying if required."""
    try:
        return operation()
    except GoogleCalendarError as exc:
        error_text = str(exc)
        if "Google Calendar API is not enabled" in error_text:
            enabled = await _auto_enable_calendar_api()
            if enabled:
                return operation()
            raise GoogleCalendarError(
                "Google Calendar API is not enabled and automatic activation failed. "
                "Configure GOOGLE_CLOUD_PROJECT_ID together with "
                "GOOGLE_SERVICE_ACCOUNT_PATH or GOOGLE_SERVICE_ACCOUNT_JSON/GOOGLE_SERVICE_ACCOUNT_JSON_B64 "
                "so Delfhos can enable the API without manual console steps."
            ) from exc
        raise


def _build_event_times(params: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, str]]:
    timezone_hint = (
        params.get("timeZone")
        or params.get("timezone")
        or params.get("tz")
        or "UTC"
    )
    start = (
        _coerce_datetime(params.get("start"), timezone_hint)
        or _coerce_datetime(params.get("start_time"), timezone_hint)
        or _coerce_datetime(params.get("startTime"), timezone_hint)
        or _coerce_datetime(params.get("startDateTime"), timezone_hint)
    )

    if not start:
        raise ToolExecutionError(tool_name="calendar", detail="calendar CREATE/UPDATE requires a start time (params.start).")

    end = (
        _coerce_datetime(params.get("end"), timezone_hint)
        or _coerce_datetime(params.get("end_time"), timezone_hint)
        or _coerce_datetime(params.get("endTime"), timezone_hint)
        or _coerce_datetime(params.get("endDateTime"), timezone_hint)
    )

    if not end:
        duration = params.get("duration_minutes") or params.get("durationMinutes") or params.get("duration")
        if duration:
            start_dt = datetime.fromisoformat(start.get("dateTime") or (start.get("date") + "T00:00:00+00:00"))
            try:
                duration_minutes = float(duration)
            except (TypeError, ValueError):
                duration_minutes = 60
            end_dt = start_dt + timedelta(minutes=duration_minutes)
            if start.get("date"):
                end = {"date": end_dt.date().isoformat()}
            else:
                end = {"dateTime": end_dt.isoformat()}
        else:
            raise ToolExecutionError(tool_name="calendar", detail="calendar CREATE/UPDATE requires either end time or duration_minutes.")

    return start, end


def _normalize_attendees(attendees: Any) -> List[Dict[str, Any]]:
    if not attendees:
        return []
    normalized: List[Dict[str, Any]] = []
    if isinstance(attendees, (list, tuple, set)):
        source = attendees
    else:
        source = [attendees]
    for entry in source:
        if isinstance(entry, str):
            normalized.append({"email": entry})
        elif isinstance(entry, dict):
            if "email" in entry:
                normalized.append(entry)
        else:
            continue
    return normalized


def _normalize_reminders(reminders: Any) -> Optional[Dict[str, Any]]:
    if reminders is None:
        return None

    if isinstance(reminders, dict):
        if "overrides" in reminders or "useDefault" in reminders:
            return reminders

    overrides: List[Dict[str, Any]] = []
    if isinstance(reminders, (list, tuple)):
        for reminder in reminders:
            if isinstance(reminder, dict) and "minutes" in reminder:
                overrides.append(
                    {
                        "method": reminder.get("method", "popup"),
                        "minutes": int(reminder["minutes"]),
                    }
                )
            elif isinstance(reminder, (int, float)):
                overrides.append({"method": "popup", "minutes": int(reminder)})
    elif isinstance(reminders, (int, float)):
        overrides.append({"method": "popup", "minutes": int(reminders)})

    if overrides:
        return {"useDefault": False, "overrides": overrides}
    return None


def _boolean_param(params: Dict[str, Any], key: str, default: bool = False) -> bool:
    value = params.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


async def calendar_tool(
    user_input: Any = "",
    task_id: Optional[str] = None,
    light_llm: Optional[str] = None,
    heavy_llm: Optional[str] = None,
    agent_id: Optional[str] = None,
    validation_mode: bool = False,
    credentials: Optional[Dict[str, Any]] = None,
    connection: Any = None,
    **kwargs: Any,
):
    """
    Google Calendar tool.
    Supports LIST, GET, CREATE, UPDATE, DELETE, RESPOND actions.
    """
    context = user_input if isinstance(user_input, dict) else {}
    action = (context.get("action") or "").upper()
    params = context.get("params") or {}

    if not action:
        raise ToolExecutionError(tool_name="calendar", detail="Google Calendar tool requires an action.")

    creds_payload = credentials or {}
    if not creds_payload and connection is not None:
        try:
            creds_payload = connection.get_credentials()
        except Exception:
            creds_payload = {}

    if not creds_payload:
        raise GoogleCalendarError("Google Calendar connection is required to perform calendar actions.")

    if _has_api_manager:
        try:
            api_manager = get_api_manager()
            if api_manager:
                enabled = api_manager.ensure_api_enabled("calendar")
                if enabled:
                    import asyncio

                    await asyncio.sleep(0.5)
        except Exception:
            pass

    client = GoogleCalendarClient(creds_payload)

    calendar_id = params.get("calendarId") or params.get("calendar_id") or "primary"
    send_updates = params.get("sendUpdates") or params.get("send_updates") or "none"

    try:
        if action == "LIST":
            time_min = params.get("timeMin") or params.get("time_min")
            time_max = params.get("timeMax") or params.get("time_max")
            if not time_min:
                time_min = _now_utc().isoformat()
            if not time_max:
                time_max = (_now_utc() + timedelta(days=7)).isoformat()

            max_results = int(params.get("maxResults") or params.get("max_results") or 10)
            query = params.get("query")
            show_cancelled = _boolean_param(params, "showCancelled", False)
            single_events = _boolean_param(params, "singleEvents", True)
            order_by = params.get("orderBy") or ("startTime" if single_events else None)

            result = await _execute_calendar_call(
                lambda: client.list_events(
                    calendar_id=calendar_id,
                    time_min=time_min,
                    time_max=time_max,
                    max_results=max_results,
                    q=query,
                    show_cancelled=show_cancelled,
                    single_events=single_events,
                    order_by=order_by,
                )
            )
            events = result.get("items", [])
            summary = f"Found {len(events)} event(s) between {time_min} and {time_max}."
            console.tool(f"[CALENDAR LIST] {summary}", task_id=task_id, agent_id=agent_id)
            return {
                "message": summary,
                "events": events,
                "count": len(events),
                "timeRange": {"timeMin": time_min, "timeMax": time_max},
            }

        if action == "GET":
            event_id = params.get("eventId") or params.get("event_id")
            if not event_id:
                raise ToolExecutionError(tool_name="calendar", detail="calendar GET requires params.eventId.")
            event = await _execute_calendar_call(
                lambda: client.get_event(calendar_id=calendar_id, event_id=event_id)
            )
            summary = f"Fetched event '{event.get('summary', 'Untitled')}'."
            console.tool(f"[CALENDAR GET] {summary}", task_id=task_id, agent_id=agent_id)
            return {"message": summary, "event": event}

        if action == "CREATE":
            summary_text = params.get("summary") or params.get("title")
            if not summary_text:
                raise ToolExecutionError(tool_name="calendar", detail="calendar CREATE requires params.summary.")

            start, end = _build_event_times(params)
            attendees = _normalize_attendees(params.get("attendees"))
            reminders = _normalize_reminders(params.get("reminders"))
            description = params.get("description")
            location = params.get("location")
            color_id = params.get("colorId") or params.get("color_id")
            conference = _boolean_param(params, "conference", False)

            event_body: Dict[str, Any] = {
                "summary": summary_text,
                "start": start,
                "end": end,
                "description": description,
                "location": location,
            }
            if attendees:
                event_body["attendees"] = attendees
            if reminders:
                event_body["reminders"] = reminders
            if color_id:
                event_body["colorId"] = str(color_id)
            if params.get("visibility"):
                event_body["visibility"] = params["visibility"]
            if params.get("transparency"):
                event_body["transparency"] = params["transparency"]
            if params.get("recurrence"):
                recurrence = params["recurrence"]
                if isinstance(recurrence, str):
                    recurrence = [recurrence]
                event_body["recurrence"] = recurrence

            event = await _execute_calendar_call(
                lambda: client.create_event(
                    calendar_id=calendar_id,
                    event_body=event_body,
                    send_updates=send_updates,
                    include_conference=conference,
                )
            )
            meeting_link = (
                event.get("hangoutLink")
                or event.get("conferenceData", {}).get("entryPoints", [{}])[0].get("uri")
            )
            summary = f"Created event '{event.get('summary', 'Untitled')}' on {calendar_id}."
            console.tool(f"[CALENDAR CREATE] {summary}", task_id=task_id, agent_id=agent_id)
            return {
                "message": summary,
                "event": event,
                "eventId": event.get("id"),
                "htmlLink": event.get("htmlLink"),
                "conferenceLink": meeting_link,
            }

        if action == "UPDATE":
            event_id = params.get("eventId") or params.get("event_id")
            if not event_id:
                raise ToolExecutionError(tool_name="calendar", detail="calendar UPDATE requires params.eventId.")

            updates: Dict[str, Any] = {}
            if params.get("summary") or params.get("title"):
                updates["summary"] = params.get("summary") or params.get("title")
            if params.get("description"):
                updates["description"] = params["description"]
            if params.get("location"):
                updates["location"] = params["location"]
            if params.get("colorId") or params.get("color_id"):
                updates["colorId"] = str(params.get("colorId") or params.get("color_id"))
            if params.get("recurrence"):
                recurrence = params["recurrence"]
                if isinstance(recurrence, str):
                    recurrence = [recurrence]
                updates["recurrence"] = recurrence
            if params.get("visibility"):
                updates["visibility"] = params["visibility"]
            if params.get("transparency"):
                updates["transparency"] = params["transparency"]

            if any(key in params for key in ("start", "start_time", "startDateTime")):
                updates["start"] = _build_event_times(params)[0]
            if any(key in params for key in ("end", "end_time", "endDateTime", "duration_minutes", "duration")):
                _, end = _build_event_times(params)
                updates["end"] = end

            attendees = _normalize_attendees(params.get("attendees"))
            if attendees:
                updates["attendees"] = attendees
            reminders = _normalize_reminders(params.get("reminders"))
            if reminders is not None:
                updates["reminders"] = reminders

            if not updates:
                raise ToolExecutionError(tool_name="calendar", detail="calendar UPDATE requires at least one field to update.")

            conference = _boolean_param(params, "conference", False)
            event = await _execute_calendar_call(
                lambda: client.update_event(
                    calendar_id=calendar_id,
                    event_id=event_id,
                    updates=updates,
                    send_updates=send_updates,
                    include_conference=conference,
                )
            )
            summary = f"Updated event '{event.get('summary', 'Untitled')}'."
            console.tool(f"[CALENDAR UPDATE] {summary}", task_id=task_id, agent_id=agent_id)
            return {"message": summary, "event": event, "eventId": event_id}

        if action == "DELETE":
            event_id = params.get("eventId") or params.get("event_id")
            if not event_id:
                raise ToolExecutionError(tool_name="calendar", detail="calendar DELETE requires params.eventId.")
            await _execute_calendar_call(
                lambda: client.delete_event(
                    calendar_id=calendar_id,
                    event_id=event_id,
                    send_updates=send_updates,
                )
            )
            summary = f"Deleted event '{event_id}' from {calendar_id}."
            console.tool(f"[CALENDAR DELETE] {summary}", task_id=task_id, agent_id=agent_id)
            return {"message": summary, "eventId": event_id}

        if action == "RESPOND":
            event_id = params.get("eventId") or params.get("event_id")
            attendee_email = params.get("attendee") or params.get("email") or params.get("attendeeEmail")
            response_status = params.get("responseStatus") or params.get("response_status")
            if not event_id:
                raise ToolExecutionError(tool_name="calendar", detail="calendar RESPOND requires params.eventId.")
            if not attendee_email:
                raise ToolExecutionError(tool_name="calendar", detail="calendar RESPOND requires attendee email (params.attendee).")
            if not response_status:
                raise ToolExecutionError(tool_name="calendar", detail="calendar RESPOND requires responseStatus (accepted/declined/tentative).")

            event = await _execute_calendar_call(
                lambda: client.respond_to_event(
                    calendar_id=calendar_id,
                    event_id=event_id,
                    attendee_email=attendee_email,
                    response_status=response_status,
                    comment=params.get("comment"),
                    send_updates=send_updates,
                )
            )
            summary = f"Updated RSVP for {attendee_email} → {response_status}."
            console.tool(f"[CALENDAR RESPOND] {summary}", task_id=task_id, agent_id=agent_id)
            return {"message": summary, "event": event, "eventId": event_id}

        # Unknown action - format beautiful error with available actions
        error_detail = (
            f"Unsupported calendar action '{action}'\n\n"
            f"📋 Available actions:\n"
            f"    • LIST - Search for events\n"
            f"    • GET - Fetch a specific event by ID\n"
            f"    • CREATE - Create a new event\n"
            f"    • UPDATE - Update event fields\n"
            f"    • DELETE - Delete an event\n"
            f"    • RESPOND - Update RSVP status\n\n"
            f"Use one of these actions in your next request."
        )
        raise ToolExecutionError(tool_name="calendar", detail=error_detail)

    except GoogleCalendarError as exc:
        console.error("[CALENDAR]", str(exc), task_id=task_id, agent_id=agent_id)
        raise

