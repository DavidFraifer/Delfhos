"""
Tool Registry System
Provides tool capability definitions and Python API documentation for agent code generation
"""

import re
from typing import Dict, List, Optional, Any, Set, Tuple


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
            "list": "LIST",
            "list emails": "LIST",
            "read": "LIST",
            "read emails": "LIST",
            "send": "SEND",
            "send emails": "SEND",
            "attachments": "GET_ATTACHMENTS",
            "get_attachments": "GET_ATTACHMENTS",
            "download attachments": "GET_ATTACHMENTS",
        },
        "sheets": {
            "get": "GET",
            "read": "GET",
            "read spreadsheets": "GET",
            "update": "UPDATE",
            "write": "UPDATE",
            "edit": "UPDATE",
            "write/edit spreadsheets": "UPDATE",
            "create": "CREATE",
            "create spreadsheets": "CREATE",
            "format": "FORMAT",
            "chart": "CHART",
        },
        "docs": {
            "get": "GET",
            "read": "GET",
            "read document": "GET",
            "read doc": "GET",
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
            "list": "LIST",
            "list files": "LIST",
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
    tool_summaries = COMPRESSED_TOOL_DOCS.get(tool_name, {})
    if registry_candidate in tool_summaries:
        return registry_candidate

    # Last resort: case-insensitive match against known actions for the tool
    for action_name in tool_summaries.keys():
        if action_name.lower() == frontend_action_lower.replace("-", "_").replace(" ", "_"):
            return action_name
    return None












# INTELLIGENT CONTEXT FILTERING - Minimal summaries for cheap LLM prefilter
# =============================================================================

# ── Tool documentation — SINGLE SOURCE OF TRUTH ──────────────────────────────
# TOOL_DOCS holds the FULL per-action doc (used verbatim in the codegen prompt).
# The reduced prefilter summaries are AUTO-DERIVED from these into
# COMPRESSED_TOOL_DOCS (defined just below), so the two can never drift apart.
TOOL_DOCS = {
    "gmail:LIST": "await gmail.list(max_results=10, query='is:unread', desc='...') -> List[{id, subject, from_email, to, date, body, snippet, attachments: [{attachment_id, filename, mime_type, size}]}] // Queries: 'from:boss', 'has:attachment'. Attachments (PDF/image invoices, receipts, scans): paths = await gmail.get_attachments(email) -> List[str] local file paths; pass them STRAIGHT to llm.call(file_data=paths) to read with vision (works for PDF too) — do NOT use files.read for these. Print brief confirm only. ❌ `gmail.read` does NOT exist — use `gmail.list`. ❌ `gmail.download_attachments` does NOT exist — use `gmail.get_attachments`.",
    "gmail:SEND": "await gmail.send(to='...', subject='...', body='...', cc='...', bcc='...', attachments=['path/file.pdf'], desc='...') -> dict",
    "gmail:GET_ATTACHMENTS": "paths = await gmail.get_attachments(email, desc='...') -> List[str] // `email` is a dict from gmail.list() with an 'attachments' field. Returns local file paths; pass straight to llm.call(file_data=paths).",
    "sheets:GET": "await sheets.get(spreadsheet_id, range='Sheet1!A1:C10', desc='...') -> List[List[Any]] // ALREADY a Python 2D array, row 1 headers. NEVER json.loads it. ❌ `sheets.read` does NOT exist — use `sheets.get`.",
    "sheets:UPDATE": "await sheets.update(spreadsheet_id, data, sheet='Sheet1', cell='A1', desc='...') // data: List[List], List[Dict], or CSV str. ❌ `sheets.write` does NOT exist — use `sheets.update`.",
    "sheets:CREATE": "await sheets.create('Title', data=data, desc='...') -> str // FAST: init with data in 1 call",
    "sql:SCHEMA": "await sql.schema(desc='...') -> str // Get DB schema. DO NOT translate table/col names",
    "sql:QUERY": "await sql.query('SELECT...', as_csv=False, desc='...') -> List[Dict] // as_csv=True for Sheets. Use ONLY exact schema names.",
    "sql:WRITE": "await sql.execute('UPDATE...', desc='...')",
    "drive:SEARCH": "await drive.search(name='Report', mime_type='spreadsheet', desc='...') -> str|None // `name=` is a plain SUBSTRING filter — NOT Google Drive query DSL. ❌ NO `query=`, NO `q=`, NO `\"name = 'X' and 'Y' in parents\"`. Returns the file_id of the FIRST match as a PLAIN STRING or None. NEVER json.loads it. Use for ONE specific file. To READ the found file you MUST use its file_id: spreadsheet→`await sheets.get(fid, range='Sheet1!A1:Z1000')`; PDF/image→`data = await drive.get(fid); await llm.call('...', file_data=[data])`; text/CSV→`(await drive.get(fid)).decode('utf-8')`. ❌ NEVER `files.read(name)` for a Drive file — files.read is ONLY for task-uploaded files.",
    "drive:LIST": "await drive.list(name='', mime_type='', desc='...') -> list[dict] // `name=` is a plain SUBSTRING filter — NOT Drive query DSL. ❌ NO `query=`, NO `q=`, NO operators inside `name`. Returns a Python LIST of file records, each {'id','name','mimeType',...} — METADATA ONLY, no content. To READ a file's content use its id: `data = await drive.get(f['id'])` → bytes, then `llm.call('...', file_data=[data])` for PDF/image or `data.decode('utf-8')` for text. ❌ NEVER print() the bytes from drive.get — analyze them with llm.call. ❌ `drive.list_files` does NOT exist — use `drive.list`.",
    "drive:UPLOAD": "await drive.upload(content_or_path, name='Report.csv', folder_id='...', desc='...') -> str // FIRST arg = content (str path OR raw bytes OR CSV/text string). `name=` is the SHORT filename and MUST be keyword-only. ❌ DO NOT swap args: `drive.upload(filename, content)` is WRONG (args reversed). For plots: plt.savefig(buf, format='png'); buf.seek(0); await drive.upload(buf.getvalue(), name='chart.png'). For CSV text: await drive.upload(csv_str, name='data.csv').",
    "drive:GET": "content = await drive.get(file_id, desc='...') -> bytes // Downloads the file's RAW BYTES (Google-native docs are auto-exported: sheet→CSV, doc→text). To READ a PDF/image from Drive with vision, pass the bytes STRAIGHT to llm.call: data = await drive.get(file_id); info = await llm.call('extract X', file_data=[data]). For text/CSV bytes: data.decode('utf-8'). ❌ NEVER use files.read(file_id) — files.read is ONLY for task-uploaded files by name, NOT Drive IDs.",
    "docs:CREATE": "await docs.create('Title', content='markdown', desc='...') -> str",
    "docs:GET": "await docs.get(doc_id, desc='...') -> str // ❌ `docs.read` does NOT exist — use `docs.get`.",
    "docs:UPDATE": "await docs.update(doc_id, 'Appended text', desc='...')",
    "calendar:LIST": "await calendar.list(start='1970-01-01T00:00:00Z', end='...T..Z', desc='...') -> List[{id, summary, start: {dateTime}, end: {dateTime}}] // Access var['start']['dateTime']",
    "calendar:CREATE": "await calendar.create(summary='Meet', start='...T..Z', end='...T..Z', description='...', desc='...')",
    "calendar:UPDATE": "await calendar.update(event_id, summary='New', start='...', end='...')",
    "calendar:DELETE": "await calendar.delete(event_id)",
    "websearch:SEARCH": "await websearch.search('query', max_results=5, desc='...') -> str // Returns ready-to-use markdown with findings and links. Use directly — only call llm.call() after if a specific output format (table, JSON, etc.) is explicitly required.",
    "llm:CALL": "await llm.call('Summarize: ' + str(data), max_tokens=2000, desc='...') -> str // File analysis: await llm.call('Desc', file_data=[var]). JSON extract: await llm.call('Extract JSON: {...}')",
    "files:READ": "await files.read('data.csv', desc='...') // UPLOADED task files ONLY (files the user attached to THIS task). CSV->List[Dict]. Image for LLM: files.read('img.png', for_llm=True). ❌ NOT for Google Drive files — a Drive file_id is not a task file. To read from Drive: drive.get(file_id) (then llm.call(file_data=[bytes]) for PDF/image).",
    "files:SAVE": "path = await files.save('out.csv', content, desc='...') -> str // ⚠️ open() is BLOCKED in the sandbox — use files.save to write CSV/JSON/text. Accepts list[dict]->CSV/Excel, dict->JSON, str/bytes raw. Returns the saved path; pass that path to gmail.send(attachments=[path]) or drive.upload(path). Files saved here are HIDDEN from the user (internal scratch).",
    "files:LIST": "await files.list(desc='...') -> List[{filename, file_type, size_bytes, path}]",
}

# Minimal examples per action (only essential patterns)
COMPRESSED_EXAMPLES = {
    "gmail:LIST": "import asyncio\nemails = await gmail.list(query='subject:Invoice')\nasync def process(e):\n    if e.get('attachments'):\n        paths = await gmail.get_attachments(e)  # -> List[str] local paths\n        return await llm.call('Extract JSON {...} from this invoice', file_data=paths)  # paths -> vision model, no files.read\n    return await llm.call('Extract JSON {...} from: ' + e['body'])  # no attachment -> use body\nresults = await asyncio.gather(*[process(e) for e in emails])",
    "sheets:UPDATE": "csv = await sql.query('SELECT *', as_csv=True)\nawait sheets.create('Rpt', data=csv)",
    "drive:SEARCH": "sid = await drive.search(name='accounting', mime_type='spreadsheet')\nif not sid: return 'not found'\nrows = await sheets.get(sid, range='Sheet1!A1:Z1000')  # rows already a List[List]",
    "drive:LIST": "files = await drive.list(mime_type='spreadsheet')\nfor f in files:\n    print(f['name'], f['id'])  # already parsed list[dict] — no json.loads",
    "parallel": "import asyncio\nresults = await asyncio.gather(*[llm.call(x) for x in items], desc='what this parallel block does')",
}


def _derive_summary(full_doc: str) -> str:
    """Reduce a full TOOL_DOCS entry to a short prefilter label (signature only).

    Drops the verbose notes/traps/examples after ``//``, strips default values and
    the return-type internals, leaving e.g.
    ``gmail.list(max_results, query, desc) -> List``.
    """
    head = full_doc.split("//", 1)[0].strip()
    head = re.sub(r"^[A-Za-z_]\w*\s*=\s*", "", head)   # drop leading 'var = ' assignment
    if head.startswith("await "):
        head = head[6:]
    if " -> " in head:
        call, ret = head.split(" -> ", 1)
        ret = re.split(r"[\[{(]", ret.strip(), 1)[0].strip() or ret.strip()
        head = f"{call.strip()} -> {ret}"
    head = re.sub(r"=[^,)]+", "", head)      # drop default values: query='x' -> query
    return head.strip()


# ── Introspected signatures: the code is the source of truth for signatures ──
# The hand-written signature inside each native TOOL_DOCS entry is replaced at
# import with the REAL one from inspect.signature, so codegen (and the derived
# prefilter summaries) can never show a stale param name (e.g. sheet_id vs
# spreadsheet_id). Notes/traps/examples after the signature are kept as written.
_NATIVE_LIB_CLASSES: Optional[Dict[str, Any]] = None


def _native_lib_classes() -> Dict[str, Any]:
    global _NATIVE_LIB_CLASSES
    if _NATIVE_LIB_CLASSES is None:
        from .tool_libraries import (
            SQLLibrary, SheetsLibrary, GmailLibrary, DriveLibrary, DocsLibrary,
            CalendarLibrary, LLMLibrary, FilesLibrary, WebSearchLibrary,
        )
        _NATIVE_LIB_CLASSES = {
            "sql": SQLLibrary, "sheets": SheetsLibrary, "gmail": GmailLibrary,
            "drive": DriveLibrary, "docs": DocsLibrary, "calendar": CalendarLibrary,
            "llm": LLMLibrary, "files": FilesLibrary, "websearch": WebSearchLibrary,
        }
    return _NATIVE_LIB_CLASSES


def _introspected_call(tool: str, method: str) -> Optional[str]:
    """Return ``tool.method(realparams)`` from live introspection, or None."""
    cls = _native_lib_classes().get(tool)
    if cls is None:
        return None
    try:
        from .call_validator import render_signature_card
        line = render_signature_card({tool: cls.__new__(cls)}, {tool: [method]}).strip()
        return line or None
    except Exception:
        return None


def _apply_introspected_signatures() -> None:
    """Rewrite the signature portion of every native TOOL_DOCS entry with the real
    introspected one. APITool/unparseable entries are left untouched."""
    try:
        native = _native_lib_classes()
    except Exception:
        return  # tool_libraries unavailable → keep hand-written docs
    for key, doc in list(TOOL_DOCS.items()):
        tool = key.split(":", 1)[0]
        if tool not in native:
            continue
        m = re.search(rf"\b{re.escape(tool)}\.(\w+)\s*\(", doc)
        if not m:
            continue
        real = _introspected_call(tool, m.group(1))
        if not real:
            continue
        prefix_m = re.match(r"\s*(\w+\s*=\s*)await\b", doc)   # keep 'content = await ...'
        prefix = prefix_m.group(1) if prefix_m else ""
        idxs = [i for i in (doc.find(" -> "), doc.find(" //")) if i != -1]
        tail = doc[min(idxs):] if idxs else ""              # keep '-> ret // notes'
        TOOL_DOCS[key] = f"{prefix}await {real}{tail}"


# Reduced prefilter summaries — AUTO-DERIVED from TOOL_DOCS (never hand-written).
COMPRESSED_TOOL_DOCS: Dict[str, Dict[str, str]] = {}


def rebuild_compressed_tool_docs() -> None:
    """(Re)derive the reduced prefilter summaries from TOOL_DOCS. Call after any
    runtime registration into TOOL_DOCS (e.g. APITool endpoints)."""
    COMPRESSED_TOOL_DOCS.clear()
    for key, doc in TOOL_DOCS.items():
        if ":" not in key:
            continue
        tool, action = key.split(":", 1)
        COMPRESSED_TOOL_DOCS.setdefault(tool, {})[action] = _derive_summary(doc)


_apply_introspected_signatures()   # fix signatures from the code (once, at import)
rebuild_compressed_tool_docs()


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
                summary = COMPRESSED_TOOL_DOCS.get(tool_name, {}).get(action, "")
                if summary:
                    lines.append(f"- {tool_name}:{action} → {summary}")
    
    # Always list built-in tools (llm, files, approval) without connection names
    lines.append("")
    lines.append("Built-ins:")
    for builtin in ['llm', 'files']:
        actions = available_tools.get(builtin, set())
        if actions:
            for action in sorted(actions):
                summary = COMPRESSED_TOOL_DOCS.get(builtin, {}).get(action, "")
                if summary:
                    lines.append(f"- {builtin}:{action} → {summary}")
                    
    # Include custom script-injected tools
    if custom_descriptions:
        has_custom = False
        for tool_name, desc in custom_descriptions.items():
            t_name = tool_name.lower()
            # Skip if it's a known built-in or already handled via connections
            if t_name in ['llm', 'files', 'websearch'] or t_name in COMPRESSED_TOOL_DOCS:
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
    lines.append("- For connection-based tools: use connection_name:ACTION (e.g., 'Gmail Account:LIST' or tool_name:ACTION)")
    lines.append("- Never return ANSWER if tools are used")
    lines.append("- Prefer minimal tool set")
    lines.append("Output format examples:")
    lines.append("- ANSWER: Python is a high-level language (no tools needed)")
    lines.append("- petstore:list_pets,llm:call (APITool method + built-in tool)")
    lines.append("- Work Gmail:LIST,llm:CALL (named connection + built-in tool)")
    
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
    # Defensive: the LLM sometimes appends call-style arguments
    # (e.g. "QUOTE(SYMBOL='AAPL')"); keep just the action identifier.
    paren_idx = action_part.find('(')
    if paren_idx != -1:
        action_part = action_part[:paren_idx].strip()
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


SANDBOX_CONTRACT = (
    "# SANDBOX CONTRACT — read before generating code\n"
    "\n"
    "## Hard rules\n"
    "1. The list of available tools and methods below is COMPLETE. There are NO other methods on these tools. Do NOT invent method names, do NOT guess from Google/AWS/REST APIs — every method you call must appear verbatim below.\n"
    "2. Method signatures are LITERAL. Use the parameter names shown exactly. Keyword-only parameters are marked; pass them by name.\n"
    "3. Tools return ALREADY-PARSED Python objects. NEVER call `json.loads()` on a tool result. Iterate lists, index dicts, call methods directly.\n"
    "4. Filesystem & subprocess access is BLOCKED. `open()`, `os`, `sys`, `subprocess`, `builtins`, `__import__('builtins')` do not work. To write a file use `await files.save(filename, content)` — it returns a path you can attach to `gmail.send` or `drive.upload`.\n"
    "5. Allowed stdlib imports: `asyncio`, `csv`, `datetime`, `io`, `json`, `math`, `pathlib`, `re`, `statistics`, `time`. Nothing else.\n"
    "6. If a parameter is not in the signature shown below, it does NOT exist. The call will fail. Re-read the signature.\n"
    "\n"
    "## Common pretraining traps — DO NOT do these:\n"
    "- ❌ `gmail.read(...)`            → ✅ `gmail.list(query=...)`\n"
    "- ❌ `gmail.download_attachments` → ✅ `gmail.get_attachments(email)`\n"
    "- ❌ `sheets.read(...)`           → ✅ `sheets.get(spreadsheet_id, range=...)`\n"
    "- ❌ `sheets.write(...)`          → ✅ `sheets.update(spreadsheet_id, data, ...)`\n"
    "- ❌ `docs.read(...)`             → ✅ `docs.get(doc_id)`\n"
    "- ❌ `drive.list_files(...)`      → ✅ `drive.list(name=..., mime_type=...)`\n"
    "- ❌ `drive.search(query='name = \"X\" and ... in parents')` → ✅ `drive.search(name='X', mime_type='spreadsheet')`  (`name` is a substring, not Drive query DSL)\n"
    "- ❌ `drive.upload(filename, content)` (reversed!) → ✅ `drive.upload(content_or_bytes, name='X.csv')`\n"
    "- ❌ `open('out.csv', 'w').write(csv)` → ✅ `path = await files.save('out.csv', csv)`\n"
    "- ❌ `json.loads(tool_result)` when the tool returned a list/dict → just use it directly\n"
)


def build_filtered_api_docs(selected_actions: List[str], custom_descriptions: Dict[str, str] = None) -> str:
    """
    Build API documentation for only the selected tool:action pairs.

    The output is framed as a closed contract: explicit sandbox rules,
    a list of the only methods available, common pretraining traps with
    correct replacements, then examples. The goal is to make the prompt
    self-contained enough that the codegen LLM does not reach for its
    pretraining of real APIs (Google Drive, Gmail, S3, ...).

    Args:
        selected_actions: List of "tool:action" strings (e.g., ["gmail:LIST", "llm:CALL"])
        custom_descriptions: Optional descriptions for custom tools injected at runtime

    Returns:
        Prompt section ready to paste into the codegen prompt.
    """
    selected = set(a.strip().lower() for a in selected_actions)
    # Always include basic built-ins
    selected.add("files:read")
    # files:save is NOT auto-included to discourage hidden outputs.

    # Group methods by tool so the contract is "tool X has these N methods, period".
    by_tool: Dict[str, List[str]] = {}
    for action_key in sorted(selected):
        matched_doc = None
        for key, doc in TOOL_DOCS.items():
            if key.lower() == action_key:
                matched_doc = doc
                break
        if matched_doc:
            tool_name = action_key.split(":", 1)[0]
            by_tool.setdefault(tool_name, []).append(f"- {matched_doc}")
        elif custom_descriptions:
            tool_name = action_key.split(":", 1)[0]
            if tool_name in custom_descriptions and tool_name not in COMPRESSED_TOOL_DOCS:
                by_tool.setdefault(tool_name, []).append(f"- {custom_descriptions[tool_name]}")

    blocks: List[str] = [SANDBOX_CONTRACT]
    blocks.append("# Available tools (THIS LIST IS COMPLETE — no other methods exist):")
    for tool_name in sorted(by_tool.keys()):
        lines = by_tool[tool_name]
        blocks.append(f"## `{tool_name}` — {len(lines)} method(s)\n" + "\n".join(lines))

    examples: List[str] = []
    for action_key in selected:
        for key, example in COMPRESSED_EXAMPLES.items():
            if key.lower() == action_key:
                examples.append(example)
                break
    if len(selected) > 2 and "parallel" not in [e.lower() for e in examples]:
        parallel = COMPRESSED_EXAMPLES.get("parallel", "")
        if parallel:
            examples.append(parallel)
    if examples:
        blocks.append("# Examples (use as templates):\n\n" + "\n\n".join(e for e in examples if e))

    return "\n\n".join(blocks)


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
        raw_tool_name = getattr(conn, 'tool_name', None)
        tool_name = raw_tool_name.lower() if raw_tool_name else None
        if not tool_name:
            continue
        
        if tool_name not in result:
            result[tool_name] = set()
        
        # If no restrictions, add all actions for this tool
        if not conn.allow:
            if tool_name in COMPRESSED_TOOL_DOCS:
                result[tool_name].update(COMPRESSED_TOOL_DOCS[tool_name].keys())
        else:
            # Map frontend actions to registry actions
            for frontend_action in conn.allow:
                mapped = map_frontend_action_to_registry_action(tool_name, frontend_action)
                if mapped:
                    result[tool_name].add(mapped)
    
    # Always include built-in tools (excluding websearch which is treated as an explicit tool)
    for builtin in ['llm', 'files']:
        if builtin in COMPRESSED_TOOL_DOCS:
            result[builtin] = set(COMPRESSED_TOOL_DOCS[builtin].keys())
            
    # Include custom tools if provided
    if custom_tools:
        for tool_name in custom_tools:
            t_name = tool_name.lower()
            if t_name not in result and t_name not in COMPRESSED_TOOL_DOCS:
                result[t_name] = {"EXECUTE"}
    
    return result


_WORD_RE = re.compile(r"\w+")


def _extract_keywords(query: str) -> List[str]:
    """Split a query into lowercase keywords (length > 1)."""
    return [w.lower() for w in _WORD_RE.findall(query or "") if len(w) > 1]


def _score_tool_action(
    tool_name: str,
    action: str,
    summary: str,
    keywords: List[str],
) -> int:
    """
    Score a tool:action against keywords.
    Exact match on name/action: 10
    Prefix on name/action: 5
    Word-boundary in name/action: 4
    Word-boundary in summary: 3
    Substring in name/action: 2
    Substring in summary: 1
    """
    tn = tool_name.lower()
    an = action.lower()
    s = (summary or "").lower()
    score = 0
    for kw in keywords:
        if kw == tn or kw == an:
            score += 10
        elif tn.startswith(kw) or an.startswith(kw):
            score += 5
        elif re.search(r"\b" + re.escape(kw) + r"\b", tn) or re.search(
            r"\b" + re.escape(kw) + r"\b", an
        ):
            score += 4
        elif s and re.search(r"\b" + re.escape(kw) + r"\b", s):
            score += 3
        elif kw in tn or kw in an:
            score += 2
        elif kw in s:
            score += 1
    return score


def build_tool_inventory_overview(
    available_actions: Dict[str, Set[str]],
    connections: List[Any] = None,
    custom_descriptions: Dict[str, str] = None,
    inline_action_limit: int = 8,
) -> str:
    """
    Build a compact one-shot inventory of available tools for the first
    iteration of search-mode prefilter.

    Format:
        tool_name: ACTION1, ACTION2, ...           (if ≤ inline_action_limit actions)
        tool_name: (N actions — use SEARCH)         (otherwise)

    Connection-aware: lists connection_name for tools that have connections.
    """
    # tool_name -> list of connection names
    conn_by_tool: Dict[str, List[str]] = {}
    if connections:
        for conn in connections:
            tn = getattr(conn, "tool_name", "").lower()
            cn = getattr(conn, "connection_name", "")
            if tn and cn:
                conn_by_tool.setdefault(tn, []).append(cn)

    lines: List[str] = []
    for tool_name in sorted(available_actions.keys()):
        actions = sorted(available_actions[tool_name])
        if not actions:
            continue
        conns = conn_by_tool.get(tool_name, [])
        # Prefer first connection name as identifier; tool_name in parens if differs
        if conns:
            if len(conns) == 1:
                header = f"{conns[0]} (tool={tool_name})"
            else:
                header = f"{tool_name} (connections: {', '.join(conns)})"
        else:
            header = tool_name

        if len(actions) <= inline_action_limit:
            lines.append(f"- {header}: {', '.join(actions)}")
        else:
            lines.append(f"- {header}: {len(actions)} actions — SEARCH to discover")

    return "\n".join(lines)


def search_tools_for_query(
    query: str,
    available_actions: Dict[str, Set[str]],
    connections: List[Any] = None,
    custom_descriptions: Dict[str, str] = None,
    exclude: Optional[Set[str]] = None,
    limit: int = 10,
) -> List[str]:
    """
    Score-ranked search over available tools. Supports multi-keyword queries
    (any whitespace-separated word becomes a keyword) and OR matching with
    relevance scoring. Returns the top `limit` results, excluding any
    `tool:ACTION` keys already in `exclude` (to avoid repeating tools across
    iterations).

    Results are formatted as "tool:ACTION → summary" (or just "tool:ACTION"
    when no summary is available).
    """
    keywords = _extract_keywords(query)
    if not keywords:
        return []

    exclude = exclude or set()
    # candidates: list of (score, key, display_summary)
    candidates: Dict[str, Tuple[int, str]] = {}

    # 1) Score against COMPRESSED_TOOL_DOCS summaries
    for tool_name, actions in available_actions.items():
        for action in actions:
            key = f"{tool_name}:{action}"
            if key in exclude:
                continue
            summary = COMPRESSED_TOOL_DOCS.get(tool_name, {}).get(action, "")
            score = _score_tool_action(tool_name, action, summary, keywords)
            if score > 0:
                candidates[key] = (score, summary)

    # 2) Boost by connection-name/description matches
    if connections:
        for conn in connections:
            conn_name = getattr(conn, "connection_name", "")
            tool_name = getattr(conn, "tool_name", "").lower()
            conn_desc = ""
            if hasattr(conn, "metadata") and isinstance(conn.metadata, dict):
                conn_desc = conn.metadata.get("description", "")
            conn_text = (conn_name + " " + (conn_desc or "")).lower()
            conn_boost = 0
            for kw in keywords:
                if kw in conn_text:
                    conn_boost += 2
            if conn_boost <= 0:
                continue
            for action in available_actions.get(tool_name, set()):
                key = f"{tool_name}:{action}"
                if key in exclude:
                    continue
                summary = COMPRESSED_TOOL_DOCS.get(tool_name, {}).get(action, "")
                prev = candidates.get(key, (0, summary))
                candidates[key] = (prev[0] + conn_boost, summary or prev[1])

    # 3) Custom tools (script-injected) — score by name + description
    if custom_descriptions:
        for raw_name, desc in custom_descriptions.items():
            t_name = raw_name.lower()
            # Skip standard tools (already covered above) and missing actions
            if t_name in COMPRESSED_TOOL_DOCS:
                continue
            actions = available_actions.get(t_name, {"EXECUTE"})
            for action in actions:
                key = f"{t_name}:{action}"
                if key in exclude or key in candidates:
                    continue
                desc_short = (desc or "")[:80]
                score = _score_tool_action(t_name, action, desc_short, keywords)
                if score > 0:
                    candidates[key] = (score, desc_short)

    # Sort by score desc, then by key asc (stable)
    ranked = sorted(candidates.items(), key=lambda kv: (-kv[1][0], kv[0]))
    top = ranked[:limit]
    return [f"{key} → {summary}" if summary else key for key, (_score, summary) in top]


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
