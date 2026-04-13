"""
Tool Registry System
Provides tool capability definitions and Python API documentation for agent code generation
"""

from typing import Dict, List, Optional, Any, Set, Tuple


class ToolActionSpec:
    """Specification for a single tool action"""
    
    def __init__(self, action: str, description: str, parameters: Dict[str, str]):
        """
        Args:
            action: Action name (e.g., "READ", "SEND")
            description: Brief description of what the action does
            parameters: Dict of parameter_name -> parameter_description
        """
        self.action = action
        self.description = description
        self.parameters = parameters
    


class ToolCapability:
    """Defines all capabilities and actions for a tool"""
    
    def __init__(self, tool_name: str, actions: List[ToolActionSpec]):
        self.tool_name = tool_name
        self.actions = actions
    


# Define Gmail tool capabilities
GMAIL_CAPABILITY = ToolCapability(
    tool_name="gmail",
    actions=[
        ToolActionSpec(
            action="READ",
            description="Search/read emails → {id, subject, from_email, body, date}",
            parameters={
                "query": "search keywords",
                "max": "max results (default 20)",
                "from": "ISO date (after)",
                "to": "ISO date (before)",
                "mailbox": "inbox/sent/drafts",
                "include_body": "true for full content"
            }
        ),
        ToolActionSpec(
            action="SEND",
            description="Send email",
            parameters={
                "to": "recipient(s)",
                "subject": "subject",
                "body": "body",
                "reply_to": "message ID to reply"
            }
        )
    ]
)

# Define Google Sheets tool capabilities
SHEETS_CAPABILITY = ToolCapability(
    tool_name="sheets",
    actions=[
        ToolActionSpec(
            action="CREATE",
            description="Create a new Google Spreadsheet",
            parameters={
                "title": "spreadsheet title",
                "folderId": "parent folder ID (optional)",
            },
        ),
        ToolActionSpec(
            action="READ",
            description="Read spreadsheet data (returns 2D array)",
            parameters={
                "spreadsheet_id": "spreadsheet ID",
                "range": "Sheet!A1:C10",
                "value_render_option": "optional render mode",
            },
        ),
        ToolActionSpec(
            action="BATCH",
            description=(
                "Execute SheetOps commands sequentially. "
                "CRITICAL: ops must be a list of STRINGS only (never JSON objects like {'operation':'w'}). "
                "Format: ['@SheetName', 'command args...', 'command args...']. "
                "Commands: w (write), a (append), clr (clear), fmt (format), chart/c (chart), csv (import CSV), ins (insert), del (delete), mg (merge), auto (auto-resize), v (validation), p (protection). "
                "NEVER use bare ranges like 'A1:C1' as commands - always prefix with command letter."
            ),
            parameters={
                "spreadsheet_id": "spreadsheet ID",
                "ops": (
                    "REQUIRED: Array of STRING commands (never JSON objects). "
                    "Format: ['@SheetName', 'command1 args', 'command2 args', ...]. "
                    "Each element must be a plain string. "
                    "Examples: "
                    "'@Sheet1' (set sheet context), "
                    "'w A1 | [\\'Header1\\',\\'Header2\\']' (write header row), "
                    "'w A2 | [\\'Data1\\',\\'Data2\\']' (write data row), "
                    "'a | [\\'Row1\\',\\'Row2\\']' (append row), "
                    "'clr A1:C10' (clear range), "
                    "'fmt A1:C1 | header,bold' (format header), "
                    "'csv A1 | \"col1,col2\\\\n1,2\\\\n3,4\"' (import CSV text starting at A1), "
                    "'chart bar | A1:B10 | A12' (create bar chart with explicit data range and anchor cell), "
                    "'c | bar | A1:B10 | A12' (shorthand for chart: type | DATA_RANGE | DEST_CELL). "
                    "For any chart/c command you MUST provide a DATA RANGE as second argument (e.g., 'A1:B10'). "
                    "NEVER use: {'operation':'w', 'range':'A1'} or any JSON objects. "
                    "ALWAYS use: plain strings like 'w A1 | [values]'."
                ),
                "sheet": "default sheet name (optional, used if @SheetName not specified)",
            },
        ),
    ],
)

