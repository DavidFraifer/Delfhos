from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from delfhos.errors import ToolDefinitionError, ToolExecutionError


class GoogleSheetsError(ToolExecutionError):
    """Raised when the Google Sheets tool encounters an unrecoverable error."""

    def __init__(self, message: str):
        super().__init__(tool_name="gsheets", detail=message)


def _handle_sheets_api_error(exc: HttpError, operation: str) -> None:
    """Handle HttpError and provide helpful messages for API not enabled errors"""
    error_msg = str(exc)
    if exc.resp.status == 403 and 'accessNotConfigured' in error_msg:
        # Try to extract project number from error message
        import re
        project_match = re.search(r'project (\d+)', error_msg)
        project_num = project_match.group(1) if project_match else None
        enable_url = (
            f"https://console.developers.google.com/apis/api/sheets.googleapis.com/overview?project={project_num}"
            if project_num
            else "https://console.developers.google.com/apis/library/sheets.googleapis.com"
        )
        raise GoogleSheetsError(
            f"Google Sheets API is not enabled. Please enable it at: {enable_url}\n"
            f"Or configure automatic API enabling by setting GOOGLE_CLOUD_PROJECT_ID and GOOGLE_SERVICE_ACCOUNT_PATH"
        ) from exc
    raise GoogleSheetsError(f"Sheets {operation} failed: {exc}") from exc


_SHEETS_CLIENT_CACHE = {}

class GoogleSheetsClient:
    """Thin wrapper around the Google Sheets API for CORTEX agents."""

    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
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
        self._sheet_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}

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
        if cache_key in _SHEETS_CLIENT_CACHE:
            self._credentials, self._service = _SHEETS_CLIENT_CACHE[cache_key]
            return

        token_uri = payload.get("token_uri") or "https://oauth2.googleapis.com/token"
        scopes_raw = (
            self._scopes_override
            or payload.get("scopes")
            or payload.get("scope")
            or self.DEFAULT_SCOPES
        )

        scopes = _normalize_scopes(scopes_raw) or self.DEFAULT_SCOPES
        missing = []
        if not client_id:
            missing.append("client_id")
        if not client_secret:
            missing.append("client_secret")
        if not refresh_token:
            missing.append("refresh_token")
        if missing:
            available_keys = list(payload.keys()) if isinstance(payload, dict) else []
            raise GoogleSheetsError(
                f"Google Sheets connection is missing OAuth credentials: {', '.join(missing)}. "
                f"Available credential keys: {available_keys}. "
                "Please reconnect Google Sheets to continue."
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
            "sheets",
            "v4",
            credentials=self._credentials,
            cache_discovery=False,
        )
        _SHEETS_CLIENT_CACHE[cache_key] = (self._credentials, self._service)

    def _ensure_service(self):
        if not self._service:
            self._build_credentials()
        elif self._credentials and self._credentials.expired and self._credentials.refresh_token:
            self._credentials.refresh(Request())

    def read_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        *,
        value_render_option: str = "UNFORMATTED_VALUE",
        date_time_render_option: str = "SERIAL_NUMBER",
    ) -> Dict[str, Any]:
        try:
            self._ensure_service()
            request = (
                self._service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueRenderOption=value_render_option,
                    dateTimeRenderOption=date_time_render_option,
                )
            )
            return request.execute()
        except HttpError as exc:
            _handle_sheets_api_error(exc, "READ")

    def write_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: List[List[Any]],
        *,
        value_input_option: str = "USER_ENTERED",
    ) -> Dict[str, Any]:
        try:
            self._ensure_service()
            body = {"values": values}
            request = (
                self._service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption=value_input_option,
                    body=body,
                )
            )
            return request.execute()
        except HttpError as exc:
            _handle_sheets_api_error(exc, "WRITE")

    def append_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: List[List[Any]],
        *,
        value_input_option: str = "USER_ENTERED",
    ) -> Dict[str, Any]:
        try:
            self._ensure_service()
            request = (
                self._service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption=value_input_option,
                    insertDataOption="INSERT_ROWS",
                    body={"values": values},
                )
            )
            return request.execute()
        except HttpError as exc:
            _handle_sheets_api_error(exc, "APPEND")

    def clear_range(self, spreadsheet_id: str, range_name: str) -> Dict[str, Any]:
        try:
            self._ensure_service()
            request = (
                self._service.spreadsheets()
                .values()
                .clear(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    body={},
                )
            )
            return request.execute()
        except HttpError as exc:
            _handle_sheets_api_error(exc, "CLEAR")

    def batch_update(self, spreadsheet_id: str, requests: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not requests:
            return {}
        try:
            self._ensure_service()
            body = {"requests": requests}
            request = (
                self._service.spreadsheets()
                .batchUpdate(spreadsheetId=spreadsheet_id, body=body)
            )
            return request.execute()
        except HttpError as exc:
            _handle_sheets_api_error(exc, "batchUpdate")

    def _refresh_sheet_cache(self, spreadsheet_id: str):
        self._ensure_service()
        metadata = (
            self._service.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="sheets(properties(sheetId,title,index))",
            )
            .execute()
        )
        mapping = {}
        for sheet in metadata.get("sheets", []):
            props = sheet.get("properties", {})
            mapping[props.get("title", "")] = props
        self._sheet_cache[spreadsheet_id] = mapping

    def get_sheet_id(self, spreadsheet_id: str, sheet_name: str, *, create_if_missing: bool = True) -> int:
        normalized = normalize_sheet_title(sheet_name)
        if spreadsheet_id not in self._sheet_cache:
            self._refresh_sheet_cache(spreadsheet_id)
        mapping = self._sheet_cache.get(spreadsheet_id, {})
        if normalized in mapping:
            return mapping[normalized]["sheetId"]

        if not create_if_missing:
            raise GoogleSheetsError(f"Sheet '{sheet_name}' does not exist in spreadsheet.")

        add_sheet_request = {
            "requests": [
                {
                    "addSheet": {
                        "properties": {
                            "title": sheet_name,
                        }
                    }
                }
            ]
        }
        response = (
            self._service.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheet_id, body=add_sheet_request)
            .execute()
        )
        new_sheet = (
            response.get("replies", [{}])[0]
            .get("addSheet", {})
            .get("properties", {})
        )
        self._sheet_cache.setdefault(spreadsheet_id, {})[normalized] = new_sheet
        return new_sheet.get("sheetId")

    def ensure_sheet(self, spreadsheet_id: str, sheet_name: str) -> Tuple[str, int]:
        sheet_id = self.get_sheet_id(spreadsheet_id, sheet_name, create_if_missing=True)
        normalized = normalize_sheet_title(sheet_name)
        return normalized, sheet_id


