from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from delfhos.errors import ToolExecutionError


class GoogleDriveError(ToolExecutionError):
    """Raised when the Google Drive tool encounters an unrecoverable error."""

    def __init__(self, message: str):
        super().__init__(tool_name="drive", detail=message)


def _handle_api_error(exc: HttpError, operation: str) -> None:
    """Handle HttpError and provide helpful messages for API not enabled errors"""
    error_msg = str(exc)
    if exc.resp.status == 403 and 'accessNotConfigured' in error_msg:
        # Try to extract project number from error message
        import re
        project_match = re.search(r'project (\d+)', error_msg)
        project_num = project_match.group(1) if project_match else None
        enable_url = (
            f"https://console.developers.google.com/apis/api/drive.googleapis.com/overview?project={project_num}"
            if project_num
            else "https://console.developers.google.com/apis/library/drive.googleapis.com"
        )
        raise GoogleDriveError(
            f"Google Drive API is not enabled. Please enable it at: {enable_url}\n"
            f"Or configure automatic API enabling by setting GOOGLE_CLOUD_PROJECT_ID and GOOGLE_SERVICE_ACCOUNT_PATH"
        ) from exc
    raise GoogleDriveError(f"Drive {operation} failed: {exc}") from exc



_DRIVE_CLIENT_CACHE = {}