# Define Drive tool capabilities
DRIVE_CAPABILITY = ToolCapability(
    tool_name="drive",
    actions=[
        ToolActionSpec(
            action="SEARCH",
            description="Search for files by name, type, or query",
            parameters={
                "name": "exact file name",
                "mimeType": "file type (spreadsheet/document/presentation/folder)",
                "folderId": "parent folder ID",
                "query": "custom search query"
            }
        ),
        ToolActionSpec(
            action="GET",
            description="Get file metadata by ID",
            parameters={
                "fileId": "file ID"
            }
        ),
        ToolActionSpec(
            action="CREATE",
            description="Create folders ONLY. NEVER use this for Google Docs or Sheets - use docs:CREATE or sheets:CREATE instead.",
            parameters={
                "name": "folder name",
                "mimeType": "must be 'application/vnd.google-apps.folder' for folders",
                "folderId": "parent folder ID (optional)"
            }
        ),
        ToolActionSpec(
            action="UPDATE",
            description="Update file name or move to different folder",
            parameters={
                "fileId": "file ID",
                "name": "new name",
                "folderId": "new parent folder ID",
                "content": "new file content (optional)"
            }
        ),
        ToolActionSpec(
            action="DELETE",
            description="Delete file (trash or permanent)",
            parameters={
                "fileId": "file ID",
                "permanent": "true for permanent delete, false for trash"
            }
        ),
        ToolActionSpec(
            action="LIST_PERMISSIONS",
            description="List file permissions",
            parameters={
                "fileId": "file ID"
            }
        ),
        ToolActionSpec(
            action="SHARE",
            description="Share file with user/group/domain",
            parameters={
                "fileId": "file ID",
                "role": "reader/commenter/writer/owner",
                "type": "user/group/domain/anyone",
                "email": "email address (for user/group)",
                "domain": "domain name (for domain type)"
            }
        ),
        ToolActionSpec(
            action="UNSHARE",
            description="Remove permission from file",
            parameters={
                "fileId": "file ID",
                "permissionId": "permission ID to remove"
            }
        )
    ]
)

# Define Calendar tool capabilities
# Define Google Docs tool capabilities
DOCS_CAPABILITY = ToolCapability(
    tool_name="docs",
    actions=[
        ToolActionSpec(
            action="CREATE",
            description="Create a new Google Doc. Always use this (NOT drive:CREATE) to create Google Docs.",
            parameters={
                "title": "document title",
                "folderId": "parent folder ID (optional)",
            },
        ),
        ToolActionSpec(
            action="READ",
            description="Read document content",
            parameters={
                "documentId": "document ID",
            },
        ),
        ToolActionSpec(
            action="UPDATE",
            description="Update document (insert/delete text, paragraphs). Operations must be an array of objects, not a string.",
            parameters={
                "documentId": "document ID",
                "operations": "array of operation objects, e.g., [{type:\"INSERT_TEXT\",text:\"content\",index:1}] or [{type:\"DELETE_TEXT\",startIndex:5,endIndex:10}]. Each operation must be an object with 'type' field (INSERT_TEXT, DELETE_TEXT, INSERT_PARAGRAPH_BREAK) and corresponding parameters.",
            },
        ),
        ToolActionSpec(
            action="FORMAT",
            description="Format text or paragraphs (bold, italic, colors, styles, alignment)",
            parameters={
                "documentId": "document ID",
                "startIndex": "start character index",
                "endIndex": "end character index",
                "bold": "true/false",
                "italic": "true/false",
                "underline": "true/false",
                "fontSize": "font size in points",
                "foregroundColor": "text color (hex or named)",
                "backgroundColor": "background color (hex or named)",
                "namedStyle": "HEADING_1/HEADING_2/NORMAL_TEXT/etc",
                "alignment": "START/CENTER/END/JUSTIFY",
            },
        ),
        ToolActionSpec(
            action="DELETE",
            description="Delete document",
            parameters={
                "documentId": "document ID",
            },
        ),
    ],
)

CALENDAR_CAPABILITY = ToolCapability(
    tool_name="calendar",
    actions=[
        ToolActionSpec(
            action="CREATE",
            description="Create event (supports Meet link, attendees, reminders)",
            parameters={
                "summary": "event title",
                "start": "start date/time (ISO or {dateTime,timeZone})",
                "end": "end date/time or duration_minutes",
                "calendarId": "calendar identifier (default primary)",
                "attendees": "list of attendee emails or objects",
                "conference": "true to auto-create Google Meet link",
                "reminders": "override reminders [{method,minutes}]",
            },
        ),
        ToolActionSpec(
            action="LIST",
            description="List events within a time range (defaults to next 7 days)",
            parameters={
                "timeMin": "RFC3339 start time (default now)",
                "timeMax": "RFC3339 end time (default now+7d)",
                "calendarId": "calendar identifier (default primary)",
                "maxResults": "max events to fetch (default 10)",
                "query": "text search filter",
            },
        ),
        ToolActionSpec(
            action="GET",
            description="Fetch a specific event by ID",
            parameters={
                "eventId": "event identifier",
                "calendarId": "calendar identifier (default primary)",
            },
        ),
        ToolActionSpec(
            action="UPDATE",
            description="Update event fields (summary, times, attendees, reminders)",
            parameters={
                "eventId": "event identifier",
                "calendarId": "calendar identifier",
                "summary": "new title",
                "start": "new start time or date",
                "end": "new end time or duration_minutes",
                "attendees": "new attendee list",
            },
        ),
        ToolActionSpec(
            action="DELETE",
            description="Delete an event",
            parameters={
                "eventId": "event identifier",
                "calendarId": "calendar identifier (default primary)",
            },
        ),
        ToolActionSpec(
            action="RESPOND",
            description="Update attendee RSVP for an event",
            parameters={
                "eventId": "event identifier",
                "attendee": "attendee email to update",
                "responseStatus": "accepted/declined/tentative",
                "calendarId": "calendar identifier",
            },
        ),
    ]
)

