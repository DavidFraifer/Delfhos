from __future__ import annotations

from typing import Any, Dict
from typing import Optional
from delfhos.errors import ToolExecutionError
import sys
import os

from ...utils.console import console
from .gdrive_client import GoogleDriveClient, GoogleDriveError

# Try to import API manager for automatic API enabling
# Add parent directories to path to find api module
_api_manager = None
_has_api_manager = False
try:
    # Try to find api module (could be in parent directory)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # From cortex/_engine/tools/ -> go up 3 levels to project root
    project_root = os.path.abspath(os.path.join(current_dir, '../../..'))
    api_path = os.path.join(project_root, 'api')
    if os.path.exists(api_path):
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from api.utils.google_api_manager import get_api_manager
        _has_api_manager = True
except (ImportError, Exception) as e:
    _has_api_manager = False
    # Debug: uncomment to see import errors
    # print(f"[DRIVE TOOL] Failed to import API manager: {e}")


async def gdrive_tool(
    user_input: Any = "",
    task_id: Optional[str] = None,
    light_llm: Optional[str] = None,
    heavy_llm: Optional[str] = None,
    agent_id: Optional[str] = None,
    validation_mode: bool = False,
    credentials: Optional[Dict[str, Any]] = None,
    connection: Any = None,
    **kwargs
):
    """
    Google Drive tool - Unified DSL wrapper.
    Handles file operations: search, get, create, update, delete, and permissions.
    """
    context = user_input if isinstance(user_input, dict) else {}
    action = (context.get("action") or "").upper()
    params = context.get("params") or {}

    if not action:
        raise ToolExecutionError(tool_name="drive", detail="Google Drive tool requires an action.")

    creds_payload = credentials or {}
    if not creds_payload and connection is not None:
        try:
            creds_payload = connection.get_credentials()
        except Exception:
            creds_payload = {}

    # Try to ensure Drive API is enabled automatically
    if _has_api_manager:
        try:
            api_manager = get_api_manager()
            if api_manager:
                enabled = api_manager.ensure_api_enabled('drive')
                if enabled:
                    # Only wait if API was just enabled (not if it was already enabled)
                    # Reduced wait time - API usually propagates quickly
                    import asyncio
                    await asyncio.sleep(0.5)
        except Exception:
            # Non-fatal - continue even if API enabling fails
            pass

    client = GoogleDriveClient(creds_payload)

    # Map MIME type aliases to full MIME types
    mime_type_map = {
        "spreadsheet": "application/vnd.google-apps.spreadsheet",
        "document": "application/vnd.google-apps.document",
        "presentation": "application/vnd.google-apps.presentation",
        "folder": "application/vnd.google-apps.folder",
    }

    if action == "SEARCH":
        name = params.get("name")
        mime_type = params.get("mimeType") or params.get("mime_type")
        folder_id = params.get("folderId") or params.get("folder_id")
        query = params.get("query")
        trashed = params.get("trashed", False)
        page_size = params.get("pageSize") or params.get("page_size", 100)

        # Convert MIME type alias if provided
        if mime_type and mime_type in mime_type_map:
            mime_type = mime_type_map[mime_type]

        result = client.search_files(
            query=query,
            name=name,
            mime_type=mime_type,
            folder_id=folder_id,
            trashed=trashed,
            page_size=page_size,
        )
        files = result.get("files", [])
        summary = f"Found {len(files)} file(s)"
        console.tool(f"[DRIVE SEARCH] {summary}", task_id=task_id, agent_id=agent_id)
        return {
            "message": summary,
            "files": files,
            "count": len(files),
        }

    if action == "GET":
        file_id = params.get("fileId") or params.get("file_id")
        if not file_id:
            raise ToolExecutionError(tool_name="drive", detail="drive GET requires params.fileId.")
        
        result = client.get_file(file_id)
        summary = f"Retrieved file: {result.get('name', 'Unknown')}"
        console.tool(f"[DRIVE GET] {summary}", task_id=task_id, agent_id=agent_id)
        return {
            "message": summary,
            "file": result,
            "fileId": file_id,
        }

    if action == "CREATE":
        name = params.get("name")
        if not name:
            raise ToolExecutionError(tool_name="drive", detail="drive CREATE requires params.name.")
        
        mime_type = params.get("mimeType") or params.get("mime_type")
        folder_id = params.get("folderId") or params.get("folder_id")
        content = params.get("content")  # bytes or base64 string
        
        # Convert MIME type alias if provided
        if mime_type and mime_type in mime_type_map:
            mime_type = mime_type_map[mime_type]
        
        # Determine actual file content
        file_path = params.get("file_path")
        file_content = None
        if content:
            if isinstance(content, str):
                import base64
                file_content = base64.b64decode(content)
            elif isinstance(content, bytes):
                file_content = content
        elif file_path and os.path.exists(file_path):
            with open(file_path, "rb") as f:
                file_content = f.read()
        
        result = client.create_file(
            name=name,
            mime_type=mime_type,
            folder_id=folder_id,
            content=file_content,
        )
        summary = f"Created file: {result.get('name', 'Unknown')} (ID: {result.get('id')})"
        console.tool(f"[DRIVE CREATE] {summary}", task_id=task_id, agent_id=agent_id)
        return {
            "message": summary,
            "file": result,
            "fileId": result.get("id"),
        }

    if action == "UPDATE":
        file_id = params.get("fileId") or params.get("file_id")
        if not file_id:
            raise ToolExecutionError(tool_name="drive", detail="drive UPDATE requires params.fileId.")
        
        name = params.get("name")
        folder_id = params.get("folderId") or params.get("folder_id")
        content = params.get("content")
        mime_type = params.get("mimeType") or params.get("mime_type")
        
        # Convert MIME type alias if provided
        if mime_type and mime_type in mime_type_map:
            mime_type = mime_type_map[mime_type]
        
        # Determine actual file content
        file_path = params.get("file_path")
        file_content = None
        if content:
            if isinstance(content, str):
                import base64
                file_content = base64.b64decode(content)
            elif isinstance(content, bytes):
                file_content = content
        elif file_path and os.path.exists(file_path):
            with open(file_path, "rb") as f:
                file_content = f.read()
        
        result = client.update_file(
            file_id=file_id,
            name=name,
            folder_id=folder_id,
            content=file_content,
            mime_type=mime_type,
        )
        summary = f"Updated file: {result.get('name', 'Unknown')} (ID: {file_id})"
        console.tool(f"[DRIVE UPDATE] {summary}", task_id=task_id, agent_id=agent_id)
        return {
            "message": summary,
            "file": result,
            "fileId": file_id,
        }

    if action == "DELETE":
        file_id = params.get("fileId") or params.get("file_id")
        if not file_id:
            raise ToolExecutionError(tool_name="drive", detail="drive DELETE requires params.fileId.")
        
        permanent = params.get("permanent", False)
        client.delete_file(file_id, permanent=permanent)
        action_type = "permanently deleted" if permanent else "moved to trash"
        summary = f"File {action_type}: {file_id}"
        console.tool(f"[DRIVE DELETE] {summary}", task_id=task_id, agent_id=agent_id)
        return {
            "message": summary,
            "fileId": file_id,
            "permanent": permanent,
        }

    if action == "LIST_PERMISSIONS":
        file_id = params.get("fileId") or params.get("file_id")
        if not file_id:
            raise ToolExecutionError(tool_name="drive", detail="drive LIST_PERMISSIONS requires params.fileId.")
        
        result = client.list_permissions(file_id)
        permissions = result.get("permissions", [])
        summary = f"Found {len(permissions)} permission(s) for file {file_id}"
        console.tool(f"[DRIVE LIST_PERMISSIONS] {summary}", task_id=task_id, agent_id=agent_id)
        return {
            "message": summary,
            "permissions": permissions,
            "fileId": file_id,
            "count": len(permissions),
        }

    if action == "SHARE":
        file_id = params.get("fileId") or params.get("file_id")
        if not file_id:
            raise ToolExecutionError(tool_name="drive", detail="drive SHARE requires params.fileId.")
        
        role = params.get("role", "reader")
        perm_type = params.get("type", "user")
        email = params.get("email") or params.get("emailAddress")
        domain = params.get("domain")
        
        result = client.create_permission(
            file_id=file_id,
            role=role,
            type=perm_type,
            email=email,
            domain=domain,
        )
        summary = f"Shared file {file_id} with {role} permission"
        console.tool(f"[DRIVE SHARE] {summary}", task_id=task_id, agent_id=agent_id)
        return {
            "message": summary,
            "permission": result,
            "fileId": file_id,
        }

    if action == "UNSHARE":
        file_id = params.get("fileId") or params.get("file_id")
        if not file_id:
            raise ToolExecutionError(tool_name="drive", detail="drive UNSHARE requires params.fileId.")
        
        permission_id = params.get("permissionId") or params.get("permission_id")
        if not permission_id:
            raise ToolExecutionError(tool_name="drive", detail="drive UNSHARE requires params.permissionId.")
        
        client.delete_permission(file_id, permission_id)
        summary = f"Removed permission {permission_id} from file {file_id}"
        console.tool(f"[DRIVE UNSHARE] {summary}", task_id=task_id, agent_id=agent_id)
        return {
            "message": summary,
            "fileId": file_id,
            "permissionId": permission_id,
        }

    raise ToolExecutionError(tool_name="drive", detail=f"Unsupported drive action '{action}'\n\n📋 Available Google Drive actions:\n    • SEARCH - Find files by name/type/query\n    • GET - Get file metadata by ID\n    • CREATE - Create folders (NOT for Docs/Sheets - use specific tools)\n    • UPDATE - Update file metadata or permissions\n    • DELETE - Delete files\n    • DOWNLOAD - Download file content\n    • UNSHARE - Remove permissions from file\n\nUse one of these actions in your next request.")

