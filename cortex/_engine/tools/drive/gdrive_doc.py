DRIVE_DOC = """
TOOL: drive
DESCRIPTION: Search, create, modify, delete, and manage permissions for Google Drive files and folders.
ACTIONS:
1. "SEARCH": params:{name:"filename", mimeType:"spreadsheet", folderId:"parent_id"} → Returns list of matching files.
2. "GET": params:{fileId:"abc123"} → Returns file metadata.
3. "CREATE": params:{name:"New File", mimeType:"spreadsheet", folderId:"parent_id"} → Creates file/folder.
4. "UPDATE": params:{fileId:"abc123", name:"New Name", folderId:"new_parent"} → Updates file metadata/location.
5. "DELETE": params:{fileId:"abc123", permanent:false} → Deletes file (trash or permanent).
6. "LIST_PERMISSIONS": params:{fileId:"abc123"} → Lists file permissions.
7. "SHARE": params:{fileId:"abc123", role:"reader", type:"user", email:"user@example.com"} → Shares file.
8. "UNSHARE": params:{fileId:"abc123", permissionId:"perm_id"} → Removes permission.

MIME TYPES: "spreadsheet" (Sheets), "document" (Docs), "presentation" (Slides), "folder", or custom (e.g., "text/plain", "application/pdf")
PERMISSION ROLES: "reader" (view), "commenter" (view+comment), "writer" (view+comment+edit), "owner" (full control)
PERMISSION TYPES: "user" (requires email), "group" (requires email), "domain" (requires domain), "anyone" (public link)

EXAMPLES:
- drive(action:"SEARCH", params:{name:"Sales Report", mimeType:"spreadsheet"})
- drive(action:"CREATE", params:{name:"Q4 Data", mimeType:"spreadsheet"})
- drive(action:"UPDATE", params:{fileId:"abc123", name:"New Name"}) or drive(action:"UPDATE", params:{fileId:"abc123", folderId:"new_folder_id"})
- drive(action:"SHARE", params:{fileId:"abc123", role:"writer", type:"user", email:"user@example.com"}) or drive(action:"SHARE", params:{fileId:"abc123", role:"reader", type:"anyone"})
""".strip()