# Define WebSearch tool capabilities
WEBSEARCH_CAPABILITY = ToolCapability(
    tool_name="websearch",
    actions=[
        ToolActionSpec(
            action="SEARCH",
            description="Search the web for comprehensive information. Use specific, detailed queries to get complete results with names, numbers, dates, and all relevant details.",
            parameters={
                "query": "detailed search query - be specific and include context (e.g., 'top 10 companies salary Financial Analyst Madrid 2024' not just 'companies')",
                "max_results": "max results (default 5, but web search returns comprehensive summaries)"
            }
        )
    ]
)

# Define LLM tool capabilities (built-in, no connection required)
LLM_CAPABILITY = ToolCapability(
    tool_name="llm",
    actions=[
        ToolActionSpec(
            action="CALL",
            description=(
                "Universal multi-purpose method to analyze text and multimodal data, generate content (emails, code, etc.) and extract JSON data. "
                "Automatically selects vision model when file_data is provided, standard model otherwise. "
                "For structured data extraction, explicitly request JSON format in prompt. "
                "For efficiency, combine extraction and formatting in ONE call when possible."
            ),
            parameters={
                "prompt": "detailed instruction string",
                "file_data": "Optional: array of file objects (e.g. from filesystem.read_media_file() or filesystem.read_text_file())",
            }
        )
    ]
)

SQL_CAPABILITY = ToolCapability(
    tool_name="sql",
    actions=[
        ToolActionSpec(
            action="SCHEMA",
            description="Introspect database schema (tables, columns, PK/FK) using the configured connection URL",
            parameters={
                "refresh": "optional true/false to force refresh (ignored for now, kept for future caching)",
            },
        ),
        ToolActionSpec(
            action="QUERY",
            description="Read data only: execute a SELECT or other safe read-only SQL query. Write operations (INSERT/UPDATE/DELETE/DDL) are rejected. Can optionally return CSV for easy ingestion in sheets.",
            parameters={
                "sql": "SQL query string",
                # read_only is forced to true internally; kept here only for backward compatibility if present
                "read_only": "ignored (always true). Tool only allows read-only queries.",
                "as_csv": "optional true/false. If true, returns CSV string (header + rows) instead of JSON object.",
            },
        ),
    ],
)

# Tool Registry
TOOL_REGISTRY: Dict[str, ToolCapability] = {
    "gmail": GMAIL_CAPABILITY,
    "sheets": SHEETS_CAPABILITY,
    "drive": DRIVE_CAPABILITY,
    "calendar": CALENDAR_CAPABILITY,
    "docs": DOCS_CAPABILITY,
    "websearch": WEBSEARCH_CAPABILITY,
    "sql": SQL_CAPABILITY,
    "llm": LLM_CAPABILITY,  # Built-in tool, always available
}


def get_tool_capability(tool_name: str) -> Optional[ToolCapability]:
    """Get tool capability definition"""
    return TOOL_REGISTRY.get(tool_name.lower())


