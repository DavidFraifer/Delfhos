from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from delfhos.errors import ToolExecutionError


class GoogleDocsError(ToolExecutionError):
    """Raised when the Google Docs tool encounters an unrecoverable error."""

    def __init__(self, message: str):
        super().__init__(tool_name="docs", detail=message)


def _handle_api_error(exc: HttpError, operation: str) -> None:
    """Handle HttpError and provide helpful messages for API not enabled errors"""
    error_msg = str(exc)
    if (exc.resp.status == 403 and 'accessNotConfigured' in error_msg) or \
       'SERVICE_DISABLED' in error_msg or \
       'has not been used in project' in error_msg:
        import re
        project_match = re.search(r'project (\d+)', error_msg)
        project_num = project_match.group(1) if project_match else None
        enable_url = (
            f"https://console.developers.google.com/apis/api/docs.googleapis.com/overview?project={project_num}"
            if project_num
            else "https://console.developers.google.com/apis/library/docs.googleapis.com"
        )
        raise GoogleDocsError(
            f"Google Docs API is not enabled. Please enable it at: {enable_url}\n"
            f"Or configure automatic API enabling by setting GOOGLE_CLOUD_PROJECT_ID and GOOGLE_SERVICE_ACCOUNT_PATH"
        ) from exc
    raise GoogleDocsError(f"Docs {operation} failed: {exc}") from exc


def _normalize_scopes(scopes: Any) -> List[str]:
    """Normalize scopes to a list of strings"""
    if isinstance(scopes, str):
        return [s.strip() for s in scopes.split(",") if s.strip()]
    if isinstance(scopes, list):
        return [str(s).strip() for s in scopes if str(s).strip()]
    return []


_DOCS_CLIENT_CACHE = {}

class GoogleDocsClient:
    """Thin wrapper around the Google Docs API for CORTEX agents."""

    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive.file",
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
        self._drive_service = None

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
        if cache_key in _DOCS_CLIENT_CACHE:
            self._credentials, self._service, self._drive_service = _DOCS_CLIENT_CACHE[cache_key]
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
            raise GoogleDocsError(
                "Google Docs connection is missing OAuth credentials. "
                "Please reconnect Google Docs to continue."
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
            "docs",
            "v1",
            credentials=self._credentials,
            cache_discovery=False,
        )
        self._drive_service = build(
            "drive",
            "v3",
            credentials=self._credentials,
            cache_discovery=False,
        )
        _DOCS_CLIENT_CACHE[cache_key] = (self._credentials, self._service, self._drive_service)

    @property
    def service(self):
        """Lazy initialization of the Docs API service"""
        if self._service is None:
            self._build_credentials()
        return self._service

    @property
    def drive_service(self):
        """Lazy initialization of the Drive API service"""
        if self._drive_service is None:
            self._build_credentials()
        return self._drive_service

    def get_document(self, document_id: str) -> Dict[str, Any]:
        """Get a document by ID"""
        try:
            return self.service.documents().get(documentId=document_id).execute()
        except HttpError as exc:
            _handle_api_error(exc, "get_document")

    def create_document(self, title: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a new Google Doc"""
        try:
            # Create the document
            document = self.service.documents().create(body={"title": title}).execute()
            document_id = document.get("documentId")
            
            # Move to folder if specified
            if folder_id and document_id:
                try:
                    file = self.drive_service.files().get(fileId=document_id, fields="parents").execute()
                    previous_parents = ",".join(file.get("parents", []))
                    self.drive_service.files().update(
                        fileId=document_id,
                        addParents=folder_id,
                        removeParents=previous_parents,
                        fields="id, parents",
                    ).execute()
                except HttpError:
                    # Non-fatal - document created even if folder move fails
                    pass
            
            return document
        except HttpError as exc:
            _handle_api_error(exc, "create_document")

    def batch_update(
        self,
        document_id: str,
        requests: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Execute batch update requests on a document"""
        try:
            return (
                self.service.documents()
                .batchUpdate(documentId=document_id, body={"requests": requests})
                .execute()
            )
        except HttpError as exc:
            _handle_api_error(exc, "batch_update")

    def insert_text(
        self,
        document_id: str,
        text: str,
        index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Insert text at a specific index (or end if not specified)"""
        if index is None:
            # Get document to find end index
            doc = self.get_document(document_id)
            index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1) - 1
        
        request = {
            "insertText": {
                "location": {"index": index},
                "text": text,
            }
        }
        return self.batch_update(document_id, [request])

    def delete_text(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
    ) -> Dict[str, Any]:
        """Delete text between start_index and end_index"""
        request = {
            "deleteContentRange": {
                "range": {
                    "startIndex": start_index,
                    "endIndex": end_index,
                }
            }
        }
        return self.batch_update(document_id, [request])

    def format_text(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        underline: Optional[bool] = None,
        strikethrough: Optional[bool] = None,
        font_size: Optional[float] = None,
        foreground_color: Optional[Dict[str, float]] = None,
        background_color: Optional[Dict[str, float]] = None,
        font_family: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Format text with various style options"""
        text_style = {}
        if bold is not None:
            text_style["bold"] = bold
        if italic is not None:
            text_style["italic"] = italic
        if underline is not None:
            text_style["underline"] = underline
        if strikethrough is not None:
            text_style["strikethrough"] = strikethrough
        if font_size is not None:
            text_style["fontSize"] = {"magnitude": font_size, "unit": "PT"}
        if foreground_color is not None:
            text_style["foregroundColor"] = {
                "color": {
                    "rgbColor": foreground_color
                }
            }
        if background_color is not None:
            text_style["backgroundColor"] = {
                "color": {
                    "rgbColor": background_color
                }
            }
        if font_family is not None:
            text_style["weightedFontFamily"] = {"fontFamily": font_family}

        request = {
            "updateTextStyle": {
                "range": {
                    "startIndex": start_index,
                    "endIndex": end_index,
                },
                "textStyle": text_style,
                "fields": ",".join(text_style.keys()),
            }
        }
        return self.batch_update(document_id, [request])

    def insert_paragraph_break(
        self,
        document_id: str,
        index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Insert a paragraph break"""
        if index is None:
            doc = self.get_document(document_id)
            index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1) - 1
        
        request = {
            "insertParagraphBreak": {
                "location": {"index": index},
            }
        }
        return self.batch_update(document_id, [request])

    def set_paragraph_style(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        named_style: Optional[str] = None,
        alignment: Optional[str] = None,
        line_spacing: Optional[float] = None,
        space_above: Optional[float] = None,
        space_below: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Set paragraph style (heading, normal, etc.)"""
        paragraph_style = {}
        if named_style is not None:
            paragraph_style["namedStyleType"] = named_style
        if alignment is not None:
            paragraph_style["alignment"] = alignment.upper()
        if line_spacing is not None:
            paragraph_style["lineSpacing"] = line_spacing
        if space_above is not None:
            paragraph_style["spaceAbove"] = {"magnitude": space_above, "unit": "PT"}
        if space_below is not None:
            paragraph_style["spaceBelow"] = {"magnitude": space_below, "unit": "PT"}

        request = {
            "updateParagraphStyle": {
                "range": {
                    "startIndex": start_index,
                    "endIndex": end_index,
                },
                "paragraphStyle": paragraph_style,
                "fields": ",".join(paragraph_style.keys()),
            }
        }
        return self.batch_update(document_id, [request])