def _normalize_scopes(scopes: Any) -> List[str]:
    if not scopes:
        return []
    if isinstance(scopes, str):
        return [scope.strip() for scope in scopes.split() if scope.strip()]
    if isinstance(scopes, (list, tuple, set)):
        normalized = []
        for item in scopes:
            if isinstance(item, str) and item.strip():
                normalized.append(item.strip())
        return normalized
    return []


_A1_TOKEN_RE = re.compile(r"^\$?([A-Za-z]+)?\$?(\d+)?$")


def split_sheet_and_range(range_str: str) -> Tuple[Optional[str], str]:
    """Return (sheet_name, range_without_sheet) for an A1 notation string."""
    if "!" not in range_str:
        return None, range_str
    sheet_part, rng = range_str.split("!", 1)
    sheet_part = sheet_part.strip()
    if sheet_part.startswith("'") and sheet_part.endswith("'"):
        sheet_part = sheet_part[1:-1]
    elif sheet_part.startswith('"') and sheet_part.endswith('"'):
        sheet_part = sheet_part[1:-1]
    return sheet_part, rng


def normalize_sheet_title(title: str) -> str:
    return (title or "").strip()


def column_letter_to_index(column: str) -> int:
    result = 0
    for char in column.upper():
        if not char.isalpha():
            raise ToolDefinitionError(detail=f"Invalid column reference '{column}'")
        result = result * 26 + (ord(char) - 64)
    return max(result - 1, 0)


def index_to_column_letter(index: int) -> str:
    if index < 0:
        raise ToolDefinitionError(detail="Column index must be non-negative")
    result = ""
    current = index + 1
    while current:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def parse_a1_token(token: str) -> Tuple[Optional[int], Optional[int]]:
    """Parse a single A1 token (e.g., A1, B, 3) into zero-based column and row indices."""
    token = token.strip()
    if not token:
        return None, None
    match = _A1_TOKEN_RE.match(token)
    if not match:
        raise ToolDefinitionError(detail=f"Invalid A1 reference '{token}'")
    col_letters, row_digits = match.groups()
    col_index = column_letter_to_index(col_letters) if col_letters else None
    row_index = int(row_digits) - 1 if row_digits else None
    return col_index, row_index


def a1_to_grid_range(a1_range: str, sheet_id: int) -> Dict[str, Any]:
    """Convert an A1 range (without sheet prefix) to a Sheets GridRange."""
    if not a1_range:
        raise ToolDefinitionError(detail="Range string cannot be empty")
    if ":" in a1_range:
        start_token, end_token = a1_range.split(":", 1)
    else:
        start_token, end_token = a1_range, None

    start_col, start_row = parse_a1_token(start_token)
    end_col, end_row = parse_a1_token(end_token) if end_token else (None, None)

    grid_range: Dict[str, Any] = {"sheetId": sheet_id}
    if start_row is not None:
        grid_range["startRowIndex"] = start_row
        grid_range["endRowIndex"] = (end_row if end_row is not None else start_row) + 1
    elif end_row is not None:
        grid_range["startRowIndex"] = 0
        grid_range["endRowIndex"] = end_row + 1

    if start_col is not None:
        grid_range["startColumnIndex"] = start_col
        grid_range["endColumnIndex"] = (end_col if end_col is not None else start_col) + 1
    elif end_col is not None:
        grid_range["startColumnIndex"] = 0
        grid_range["endColumnIndex"] = end_col + 1

    return grid_range