def map_frontend_action_to_registry_action(tool_name: str, frontend_action: str) -> Optional[str]:
    """
    Map frontend action name (e.g., "Read emails") to tool registry action name (e.g., "READ")
    
    Args:
        tool_name: Tool name (e.g., "gmail", "sheets")
        frontend_action: Frontend action name (e.g., "Read emails", "Send emails")
    
    Returns:
        Tool registry action name (e.g., "READ", "SEND") or None if no mapping
    """
    tool_name = tool_name.lower()
    frontend_action_lower = frontend_action.lower()
    
    # Mapping rules for each tool
    mappings = {
        "gmail": {
            "read": "READ",
            "read emails": "READ",
            "send": "SEND",
            "send emails": "SEND",
        },
        "sheets": {
            "read": "READ",
            "read spreadsheets": "READ",
            "write": "WRITE",
            "edit": "WRITE",
            "write/edit spreadsheets": "WRITE",
            "create": "CREATE",
            "create spreadsheets": "CREATE",
            "format": "FORMAT",
            "chart": "CHART",
        },
        "docs": {
            "read": "READ",
            "read document": "READ",
            "read doc": "READ",
            "write": "UPDATE",
            "edit": "UPDATE",
            "update": "UPDATE",
            "create": "CREATE",
            "create document": "CREATE",
            "create doc": "CREATE",
            "format": "FORMAT",
            "delete": "DELETE",
        },
        "sql": {
            "read": "QUERY",
            "query": "QUERY",
            "schema": "SCHEMA",
            "write": "WRITE",
            "execute": "WRITE",
        },
        "drive": {
            "search": "SEARCH",
            "search files": "SEARCH",
            "find": "SEARCH",
            "find files": "SEARCH",
            "get": "GET",
            "get file": "GET",
            "read": "GET",
            "read file": "GET",
            "create": "CREATE",
            "create file": "CREATE",
            "create folder": "CREATE",
            "upload": "CREATE",
            "update": "UPDATE",
            "update file": "UPDATE",
            "modify": "UPDATE",
            "modify file": "UPDATE",
            "rename": "UPDATE",
            "move": "UPDATE",
            "delete": "DELETE",
            "delete file": "DELETE",
            "remove": "DELETE",
            "list permissions": "LIST_PERMISSIONS",
            "permissions": "LIST_PERMISSIONS",
            "share": "SHARE",
            "share file": "SHARE",
            "unshare": "UNSHARE",
            "remove permission": "UNSHARE",
        },
        "calendar": {
            "read": "LIST",
            "read events": "LIST",
            "create": "CREATE",
            "create events": "CREATE",
            "update": "UPDATE",
            "update events": "UPDATE",
            "delete": "DELETE",
            "delete events": "DELETE",
        },
        "websearch": {
            "search": "SEARCH",
        },
    }
    
    tool_mappings = mappings.get(tool_name, {})
    mapped = tool_mappings.get(frontend_action_lower)
    if mapped:
        return mapped

    # Fallback for dynamic tool names (APITool, etc.):
    # - accept already-registry-like names (e.g. LIST_PETS)
    # - normalize user forms (e.g. list-pets, list pets)
    registry_candidate = frontend_action.strip().upper().replace("-", "_").replace(" ", "_")
    tool_summaries = TOOL_ACTION_SUMMARIES.get(tool_name, {})
    if registry_candidate in tool_summaries:
        return registry_candidate

    # Last resort: case-insensitive match against known actions for the tool
    for action_name in tool_summaries.keys():
        if action_name.lower() == frontend_action_lower.replace("-", "_").replace(" ", "_"):
            return action_name
    return None












# INTELLIGENT CONTEXT FILTERING - Minimal summaries for cheap LLM prefilter
# =============================================================================

# Ultra-minimal tool+action summaries (~10 tokens each) for prefilter LLM
TOOL_ACTION_SUMMARIES = {
    "gmail": {
        "READ": "Search/read emails, get body, attachments",
        "SEND": "Send emails with attachments, CC/BCC",
    },
    "sheets": {
        "READ": "Read spreadsheet data from cells/ranges",
        "WRITE": "Write/append data to cells",
        "CREATE": "Create new spreadsheets",
        "FORMAT": "Format cells (bold, colors, etc)",
        "CHART": "Create charts from data",
    },
    "sql": {
        "SCHEMA": "Get SQL database structure (tables, columns, types)",
        "QUERY": "Query SQL database (SELECT) - use for any DB/database/SQL request",
        "WRITE": "Modify SQL database (INSERT/UPDATE/DELETE)",
    },
    "drive": {
        "SEARCH": "Find files/folders by name/type",
        "CREATE": "Create new folders (NOT docs/sheets)",
        "GET": "Get file metadata",
        "SHARE": "Share files with users",
    },
    "docs": {
        "CREATE": "Create new Google Docs (VISIBLE to user)",
        "READ": "Read document content",
        "UPDATE": "Edit document text",
        "FORMAT": "Format text (bold, colors, etc)",
    },
    "calendar": {
        "LIST": "List events in date range",
        "CREATE": "Create new events",
        "UPDATE": "Modify existing events",
        "DELETE": "Remove events",
    },
    "websearch": {
        "SEARCH": "Search the web for information",
    },
    "llm": {
        "CALL": "Universal method for text analysis, image analysis, content generation, and structured data extraction",
    },
    "files": {
        "READ": "Read uploaded task files ONLY.",
        "SAVE": "Save internal/temporary output files (HIDDEN from user, use docs/sheets to share)",
        "LIST": "List uploaded task files (NOT user desktop/system files)",
    },

}