class GoogleDriveClient:
    """Thin wrapper around the Google Drive API for CORTEX agents."""

    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/drive",
    ]

    # MIME types for common Google Workspace files
    MIME_TYPES = {
        "spreadsheet": "application/vnd.google-apps.spreadsheet",
        "document": "application/vnd.google-apps.document",
        "presentation": "application/vnd.google-apps.presentation",
        "folder": "application/vnd.google-apps.folder",
        "file": "application/vnd.google-apps.file",
    }

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
        if cache_key in _DRIVE_CLIENT_CACHE:
            self._credentials, self._service = _DRIVE_CLIENT_CACHE[cache_key]
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
            raise GoogleDriveError(
                "Google Drive connection is missing OAuth credentials. "
                "Please reconnect Google Drive to continue."
            )

        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret= client_secret,
            scopes=scopes,
        )
        if not credentials.valid and credentials.refresh_token:
            credentials.refresh(Request())

        self._credentials = credentials
        self._service = build(
            "drive",
            "v3",
            credentials=self._credentials,
            cache_discovery=False,
        )
        _DRIVE_CLIENT_CACHE[cache_key] = (self._credentials, self._service)

    def _ensure_service(self):
        if not self._service:
            self._build_credentials()
        elif self._credentials and self._credentials.expired and self._credentials.refresh_token:
            self._credentials.refresh(Request())

    def search_files(
        self,
        query: Optional[str] = None,
        *,
        name: Optional[str] = None,
        mime_type: Optional[str] = None,
        folder_id: Optional[str] = None,
        trashed: bool = False,
        page_size: int = 100,
        fields: str = "files(id,name,mimeType,parents,createdTime,modifiedTime,size,webViewLink)",
    ) -> Dict[str, Any]:
        """
        Search for files in Google Drive.
        
        Args:
            query: Custom query string (e.g., "name contains 'Report'")
            name: Exact name match
            mime_type: MIME type filter (e.g., "application/vnd.google-apps.spreadsheet")
            folder_id: Search within specific folder
            trashed: Include trashed files
            page_size: Maximum results to return
            fields: Fields to return in response
        
        Returns:
            Dict with 'files' list containing file metadata
        """
        try:
            self._ensure_service()
            
            # Build query
            query_parts = []
            if not trashed:
                query_parts.append("trashed=false")
            if name:
                query_parts.append(f"name='{name}'")
            if mime_type:
                query_parts.append(f"mimeType='{mime_type}'")
            if folder_id:
                query_parts.append(f"'{folder_id}' in parents")
            if query:
                query_parts.append(query)
            
            q = " and ".join(query_parts) if query_parts else None
            
            request = self._service.files().list(
                q=q,
                pageSize=page_size,
                fields=f"nextPageToken,{fields}",
                orderBy="modifiedTime desc",
            )
            return request.execute()
        except HttpError as exc:
            _handle_api_error(exc, "SEARCH")

    def get_file(self, file_id: str, fields: Optional[str] = None) -> Dict[str, Any]:
        """
        Get file metadata by ID.
        
        Args:
            file_id: Google Drive file ID
            fields: Comma-separated list of fields to return
        
        Returns:
            File metadata dict
        """
        try:
            self._ensure_service()
            default_fields = "id,name,mimeType,parents,createdTime,modifiedTime,size,webViewLink,permissions"
            request = self._service.files().get(
                fileId=file_id,
                fields=fields or default_fields,
            )
            return request.execute()
        except HttpError as exc:
            _handle_api_error(exc, "GET")

    def create_file(
        self,
        name: str,
        *,
        mime_type: Optional[str] = None,
        folder_id: Optional[str] = None,
        content: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """
        Create a new file in Google Drive.
        
        Args:
            name: File name
            mime_type: MIME type (defaults to Google Docs if not specified)
            folder_id: Parent folder ID
            content: File content (for non-Google Workspace files)
        
        Returns:
            Created file metadata
        """
        try:
            self._ensure_service()
            
            file_metadata = {"name": name}
            if folder_id:
                file_metadata["parents"] = [folder_id]
            
            # If no MIME type specified and no content, default to Google Docs
            if not mime_type and not content:
                mime_type = self.MIME_TYPES["document"]
            
            if mime_type:
                file_metadata["mimeType"] = mime_type
            
            if content:
                # Upload file with content
                from io import BytesIO
                from googleapiclient.http import MediaIoBaseUpload
                media_body = MediaIoBaseUpload(
                    BytesIO(content),
                    mimetype=mime_type or "application/octet-stream",
                    resumable=True,
                )
                request = self._service.files().create(
                    body=file_metadata,
                    media_body=media_body,
                    fields="id,name,mimeType,parents,createdTime,webViewLink",
                )
            else:
                # Create empty Google Workspace file
                request = self._service.files().create(
                    body=file_metadata,
                    fields="id,name,mimeType,parents,createdTime,webViewLink",
                )
            
            return request.execute()
        except HttpError as exc:
            _handle_api_error(exc, "CREATE")

    def update_file(
        self,
        file_id: str,
        *,
        name: Optional[str] = None,
        folder_id: Optional[str] = None,
        content: Optional[bytes] = None,
        mime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update file metadata and/or content.
        
        Args:
            file_id: File ID to update
            name: New file name
            folder_id: Move to new folder (set to None to remove from all folders)
            content: New file content
            mime_type: MIME type for content
        
        Returns:
            Updated file metadata
        """
        try:
            self._ensure_service()
            
            file_metadata = {}
            if name is not None:
                file_metadata["name"] = name
            if folder_id is not None:
                # Get current parents first
                current_file = self.get_file(file_id, fields="parents")
                previous_parents = ",".join(current_file.get("parents", []))
                file_metadata["addParents"] = folder_id
                file_metadata["removeParents"] = previous_parents
            
            if content:
                # Update file with new content
                from io import BytesIO
                from googleapiclient.http import MediaIoBaseUpload
                media_body = MediaIoBaseUpload(
                    BytesIO(content),
                    mimetype=mime_type or "application/octet-stream",
                    resumable=True,
                )
                request = self._service.files().update(
                    fileId=file_id,
                    body=file_metadata,
                    media_body=media_body,
                    fields="id,name,mimeType,parents,modifiedTime,webViewLink",
                )
            else:
                # Update metadata only
                request = self._service.files().update(
                    fileId=file_id,
                    body=file_metadata,
                    fields="id,name,mimeType,parents,modifiedTime,webViewLink",
                )
            
            return request.execute()
        except HttpError as exc:
            _handle_api_error(exc, "UPDATE")

    def delete_file(self, file_id: str, *, permanent: bool = False) -> Dict[str, Any]:
        """
        Delete a file (move to trash or permanently delete).
        
        Args:
            file_id: File ID to delete
            permanent: If True, permanently delete; if False, move to trash
        
        Returns:
            Empty dict on success
        """
        try:
            self._ensure_service()
            if permanent:
                request = self._service.files().delete(fileId=file_id)
            else:
                request = self._service.files().update(
                    fileId=file_id,
                    body={"trashed": True},
                )
            request.execute()
            return {}
        except HttpError as exc:
            _handle_api_error(exc, "DELETE")

    def list_permissions(self, file_id: str) -> Dict[str, Any]:
        """
        List permissions for a file.
        
        Args:
            file_id: File ID
        
        Returns:
            Dict with 'permissions' list
        """
        try:
            self._ensure_service()
            request = self._service.permissions().list(
                fileId=file_id,
                fields="permissions(id,type,role,emailAddress,displayName)",
            )
            return request.execute()
        except HttpError as exc:
            _handle_api_error(exc, "LIST_PERMISSIONS")

    def create_permission(
        self,
        file_id: str,
        *,
        role: str = "reader",
        type: str = "user",
        email: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a permission (share file).
        
        Args:
            file_id: File ID
            role: Permission role (reader, writer, commenter, owner)
            type: Permission type (user, group, domain, anyone)
            email: Email address (for user/group type)
            domain: Domain (for domain type)
        
        Returns:
            Created permission metadata
        """
        try:
            self._ensure_service()
            
            permission = {"role": role, "type": type}
            if email:
                permission["emailAddress"] = email
            if domain:
                permission["domain"] = domain
            
            request = self._service.permissions().create(
                fileId=file_id,
                body=permission,
                fields="id,type,role,emailAddress",
            )
            return request.execute()
        except HttpError as exc:
            _handle_api_error(exc, "CREATE_PERMISSION")

    def delete_permission(self, file_id: str, permission_id: str) -> Dict[str, Any]:
        """
        Delete a permission (unshare file).
        
        Args:
            file_id: File ID
            permission_id: Permission ID to delete
        
        Returns:
            Empty dict on success
        """
        try:
            self._ensure_service()
            request = self._service.permissions().delete(
                fileId=file_id,
                permissionId=permission_id,
            )
            request.execute()
            return {}
        except HttpError as exc:
            _handle_api_error(exc, "DELETE_PERMISSION")

    def create_folder(self, name: str, *, folder_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new folder.
        
        Args:
            name: Folder name
            folder_id: Parent folder ID
        
        Returns:
            Created folder metadata
        """
        return self.create_file(
            name,
            mime_type=self.MIME_TYPES["folder"],
            folder_id=folder_id,
        )


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