# Compressed API docs per tool+action (~80% smaller than full docs)
COMPRESSED_API_DOCS = {
    "gmail:READ": "await gmail.read(max_results=10, query='is:unread', desc='...') -> List[{id, subject, from_email, to, date, body, snippet, attachments: [{attachment_id, filename, mime_type, size}]}] // Queries: 'from:boss', 'has:attachment'. Download: await gmail.download_attachments(email). ⚠️ Print brief confirm only.",
    "gmail:SEND": "await gmail.send(to='...', subject='...', body='...', cc='...', bcc='...', attachments=['path/file.pdf'], desc='...') -> dict",
    "sheets:READ": "await sheets.read(sheet_id, range='Sheet1!A1:C10', desc='...') -> List[List[Any]] // 2D array, row 1 headers",
    "sheets:WRITE": "await sheets.write(sheet_id, data, sheet='Sheet1', cell='A1', desc='...') // data: List[List], List[Dict], or CSV str",
    "sheets:CREATE": "await sheets.create('Title', data=data, desc='...') -> str // FAST: init with data in 1 call",
    "sql:SCHEMA": "await sql.schema(desc='...') -> str // Get DB schema. DO NOT translate table/col names",
    "sql:QUERY": "await sql.query('SELECT...', as_csv=False, desc='...') -> List[Dict] // as_csv=True for Sheets. Use ONLY exact schema names.",
    "sql:WRITE": "await sql.execute('UPDATE...', desc='...')",
    "drive:SEARCH": "await drive.search(name='Report', mime_type='spreadsheet', desc='...') -> str|None",
    "drive:UPLOAD": "await drive.upload('path.xlsx' OR bytes, name='Report', folder_id='...', desc='...') -> str // For plots: plt.savefig(buf, format='png'); buf.seek(0); await drive.upload(buf.getvalue(),...)",
    "drive:GET": "await drive.get(file_id) -> bytes",
    "docs:CREATE": "await docs.create('Title', content='markdown', desc='...') -> str",
    "docs:READ": "await docs.read(doc_id, desc='...') -> str",
    "docs:UPDATE": "await docs.update(doc_id, 'Appended text', desc='...')",
    "calendar:LIST": "await calendar.list(start='1970-01-01T00:00:00Z', end='...T..Z', desc='...') -> List[{id, summary, start: {dateTime}, end: {dateTime}}] // Access var['start']['dateTime']",
    "calendar:CREATE": "await calendar.create(summary='Meet', start='...T..Z', end='...T..Z', description='...', desc='...')",
    "calendar:UPDATE": "await calendar.update(event_id, summary='New', start='...', end='...')",
    "calendar:DELETE": "await calendar.delete(event_id)",
    "websearch:SEARCH": "await websearch.search('query', max_results=5, desc='...') -> str // Returns ready-to-use markdown with findings and links. Use directly — only call llm.call() after if a specific output format (table, JSON, etc.) is explicitly required.",
    "llm:CALL": "await llm.call('Summarize: ' + str(data), max_tokens=2000, desc='...') -> str // File analysis: await llm.call('Desc', file_data=[var]). JSON extract: await llm.call('Extract JSON: {...}')",
    "files:READ": "await files.read('data.csv', desc='...') // UPLOADED task files ONLY. CSV->List[Dict]. Image for LLM: files.read('img.png', for_llm=True).",
    "files:SAVE": "await files.save('out.csv', [{'A':1}], desc='...') // HIDDEN from user! Save directly to list[dict]->CSV/Excel, dict->JSON. Use Docs/print to share to user.",
    "files:LIST": "await files.list(desc='...') -> List[{filename, file_type, size_bytes, path}]",
}

# Minimal examples per action (only essential patterns)
COMPRESSED_EXAMPLES = {
    "gmail:READ": "import asyncio\nemails = await gmail.read(query='has:attachment')\nasync def process(e):\n    if e.get('attachments'): await gmail.download_attachments(e)\n    return e\nresults = await asyncio.gather(*[process(e) for e in emails])",
    "sheets:WRITE": "csv = await sql.query('SELECT *', as_csv=True)\nawait sheets.create('Rpt', data=csv)",
    "parallel": "import asyncio\nresults = await asyncio.gather(*[llm.call(x) for x in items], desc='what this parallel block does')",
}


def _get_connection_available_actions(conn: Any, available_tools: Dict[str, Set[str]]) -> Set[str]:
    """Resolve action set for a specific connection, respecting its allow restrictions."""
    tool_name = getattr(conn, 'tool_name', 'unknown').lower()
    fallback_actions = set(available_tools.get(tool_name, set()))

    allow = getattr(conn, 'allow', None)
    if allow is None:
        return fallback_actions

    # `allow` may be list/set/tuple or a single string.
    raw_actions: List[str]
    if isinstance(allow, (set, tuple, list)):
        raw_actions = [str(a) for a in allow]
    else:
        raw_actions = [str(allow)]

    mapped_actions: Set[str] = set()
    for frontend_action in raw_actions:
        mapped = map_frontend_action_to_registry_action(tool_name, frontend_action)
        if mapped:
            mapped_actions.add(mapped)

    # For dynamic tools (e.g. APITool), keep known allowed actions as fallback
    # if mapping table cannot resolve them.
    if not mapped_actions:
        mapped_actions = {str(a).strip().upper().replace("-", "_").replace(" ", "_") for a in raw_actions if str(a).strip()}

    if fallback_actions:
        return mapped_actions.intersection(fallback_actions)
    return mapped_actions


def build_prefilter_prompt(task: str, available_tools: Dict[str, Set[str]], connections: List[Any] = None, custom_descriptions: Dict[str, str] = None) -> str:
    """
    Build ultra-minimal prompt for prefilter LLM to select needed tools+actions.
    Now connection-aware: includes connection names/descriptions so the LLM can
    choose WHICH specific connection to use.
    
    Args:
        task: User's task description
        available_tools: Dict of tool_name -> Set of allowed actions
        connections: List of Connection objects (with connection_name, tool_name, metadata)
        custom_descriptions: Descriptions for custom tools injected at runtime
    
    Returns:
        Minimal prompt string (~200-400 tokens total)
    """
    # Keep task compact for prefilter; detailed reasoning happens in code-generation stage.
    task_text = (task or "").strip()
    if len(task_text) > 1400:
        task_text = task_text[:1400].rstrip() + " ...[truncated]"

    lines = [f'Task: "{task_text}"', ""]
    
    # If we have connections, list them with their names and descriptions
    if connections:
        lines.append("Connections:")
        for conn in connections:
            conn_name = getattr(conn, 'connection_name', 'Unknown')
            tool_name = getattr(conn, 'tool_name', 'unknown').lower()
            conn_desc = ''
            if hasattr(conn, 'metadata') and isinstance(conn.metadata, dict):
                conn_desc = conn.metadata.get('description', '')
            
            # Get allowed actions for this specific connection.
            actions = _get_connection_available_actions(conn, available_tools)
            if actions:
                method_names = sorted([f"{a.lower()}()" for a in actions])
                methods_str = ", ".join(method_names)
                desc_compact = (conn_desc or "").strip()
                if len(desc_compact) > 80:
                    desc_compact = desc_compact[:80].rstrip() + "..."
                desc_part = f" | {desc_compact}" if desc_compact else ""
                lines.append(f"- {conn_name} (tool={tool_name}) call: {methods_str}{desc_part}")
    else:
        # Fallback: no connections, just list abstract tools
        lines.append("Tools:")
        for tool_name, actions in sorted(available_tools.items()):
            for action in sorted(actions):
                summary = TOOL_ACTION_SUMMARIES.get(tool_name, {}).get(action, "")
                if summary:
                    lines.append(f"- {tool_name}:{action} → {summary}")
    
    # Always list built-in tools (llm, files, approval) without connection names
    lines.append("")
    lines.append("Built-ins:")
    for builtin in ['llm', 'files']:
        actions = available_tools.get(builtin, set())
        if actions:
            for action in sorted(actions):
                summary = TOOL_ACTION_SUMMARIES.get(builtin, {}).get(action, "")
                if summary:
                    lines.append(f"- {builtin}:{action} → {summary}")
                    
    # Include custom script-injected tools
    if custom_descriptions:
        has_custom = False
        for tool_name, desc in custom_descriptions.items():
            t_name = tool_name.lower()
            # Skip if it's a known built-in or already handled via connections
            if t_name in ['llm', 'files', 'websearch'] or t_name in TOOL_ACTION_SUMMARIES:
                continue
            if any(getattr(c, 'tool_name', '').lower() == t_name for c in (connections or [])):
                continue
            
            if not has_custom:
                lines.append("")
                lines.append("Custom tools:")
                has_custom = True
            
            actions_str = ",".join(sorted(available_tools.get(t_name, {"EXECUTE"})))
            desc_compact = (desc or "").strip()
            if len(desc_compact) > 80:
                desc_compact = desc_compact[:80].rstrip() + "..."
            desc_part = f" | {desc_compact}" if desc_compact else ""
            lines.append(f"- {tool_name} (tool={t_name}) actions: {actions_str}{desc_part}")
    
    lines.append("")
    lines.append("Rules:")
    lines.append("- If internal knowledge is enough and no tools are needed, return: ANSWER: <text>")
    lines.append("- If tools are needed, return only comma-separated <Tool>:<METHOD or ACTION>")
    lines.append("- For connection-based tools: use connection_name:ACTION (e.g., 'Gmail Account:READ' or tool_name:ACTION)")
    lines.append("- Never return ANSWER if tools are used")
    lines.append("- Prefer minimal tool set")
    lines.append("Output format examples:")
    lines.append("- ANSWER: Python is a high-level language (no tools needed)")
    lines.append("- petstore:list_pets,llm:call (APITool method + built-in tool)")
    lines.append("- Work Gmail:READ,llm:CALL (named connection + built-in tool)")
    
    return "\n".join(lines)


def _build_connection_lookup(connections: List[Any] = None) -> Dict[str, tuple]:
    """Build case-insensitive connection-name lookup for prefilter parsing."""
    lookup = {}
    if not connections:
        return lookup

    for conn in connections:
        cname = getattr(conn, 'connection_name', '').strip()
        tname = getattr(conn, 'tool_name', '').lower().strip()
        if cname and tname:
            lookup[cname.lower()] = (cname, tname)
    return lookup


def _parse_prefilter_part(part: str) -> Optional[tuple]:
    """Parse one '<name>:<action>' fragment from prefilter output."""
    if ':' not in part:
        return None

    # Split on last colon to support names that include colons.
    colon_idx = part.rfind(':')
    name_part = part[:colon_idx].strip()
    action_part = part[colon_idx + 1:].strip().upper()
    if not name_part or not action_part:
        return None
    return name_part, action_part


def _append_connection_mapping(connection_map: Dict[str, List[str]], tool_name: str, connection_name: str) -> None:
    if tool_name not in connection_map:
        connection_map[tool_name] = []
    if connection_name not in connection_map[tool_name]:
        connection_map[tool_name].append(connection_name)


def parse_prefilter_response(response: str, connections: List[Any] = None) -> tuple:
    """
    Parse the prefilter response into selected actions and connection mapping.
    
    Args:
        response: Raw LLM response (e.g., "Work Gmail:READ,Sales DB:QUERY,llm:CALL")
        connections: List of Connection objects for name resolution
    
    Returns:
        Tuple of (selected_actions: List[str], connection_map: Dict[str, str])
        - selected_actions: List of "tool:ACTION" for API docs lookup (e.g., ["gmail:READ", "sql:QUERY"])
        - connection_map: Dict of tool_name -> connection_name (e.g., {"gmail": "Work Gmail", "sql": "Sales DB"})
          When multiple connections of the same tool are selected, uses tool_name_idx as key.
    """
    conn_lookup = _build_connection_lookup(connections)
    
    # Built-in tools that don't need connections
    builtins = {'llm', 'files', 'websearch'}
    
    selected_actions = []
    connection_map = {}  # tool_name -> [connection_name, ...]
    
    parts = [p.strip() for p in response.strip().split(',') if p.strip()]
    
    for part in parts:
        parsed = _parse_prefilter_part(part)
        if parsed is None:
            continue
        name_part, action_part = parsed
        
        # Check if it's a built-in tool (tool:ACTION format)
        if name_part.lower() in builtins:
            selected_actions.append(f"{name_part.lower()}:{action_part}")
            continue
        
        # Check if it's a connection name (connection_name:ACTION format)
        lookup_key = name_part.lower()
        if lookup_key in conn_lookup:
            original_name, tool_name = conn_lookup[lookup_key]
            selected_actions.append(f"{tool_name}:{action_part}")
            _append_connection_mapping(connection_map, tool_name, original_name)
        else:
            # Fallback: try as tool_name directly (backward compat)
            tool_name = name_part.lower()
            selected_actions.append(f"{tool_name}:{action_part}")
    
    return selected_actions, connection_map


def build_filtered_api_docs(selected_actions: List[str], custom_descriptions: Dict[str, str] = None) -> str:
    """
    Build API documentation for only the selected tool:action pairs.

    Args:
        selected_actions: List of "tool:action" strings (e.g., ["gmail:READ", "llm:CALL"])
        custom_descriptions: Optional descriptions for custom tools injected at runtime

    Returns:
        Compressed API documentation string
    """
    docs = ["# Tools (async, use await):"]
    examples = []

    # Normalize and deduplicate
    selected = set(a.strip().lower() for a in selected_actions)

    # Always include basic built-ins
    selected.add("files:read")
    # files:save is NOT auto-included to discourage hidden outputs

    # Build docs for selected actions
    for action_key in sorted(selected):
        # Try exact match first
        matched = False
        for key, doc in COMPRESSED_API_DOCS.items():
            if key.lower() == action_key:
                docs.append(doc)
                matched = True
                break

        # If no standard doc found, check if it's a custom tool
        if not matched and custom_descriptions:
            tool_name = action_key.split(":")[0]
            if tool_name in custom_descriptions and tool_name not in TOOL_ACTION_SUMMARIES:
                desc = custom_descriptions[tool_name]
                docs.append(desc)
    
    # Add relevant examples
    for action_key in selected:
        for key, example in COMPRESSED_EXAMPLES.items():
            if key.lower() == action_key:
                examples.append(example)
                break
    
    # Always add parallelization hint if multiple tools selected
    if len(selected) > 2 and "parallel" not in [e.lower() for e in examples]:
        examples.append(COMPRESSED_EXAMPLES.get("parallel", ""))
    
    result = "\n\n".join(docs)
    if examples:
        result += "\n\n# Examples:\n" + "\n\n".join(e for e in examples if e)
    
    return result


def filter_selected_actions(
    selected_actions: List[str],
    available_actions: Dict[str, Set[str]],
) -> Tuple[List[str], List[str]]:
    """Keep only tool:action pairs that are actually allowed for this run.

    Returns:
        (allowed_selected_actions, blocked_selected_actions)
    """
    allowed: List[str] = []
    blocked: List[str] = []

    for item in selected_actions:
        parsed = _parse_prefilter_part(item)
        if parsed is None:
            blocked.append(item)
            continue

        tool_name, action_name = parsed
        tool_key = tool_name.lower().strip()
        action_key = action_name.upper().strip()
        allowed_for_tool = available_actions.get(tool_key, set())

        if action_key in allowed_for_tool:
            allowed.append(f"{tool_key}:{action_key}")
        else:
            blocked.append(f"{tool_key}:{action_key}")

    # Preserve order while removing duplicates.
    allowed = list(dict.fromkeys(allowed))
    blocked = list(dict.fromkeys(blocked))
    return allowed, blocked


def get_available_actions_for_connections(connections: List[Any], custom_tools: Dict[str, Any] = None) -> Dict[str, Set[str]]:
    """
    Extract available tool:action pairs from connections.
    
    Args:
        connections: List of Connection objects
        custom_tools: Optional Dict of custom tool functions (for capturing unmapped scripts)
    
    Returns:
        Dict of tool_name -> Set of allowed action names
    """
    result = {}
    
    for conn in connections:
        tool_name = conn.tool_name.lower() if hasattr(conn, 'tool_name') else None
        if not tool_name:
            continue
        
        if tool_name not in result:
            result[tool_name] = set()
        
        # If no restrictions, add all actions for this tool
        if not conn.allow:
            if tool_name in TOOL_ACTION_SUMMARIES:
                result[tool_name].update(TOOL_ACTION_SUMMARIES[tool_name].keys())
        else:
            # Map frontend actions to registry actions
            for frontend_action in conn.allow:
                mapped = map_frontend_action_to_registry_action(tool_name, frontend_action)
                if mapped:
                    result[tool_name].add(mapped)
    
    # Always include built-in tools (excluding websearch which is treated as an explicit tool)
    for builtin in ['llm', 'files']:
        if builtin in TOOL_ACTION_SUMMARIES:
            result[builtin] = set(TOOL_ACTION_SUMMARIES[builtin].keys())
            
    # Include custom tools if provided
    if custom_tools:
        for tool_name in custom_tools:
            t_name = tool_name.lower()
            if t_name not in result and t_name not in TOOL_ACTION_SUMMARIES:
                result[t_name] = {"EXECUTE"}
    
    return result


def build_connection_context_for_prompt(connection_map: Dict[str, List[str]], connections: List[Any]) -> str:
    """
    Build a "Connected Services" section for the code generation prompt.
    Lists the specific connections the LLM should use, so it knows which
    connection_name to pass to tool methods.
    
    Args:
        connection_map: Dict of tool_name -> [connection_name, ...] from prefilter
        connections: All available Connection objects (for metadata lookup)
    
    Returns:
        Formatted string for injection into the code generation prompt
    """
    if not connection_map:
        return ""
    
    # Build lookup: connection_name -> Connection object
    conn_by_name = {}
    for conn in connections:
        cname = getattr(conn, 'connection_name', '')
        if cname:
            conn_by_name[cname] = conn
    
    lines = ["\n**CONNECTED SERVICES** (auto-detected, no connection_name needed):"]
    
    for tool_name, conn_names in sorted(connection_map.items()):
        for conn_name in conn_names:
            conn = conn_by_name.get(conn_name)
            desc = ''
            if conn and hasattr(conn, 'metadata') and isinstance(conn.metadata, dict):
                desc = conn.metadata.get('description', '')
            desc_part = f" - {desc}" if desc else ""
            lines.append(f"- {tool_name}: \"{conn_name}\"{desc_part}")
    
    # Add usage hint
    has_multi = any(len(names) > 1 for names in connection_map.values())
    if has_multi:
        lines.append("")
        lines.append("IMPORTANT: Multiple connections of the same type are available.")
        lines.append('The system will auto-detect the correct connection.')
        lines.append('Example: await sql.query("SELECT ...")')
    else:
        # Single connections per tool - still add hint but less urgent
        lines.append("")
        lines.append('Tip: The system auto-detects the correct connection.')
    
    return "\n".join(lines)
