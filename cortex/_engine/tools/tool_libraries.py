"""
Python Tool Libraries for Agent Execution

Each tool is exposed as a clean Python API that agents can import and use.
These wrappers handle connection resolution, error handling, and result formatting.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import json
from delfhos.errors import ToolExecutionError, ConnectionConfigurationError
import re
import time

from ..utils.console import console
from .classification import classify_tool, is_delete_tool


def _normalize_confirm_policy(confirm_policy: Any) -> Union[bool, List[str], str]:
    if isinstance(confirm_policy, bool):
        return confirm_policy
    if isinstance(confirm_policy, list):
        return [str(p) for p in confirm_policy]
    if isinstance(confirm_policy, str):
        return confirm_policy
    return False


def _requires_approval(confirm_policy: Union[bool, List[str], str], tool_name: str, action_name: Optional[str] = None) -> bool:
    if isinstance(confirm_policy, bool):
        return confirm_policy
    if isinstance(confirm_policy, list):
        return tool_name in confirm_policy or (action_name and action_name in confirm_policy)
    if isinstance(confirm_policy, str):
        if confirm_policy == "all":
            return True
        return tool_name == confirm_policy or (action_name and action_name == confirm_policy)
    return False


def _resolve_effective_confirm_policy(
    fallback_confirm_policy: Union[bool, List[str], str],
    agent_confirm_policy: Optional[Union[bool, List[str], str]] = None,
    tool_confirm_policy: Optional[bool] = None,
) -> Tuple[Union[bool, List[str], str], bool]:
    """Resolve confirm policy precedence.

    Order:
    1) tool_confirm=True/False -> hard override (always/never ask)
    2) agent_confirm policy    -> deployment-time policy
    3) fallback policy         -> per-connection/per-call fallback
    """
    if tool_confirm_policy is True:
        return True, True
    if tool_confirm_policy is False:
        return False, True

    if agent_confirm_policy is not None:
        return _normalize_confirm_policy(agent_confirm_policy), False

    return _normalize_confirm_policy(fallback_confirm_policy), False




async def _request_unified_approval(
    *,
    tool_tracker: Any,
    task_id: str,
    tool_name: str,
    action_name: Optional[str],
    confirm_policy: Union[bool, List[str], str],
    agent_confirm_policy: Optional[Union[bool, List[str], str]] = None,
    tool_confirm_policy: Optional[bool] = None,
    connection_name: Optional[str] = None,
    message: Optional[str] = None,
    context_payload: Optional[Dict[str, Any]] = None,
    ui_metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    orchestrator = getattr(tool_tracker, "orchestrator", None) if tool_tracker else None
    if not orchestrator or not getattr(orchestrator, "approval_manager", None):
        return True

    if agent_confirm_policy is None:
        agent_confirm_policy = getattr(orchestrator, "confirm", None)

    normalized_policy, hard_override = _resolve_effective_confirm_policy(
        fallback_confirm_policy=confirm_policy,
        agent_confirm_policy=agent_confirm_policy,
        tool_confirm_policy=tool_confirm_policy,
    )
    if not hard_override and not _requires_approval(normalized_policy, tool_name, action_name):
        return True

    if action_name:
        default_message = f"Approve {action_name.upper()} operation: {tool_name}.{action_name}"
    else:
        default_message = f"Approve {tool_name.upper()} operation: {tool_name}"

    approval_payload = {
        "action": "tool.confirm",
        "tool": tool_name,
        "method": action_name,
        "action_name": action_name,
        "confirm_policy": normalized_policy,
        "agent_confirm_policy": _normalize_confirm_policy(agent_confirm_policy) if agent_confirm_policy is not None else None,
        "tool_confirm_policy": tool_confirm_policy,
        "hard_override": hard_override,
        "connection": connection_name,
    }
    if context_payload and isinstance(context_payload, dict):
        approval_payload.update(context_payload)

    try:
        context_json = json.dumps(approval_payload, ensure_ascii=False, default=str)
    except Exception:
        context_json = str(approval_payload)

    metadata = {
        "approval_kind": "tool_confirm",
        "tool_name": tool_name,
        "tool_method": action_name,
        "action_name": action_name,
        "confirm_policy": normalized_policy,
        "agent_confirm_policy": _normalize_confirm_policy(agent_confirm_policy) if agent_confirm_policy is not None else None,
        "tool_confirm_policy": tool_confirm_policy,
        "hard_override": hard_override,
        "connection_name": connection_name,
    }
    if ui_metadata and isinstance(ui_metadata, dict):
        metadata.update(ui_metadata)

    _approval_start = time.time()
    approved = await orchestrator.require_approval(
        task_id=task_id,
        message=message or default_message,
        context=context_json,
        ui_metadata=metadata,
    )
    _wait_duration = time.time() - _approval_start
    if tool_tracker and hasattr(tool_tracker, "add_pending_wait"):
        tool_tracker.add_pending_wait(_wait_duration)
    return True


def clean_json_from_markdown(text: str) -> str:
    """
    Clean JSON from markdown code blocks.
    
    Handles cases like:
    - ```json\n{...}\n```
    - ```\n{...}\n```
    - Multiple code blocks (takes the first valid JSON)
    - Just the JSON content
    
    Returns cleaned JSON string ready for parsing.
    """
    if not text or not isinstance(text, str):
        return text
    
    text = text.strip()
    
    # First, try to extract JSON from markdown code blocks
    # Match: ```json\n{...}\n``` or ```\n{...}\n```
    # Use non-greedy matching to get the first complete block
    code_block_pattern = r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```'
    code_block_matches = list(re.finditer(code_block_pattern, text, re.DOTALL))
    
    if code_block_matches:
        # Try each match until we find valid JSON
        for match in code_block_matches:
            potential_json = match.group(1).strip()
            if potential_json.startswith(('{', '[')):
                # Try to parse it to validate it's valid JSON
                try:
                    json.loads(potential_json)
                    return potential_json
                except (json.JSONDecodeError, ValueError):
                    continue
    
    # If no valid code blocks found, remove any remaining markdown markers
    text = re.sub(r'```[a-z]*\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```', '', text, flags=re.MULTILINE)
    text = text.strip()
    
    # Try to find JSON object or array in the text
    # Look for { ... } or [ ... ] - find the longest match that's valid JSON
    json_patterns = [
        r'(\{.*\})',  # JSON object (greedy)
        r'(\[.*\])',  # JSON array (greedy)
    ]
    
    for pattern in json_patterns:
        matches = list(re.finditer(pattern, text, re.DOTALL))
        # Try matches from longest to shortest
        matches.sort(key=lambda m: len(m.group(1)), reverse=True)
        for match in matches:
            potential_json = match.group(1).strip()
            if potential_json.startswith(('{', '[')):
                # Try to parse it to validate
                try:
                    json.loads(potential_json)
                    return potential_json
                except (json.JSONDecodeError, ValueError):
                    continue
    
    # If no JSON found, return cleaned text
    return text


def _truncate_preview_text(content: str, limit: int = 1000) -> str:
    preview = content[:limit]
    if len(content) > limit:
        preview += "\n\n... (truncated)"
    return preview


def _format_size_display(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


def _build_file_preview_metadata(content: Union[str, bytes], filename: str) -> Dict[str, Any]:
    """Build preview metadata for approval UI without mutating file content."""
    preview_content = None
    preview_table_data = None
    can_preview = False
    is_table_format = False

    if isinstance(content, str):
        can_preview = True

        if filename.endswith('.csv') or (',' in content and '\n' in content):
            try:
                import csv as csv_module
                from io import StringIO

                csv_reader = csv_module.reader(StringIO(content))
                rows = list(csv_reader)
                if rows:
                    preview_table_data = rows[:10]
                    is_table_format = True
                else:
                    preview_content = _truncate_preview_text(content)
            except Exception:
                preview_content = _truncate_preview_text(content)
        elif filename.endswith('.json'):
            try:
                parsed_json = json.loads(content)
                if isinstance(parsed_json, list) and len(parsed_json) > 0:
                    if isinstance(parsed_json[0], dict):
                        headers = list(parsed_json[0].keys())
                        table_rows = [headers]
                        for item in parsed_json[:10]:
                            table_rows.append([str(item.get(h, '')) for h in headers])
                        preview_table_data = table_rows
                        is_table_format = True
                    else:
                        preview_content = _truncate_preview_text(content)
                elif isinstance(parsed_json, dict):
                    formatted = json.dumps(parsed_json, indent=2, ensure_ascii=False)
                    preview_content = _truncate_preview_text(formatted)
                else:
                    preview_content = _truncate_preview_text(content)
            except Exception:
                preview_content = _truncate_preview_text(content)
        else:
            preview_content = _truncate_preview_text(content)

    return {
        "preview_content": preview_content,
        "preview_table_data": preview_table_data,
        "is_table_format": is_table_format,
        "can_preview": can_preview,
    }


class ToolLibraryBase:
    """Base class for all tool libraries"""
    
    def __init__(self, tool_manager, task_id: str, agent_id: str, light_llm: str, heavy_llm: str, tool_tracker=None,
                 vision_llm: Optional[str] = None, search_llm: Optional[str] = None, memory: Optional[Any] = None):
        self.tool_manager = tool_manager
        self.task_id = task_id
        self.agent_id = agent_id
        self.light_llm = light_llm
        self.heavy_llm = heavy_llm
        self.vision_llm = vision_llm or self.heavy_llm
        self.search_llm = search_llm or self.light_llm
        self.tool_tracker = tool_tracker
        self.memory = memory
    
    @property
    def tool_name(self) -> str:
        """Override in subclasses to return the tool name (e.g., 'gmail', 'sql')"""
        return "unknown"
    
    async def _execute_tool(self, connection_name: str, context: dict, desc: str = None, post_process_metadata: callable = None) -> Any:
        """
        Execute a tool action through the tool manager
        
        Args:
            connection_name: Name of the connection to use
            context: Tool context/parameters
            desc: Optional description for tracking
            post_process_metadata: Optional callback(result) -> dict to generate metadata from result
                                  This allows libraries to analyze results and add widget metadata
        """
        import time
        
        # Use the actual tool name (e.g., "gmail", "sql") not the action name (e.g., "read", "query")
        tool_name = self.tool_name
        start_time = time.time()
        ui_metadata = None
        
        # Allow callers to attach lightweight UI hints (e.g. code snippets) in context
        if isinstance(context, dict):
            ui_metadata = context.get("ui_metadata") or context.get("metadata") or {}
            ui_metadata["_tool_trace_args"] = context.get("params", {})
            ui_metadata["_tool_action"] = context.get("action", "")
        
        if self.tool_tracker:
            await self.tool_tracker.track_start(tool_name, desc or f"Using {tool_name}", ui_metadata=ui_metadata)
        
        try:
            action_name = None
            if isinstance(context, dict) and context.get("action"):
                action_name = str(context.get("action")).strip().lower().replace("-", "_")

            # Always print tool activity so the user has context during long tasks
            _verbose = "low"
            if self.tool_tracker and getattr(self.tool_tracker, "orchestrator", None):
                _verbose = getattr(self.tool_tracker.orchestrator, "verbose", "low")
            _tool_msg = f"[{tool_name}] {desc or f'Running {tool_name}'}"
            if _verbose == "high":
                _parts = []
                if action_name:
                    _parts.append(f"action={action_name}")
                if connection_name:
                    _parts.append(f"connection={connection_name}")
                console.tool(_tool_msg, " | ".join(_parts) if _parts else None, task_id=self.task_id, agent_id=self.agent_id)
            else:
                console.tool(_tool_msg, task_id=self.task_id, agent_id=self.agent_id)

            result = await self.tool_manager.execute_tool(
                connection_name,
                context=context,
                task_id=self.task_id,
                light_llm=self.light_llm,
                heavy_llm=self.heavy_llm,
                agent_id=self.agent_id,
                validation_mode=False,
                action=action_name,
            )
            
            # Post-process result to generate metadata (e.g., for widgets)
            if post_process_metadata and callable(post_process_metadata):
                try:
                    result_metadata = post_process_metadata(result)
                    if result_metadata and isinstance(result_metadata, dict):
                        # Merge with existing metadata
                        if ui_metadata and isinstance(ui_metadata, dict):
                            ui_metadata.update(result_metadata)
                        else:
                            ui_metadata = result_metadata
                except Exception as e:
                    # Don't fail if metadata generation fails
                    console.debug(f"[{tool_name}] Metadata generation failed", str(e), task_id=self.task_id, agent_id=self.agent_id)
            
            # Track tool call end
            duration = time.time() - start_time
            if self.tool_tracker:
                await self.tool_tracker.track_end(tool_name, duration, success=True, description=desc, ui_metadata=ui_metadata)
            
            # Track tool usage in orchestrator
            if self.tool_tracker and self.tool_tracker.orchestrator:
                self.tool_tracker.orchestrator.track_tool_usage(self.task_id, tool_name)
            
            return result
        except Exception as e:
            # Track tool call failure
            duration = time.time() - start_time
            if self.tool_tracker:
                await self.tool_tracker.track_end(tool_name, duration, success=False, error=str(e), description=desc, ui_metadata=ui_metadata)
            
            # Track tool usage even on failure
            if self.tool_tracker and self.tool_tracker.orchestrator:
                self.tool_tracker.orchestrator.track_tool_usage(self.task_id, tool_name)
            
            raise

    def _get_confirm_policy(self, connection_name: Optional[str] = None, default: Union[str, bool] = True) -> Union[str, bool]:
        if connection_name and hasattr(self.tool_manager, "connections"):
            conn = self.tool_manager.connections.get(connection_name)
            if conn is not None:
                policy = getattr(conn, "confirm", None)
                if policy is not None:
                    return policy
                return True  # confirm not configured → ask for everything
        return default


class SQLLibrary(ToolLibraryBase):
    """
    SQL Database Library - Read-only access to PostgreSQL and MySQL databases.
    
    Usage:
        from tools import sql
        
        # Get database schema
        schema = await sql.schema()
        
        # Execute read-only queries
        results = await sql.query("SELECT * FROM users WHERE active = true")
        
        # Get results as CSV for large datasets
        csv_data = await sql.query("SELECT name, cost FROM tasks", as_csv=True)
    """
    
    @property
    def tool_name(self) -> str:
        return "sql"
    
    async def schema(self, desc: str = None) -> str:
        """
        Get complete database schema (tables, columns, types, keys).
        
        Args:
            desc: Optional description of what you're doing (e.g., "Getting database structure")
        
        Returns:
            str: Formatted schema description
        """
        conn_name = self._get_sql_connection()
        result = await self._execute_tool(conn_name, {
            "action": "SCHEMA",
            "params": {}
        }, desc=desc or "Getting database schema")
        if isinstance(result, dict):
            return result.get("schema", str(result))
        return str(result)
    
    async def query(self, sql: str, as_csv: bool = False, desc: str = None) -> Union[List[Dict], str]:
        """
        Execute a read-only SQL query (SELECT only).
        
        Args:
            sql: SQL query string (SELECT only, no UPDATE/DELETE/DROP)
            as_csv: If True, return results as CSV string (efficient for large datasets)
            desc: Optional description of what you're querying (e.g., "Fetching user data")
        
        Returns:
            List[Dict] if as_csv=False (default), or str (CSV format) if as_csv=True
        
        Example:
            users = await sql.query("SELECT id, name FROM users LIMIT 10", desc="Loading active users")
            csv = await sql.query("SELECT * FROM tasks", as_csv=True, desc="Exporting all tasks")
        """
        conn_name = self._get_sql_connection()

        # NO approval needed for read-only SELECT queries
        result = await self._execute_tool(conn_name, {
            "action": "QUERY",
            "params": {
                "sql": sql,
                "read_only": True,
                "as_csv": as_csv
            },
            # Small hint for the UI so it can show the query text as a code snippet
            "ui_metadata": {
                "code_snippet": sql,
                "code_language": "sql"
            }
        }, desc=desc or f"Executing query: {sql[:50]}...")
        
        # If as_csv=True, result is already a CSV string
        if as_csv:
            return result if isinstance(result, str) else str(result)
        
        # Otherwise, extract rows from result dict
        if isinstance(result, dict) and "rows" in result:
            rows = result["rows"]
            # Normalize row keys and values to be more forgiving with LLM‑generated code:
            # - Postgres folds unquoted aliases to lowercase, but the model often uses
            #   capitalized names like "Request" / "Tokens". To avoid KeyError, we
            #   duplicate keys with simple case variants.
            # - Also collapse whitespace in string values so multi‑line text doesn't break
            #   Markdown tables (newlines inside a cell become spaces).
            if isinstance(rows, list):
                normalized_rows = []
                for row in rows:
                    if isinstance(row, dict):
                        new_row = {}
                        for key, value in row.items():
                            # Clean value whitespace for nicer formatting in tables
                            cleaned_value = value
                            if isinstance(value, str):
                                # Collapse all whitespace (including newlines) into single spaces
                                cleaned_value = re.sub(r"\s+", " ", value).strip()

                            # For common numeric fields (tokens, cost, price, amount, etc.),
                            # replace None with 0.0 so f\"{value:.2f}\" style formatting won't crash.
                            if cleaned_value is None and isinstance(key, str):
                                key_lower = key.lower()
                                if key_lower in {"tokens", "cost", "coste", "price", "amount", "importe"}:
                                    cleaned_value = 0.0
                            
                            if isinstance(key, str):
                                lower = key.lower()
                                cap = key.capitalize()
                                upper = key.upper()
                                # Base key as-is
                                new_row[key] = cleaned_value
                                # Ensure lowercase version exists
                                if lower not in new_row:
                                    new_row[lower] = cleaned_value
                                # Ensure capitalized version exists (e.g. request -> Request)
                                if cap not in new_row:
                                    new_row[cap] = cleaned_value
                                # Ensure uppercase version exists (e.g. request -> REQUEST)
                                if upper not in new_row:
                                    new_row[upper] = cleaned_value
                                
                                # Handle SQL aggregate functions (e.g., COUNT(*) returns as "count")
                                # Add common variants that LLM might use: COUNT(*), COUNT(), COUNT
                                key_lower_clean = key.lower().strip()
                                common_aggregates = {"count", "sum", "avg", "average", "max", "min", "total"}
                                if key_lower_clean in common_aggregates:
                                    # Add variants with parentheses that LLM might use
                                    variants = [
                                        f"{upper}(*)",
                                        f"{upper}()",
                                        f"{cap}(*)",
                                        f"{cap}()",
                                        f"{lower}(*)",
                                        f"{lower}()",
                                    ]
                                    for variant in variants:
                                        if variant not in new_row:
                                            new_row[variant] = cleaned_value
                            else:
                                new_row[key] = cleaned_value
                        normalized_rows.append(new_row)
                    else:
                        normalized_rows.append(row)
                return normalized_rows
            return rows
        
        # Fallback: return result as-is
        return result
    
    async def execute(self, sql: str, desc: str = None) -> Dict[str, Any]:
        """
        Execute any write SQL statement (UPDATE, INSERT, DELETE, etc.) - requires human approval.
        
        Args:
            sql: SQL query string (any write operation)
            desc: Optional description for UI tracking
        
        Returns:
            Dict with execution result (message, row_count, etc.)
        
        Example:
            result = await sql.execute("UPDATE tasks SET status = 'completed' WHERE id = 1", desc="Completing task")
        """
        # Auto-detect operation type from SQL
        sql_upper = sql.upper().strip()
        if sql_upper.startswith("DELETE"):
            operation_type = "DELETE"
        elif sql_upper.startswith("UPDATE"):
            operation_type = "UPDATE"
        elif sql_upper.startswith("INSERT"):
            operation_type = "INSERT"
        else:
            operation_type = "EXECUTE"
        
        conn_name = self._get_sql_connection()
        
        # For DELETE operations, estimate affected rows as a safety warning
        estimated_rows = None
        if operation_type == "DELETE":
            try:
                parts = sql[len("DELETE FROM"):].strip()
                if "WHERE" in parts.upper():
                    table_part, where_part = parts.split("WHERE", 1)
                    table_name = table_part.strip().split()[0]
                    count_query = f"SELECT COUNT(*) as count FROM {table_name} WHERE {where_part}"
                else:
                    table_name = parts.split()[0]
                    count_query = f"SELECT COUNT(*) as count FROM {table_name}"
                
                count_result = await self.query(count_query, desc="Estimating affected rows")
                if isinstance(count_result, list) and len(count_result) > 0:
                    estimated_rows = count_result[0].get("count", 0) if isinstance(count_result[0], dict) else count_result[0]
            except Exception:
                pass
        
        approval_message = desc or f"Approve {operation_type} operation on {conn_name}"
        if estimated_rows is not None and estimated_rows > 10:
            approval_message += f" ({estimated_rows} rows will be deleted)"

        action_name = "delete" if operation_type == "DELETE" else "write"
        ui_metadata = {
            "sql_query": sql,
            "sql_operation": operation_type,
            "sql_connection": conn_name,
        }
        if estimated_rows is not None:
            ui_metadata["estimated_rows"] = estimated_rows
            ui_metadata["has_warning"] = estimated_rows > 10

        await _request_unified_approval(
            tool_tracker=self.tool_tracker,
            task_id=self.task_id,
            tool_name="sql",
            action_name="execute",
                        confirm_policy=self._get_confirm_policy(conn_name, default="write"),
            connection_name=conn_name,
            message=approval_message,
            context_payload={
                "sql": sql,
                "sql_operation": operation_type.lower(),
                "estimated_rows": estimated_rows,
            },
            ui_metadata=ui_metadata,
        )
        
        result = await self._execute_tool(conn_name, {
            "action": "EXECUTE",
            "params": {
                "sql": sql
            },
            "ui_metadata": {
                "code_snippet": sql,
                "code_language": "sql"
            }
        }, desc=desc or f"Executing {operation_type.lower()}: {sql[:50]}...")
        
        if isinstance(result, dict):
            return result
        return {"message": str(result), "rows": [], "row_count": 0}


    
    def _get_sql_connection(self) -> str:
        """Get the first active SQL connection name."""
        for conn in self.tool_manager.connections.values():
            if getattr(conn, "tool_name", "").lower() == "sql" and conn.is_active():
                return conn.connection_name
        raise ConnectionConfigurationError(tool_name="SQL", detail="No active SQL connection found")


class SheetsLibrary(ToolLibraryBase):
    """
    Google Sheets Library - Create, read, and write spreadsheets.
    
    Usage:
        sheet_id = await sheets.create("Sales Report 2024", desc="Creating report")
        await sheets.write(sheet_id, [["Name", "Amount"], ["John", 1000]], desc="Writing data")
        data = await sheets.read(sheet_id, range="Sheet1!A1:B10", desc="Reading data")
    """
    
    @property
    def tool_name(self) -> str:
        return "sheets"
    
    async def create(self, title: str, data: Any = None, sheet: str = "Sheet1", desc: str = None) -> str:
        """
        Create a new spreadsheet.
        
        Args:
            title: Title of the spreadsheet
            data: Optional initial data (List[List] or List[Dict]). Combining CREATE + Data is much faster than doing it in two steps.
            sheet: Name of the sheet to write data to (default: "Sheet1")
            desc: Optional description for tracking
            
        Returns surface spreadsheet ID.
        """
        conn_name = self._get_sheets_connection()
        tool_name = self.tool_name
        start_time = time.time()
        description = desc or f"Creating spreadsheet: {title}"
        
        # Track start
        if self.tool_tracker:
            await self.tool_tracker.track_start(tool_name, description)
        
        params = {"title": title}
        if data is not None:
            # Normalize data if it's List[Dict]
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                headers = list(data[0].keys())
                data = [headers] + [[row.get(h, "") for h in headers] for row in data]
            params["data"] = data
            params["sheet"] = sheet

        await _request_unified_approval(
            tool_tracker=self.tool_tracker,
            task_id=self.task_id,
            tool_name="sheets",
            action_name="create",
            confirm_policy=self._get_confirm_policy(conn_name, default="write"),
            connection_name=conn_name,
            message=desc or f"Approve creating spreadsheet: {title}",
            context_payload={"title": title, "sheet": sheet},
        )

        try:
            result = await self.tool_manager.execute_tool(
                conn_name,
                context={
                    "action": "CREATE",
                    "params": params
                },
                task_id=self.task_id,
                light_llm=self.light_llm,
                heavy_llm=self.heavy_llm,
                agent_id=self.agent_id,
                validation_mode=False
            )
            
            sheet_id = result.get("spreadsheet_id") if isinstance(result, dict) else result
            
            # Build sheet URL for metadata
            sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}" if sheet_id else None
            
            # Track end with metadata containing the sheet URL
            duration = time.time() - start_time
            ui_metadata = {}
            if sheet_url:
                ui_metadata["sheet_link"] = sheet_url
            
            if self.tool_tracker:
                await self.tool_tracker.track_end(
                    tool_name, 
                    duration, 
                    success=True, 
                    description=description,
                    ui_metadata=ui_metadata if ui_metadata else None
                )
            
            # Track tool usage
            if self.tool_tracker and self.tool_tracker.orchestrator:
                self.tool_tracker.orchestrator.track_tool_usage(self.task_id, tool_name)
            
            return sheet_id
        except Exception as e:
            duration = time.time() - start_time
            if self.tool_tracker:
                await self.tool_tracker.track_end(tool_name, duration, success=False, error=str(e), description=description)
            if self.tool_tracker and self.tool_tracker.orchestrator:
                self.tool_tracker.orchestrator.track_tool_usage(self.task_id, tool_name)
            raise
    
    async def read(self, spreadsheet_id: str, range: str = "Sheet1", desc: str = None) -> List[List[Any]]:
        """
        Read data from a spreadsheet range.
        
        Args:
            spreadsheet_id: Spreadsheet ID
            range: Range in 'Sheet1!A1:D10' format (default: 'Sheet1')
            desc: Optional description for UI tracking
        
        Returns:
            List[List] - 2D array of cell values
        """
        conn_name = self._get_sheets_connection()
        
        # Parse "Sheet1!A1:D10" into sheet_name and range_notation
        if "!" in range:
            sheet_name, range_notation = range.split("!", 1)
        else:
            sheet_name = range
            range_notation = "A:ZZ"
        
        def generate_sheet_metadata(result):
            metadata = {}
            if spreadsheet_id:
                sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
                metadata["sheet_link"] = sheet_url
                metadata["sheet_widget"] = {
                    "spreadsheet_id": spreadsheet_id,
                    "sheet_name": sheet_name,
                    "range": range_notation,
                    "url": sheet_url
                }
            return metadata
        
        result = await self._execute_tool(
            conn_name, 
            {
                "action": "READ",
                "params": {
                    "spreadsheet_id": spreadsheet_id,
                    "sheet_name": sheet_name,
                    "range": range_notation
                }
            }, 
            desc=desc or f"Reading {sheet_name}!{range_notation}",
            post_process_metadata=generate_sheet_metadata
        )
        return result.get("values", []) if isinstance(result, dict) else result
    
    async def write(self, spreadsheet_id: str, data, sheet: str = "Sheet1", cell: str = "A1", desc: str = None) -> dict:
        """
        Write data to a spreadsheet.
        
        Args:
            spreadsheet_id: Spreadsheet ID
            data: Data to write. Accepts:
                - List[List]: 2D array (e.g. [["Name", "Value"], ["A", 1]])
                - List[Dict]: Auto-converted to List[List] with headers from dict keys
                - str: CSV string (loaded directly)
            sheet: Sheet name (default: "Sheet1")
            cell: Starting cell (default: "A1")
            desc: Optional description for UI tracking
        """
        conn_name = self._get_sheets_connection()
        
        # Auto-detect and normalize data format
        if isinstance(data, str):
            # CSV string — use csv loader
            await _request_unified_approval(
                tool_tracker=self.tool_tracker,
                task_id=self.task_id,
                tool_name="sheets",
                action_name="write",
                confirm_policy=self._get_confirm_policy(conn_name, default="write"),
                connection_name=conn_name,
                message=desc or f"Approve writing CSV data to {sheet}!{cell}",
                context_payload={"spreadsheet_id": spreadsheet_id, "sheet_name": sheet, "start_cell": cell},
            )
            return await self._execute_tool(conn_name, {
                "action": "BATCH",
                "params": {
                    "spreadsheet_id": spreadsheet_id,
                    "ops": [f"csv {cell} | {data}"]
                }
            }, desc=desc or f"Loading CSV data to {sheet}!{cell}")
        
        # Convert List[Dict] to List[List] with headers
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            headers = list(data[0].keys())
            data = [headers] + [[row.get(h, "") for h in headers] for row in data]
        
        preview_data = data[:10] if len(data) > 10 else data
        await _request_unified_approval(
            tool_tracker=self.tool_tracker,
            task_id=self.task_id,
            tool_name="sheets",
            confirm_policy=self._get_confirm_policy(conn_name, default="write"),
            connection_name=conn_name,
            message=desc or f"Approve writing data to {sheet}!{cell}",
            context_payload={
                "spreadsheet_id": spreadsheet_id,
                "sheet_name": sheet,
                "start_cell": cell,
                "data_rows": len(data),
            },
            ui_metadata={
                "spreadsheet_id": spreadsheet_id,
                "sheet_name": sheet,
                "start_cell": cell,
                "data_preview": preview_data,
                "total_rows": len(data),
            },
        )
        
        return await self._execute_tool(conn_name, {
            "action": "BATCH",
            "params": {
                "spreadsheet_id": spreadsheet_id,
                "ops": [
                    f"@{sheet}",
                    f"w {cell} | $data"
                ]
            },
            "variables": {
                "data": data
            }
        }, desc=desc or f"Writing data to {sheet}!{cell}")
    

    def _get_sheets_connection(self) -> str:
        """Get the first active Sheets connection name."""
        for conn in self.tool_manager.connections.values():
            if getattr(conn, "tool_name", "").lower() == "sheets" and conn.is_active():
                return conn.connection_name
        raise ConnectionConfigurationError(tool_name="Sheets", detail="No active Sheets connection found")


class GmailLibrary(ToolLibraryBase):
    """
    Gmail Library - Send, read emails, and download attachments.
    
    Usage:
        emails = await gmail.read(query="is:unread", max_results=10, desc="Reading unread")
        # Each email: {id, subject, from_email, body, date, attachments: [{attachment_id, filename, mime_type, size}]}
        await gmail.send(to="a@b.com", subject="Hi", body="Hello", desc="Sending email")
        paths = await gmail.download_attachments(email, desc="Downloading")
    """
    
    @property
    def tool_name(self) -> str:
        return "gmail"
    
    async def send(self, to: str, subject: str, body: str, cc: Optional[str] = None, 
                   bcc: Optional[str] = None, attachments: Optional[List[str]] = None, desc: str = None) -> dict:
        """
        Send an email via Gmail.
        
        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body text
            cc: Optional CC recipients (comma-separated string or list)
            bcc: Optional BCC recipients (comma-separated string or list)
            attachments: Optional list of file paths to attach (e.g., ["uploads/task_id/file.pdf"])
            desc: Optional description for UI tracking
            
        Returns:
            dict with success message
        """
        conn_name = self._get_gmail_connection()
        
        draft = {
            "to": to,
            "cc": cc,
            "bcc": bcc,
            "subject": subject,
            "body": body,
            "attachments": attachments or [],
        }
        await _request_unified_approval(
            tool_tracker=self.tool_tracker,
            task_id=self.task_id,
            tool_name="gmail",
            action_name="send",
            confirm_policy=self._get_confirm_policy(conn_name, default="write"),
            connection_name=conn_name,
            message=desc or f"Approve sending email to {to}: {subject}",
            context_payload={"draft": draft},
            ui_metadata={"gmail_send_draft": draft},
        )
        params = {
            "to": to,
            "subject": subject,
            "body": body
        }
        if cc:
            params["cc"] = cc
        if bcc:
            params["bcc"] = bcc
        if attachments:
            params["attachments"] = attachments
        
        attachment_info = f" with {len(attachments)} attachment(s)" if attachments else ""
        return await self._execute_tool(conn_name, {
            "action": "SEND",
            "params": params
        }, desc=desc or f"Sending email to {to}: {subject}{attachment_info}")
    
    async def read(self, max_results: int = 10, query: str = "", desc: str = None) -> List[Dict]:
        """
        Read emails from Gmail. Always includes attachment metadata.
        
        Args:
            max_results: Maximum number of emails to return
            query: Gmail search query (e.g., "is:unread", "from:boss@company.com")
            desc: Optional description (e.g., "Looking for the last email")
        
        Returns:
            List[Dict] with keys: id, subject, from_email, body, date, snippet, attachments
            Each attachment dict has: attachment_id, filename, mime_type, size
            Returns empty list if no emails found
        """
        conn_name = self._get_gmail_connection()
        default_desc = f"Reading {max_results} emails"
        if query:
            default_desc += f" matching '{query}'"
        
        def generate_email_metadata(result):
            """Generate metadata for email widgets - one widget per email"""
            metadata = {}
            if isinstance(result, list) and len(result) > 0:
                # Create a widget for each email
                email_widgets = []
                for email in result:
                    if isinstance(email, dict):
                        email_widgets.append({
                            "id": email.get("id", ""),
                            "subject": email.get("subject", "(no subject)"),
                            "from": email.get("from_email", ""),
                            "date": email.get("date", ""),
                            "snippet": email.get("snippet", "")[:100] if email.get("snippet") else "",
                            "body": email.get("body", ""),
                            "body_html": email.get("body_html", ""),
                            "to": email.get("to", []),
                            "attachments": email.get("attachments", [])
                        })
                if email_widgets:
                    metadata["email_widgets"] = email_widgets
            return metadata
        
        result = await self._execute_tool(
            conn_name, 
            {
                "action": "READ",
                "params": {
                    "max": max_results,
                    "query": query,
                    "include_body": True,
                    "include_attachments": True,  # Always include attachments
                    "return_structured": True  # Request structured data (list of dicts)
                }
            }, 
            desc=desc or default_desc,
            post_process_metadata=generate_email_metadata
        )
        
        # Gmail tool should now return a list of dicts when return_structured=True
        if isinstance(result, list):
            # Strip body_html from the result - it's only needed for the frontend
            # widget (already extracted by generate_email_metadata above).
            # The LLM should only process clean text via the 'body' field.
            for email in result:
                if isinstance(email, dict):
                    email.pop("body_html", None)
            return result
        
        # Fallback: if tool returns string (backward compatibility), return empty list
        if isinstance(result, str):
            if result.startswith("No emails found"):
                return []
            # Log warning if we get unexpected format
            console.debug(
                "[GMAIL] Tool returned string instead of structured data",
                f"Result: {result[:200]}...",
                task_id=self.task_id,
                agent_id=self.agent_id
            )
            return []
        
        return []
    
    async def download_attachments(self, email: Dict, desc: str = None) -> List[str]:
        """
        Download all attachments from an email.
        
        Args:
            email: Email dict from gmail.read() with attachments
            desc: Optional description for UI tracking
            
        Returns:
            List[str]: List of file paths for downloaded attachments
        """
        if not email.get('attachments'):
            return []
        
        from ..tools.gmail.gmail_client import GmailClient
        from ..tools.files import save_output_file
        
        conn_name = self._get_gmail_connection()
        connection = self.tool_manager.connections.get(conn_name)
        if not connection:
            raise ConnectionConfigurationError(tool_name="Gmail", detail=f"Gmail connection '{conn_name}' not found")
        
        credentials = connection.get_credentials()
        gmail_client = GmailClient(credentials)
        
        file_paths = []
        for att in email['attachments']:
            attachment_data = gmail_client.get_attachment(email['id'], att['attachment_id'])
            filename = att.get('filename', f"attachment_{att['attachment_id']}")
            file_path = await save_output_file(self.task_id, filename, attachment_data, self.agent_id)
            file_paths.append(file_path)
        
        return file_paths
    
    def _get_gmail_connection(self) -> str:
        """Get the first active Gmail connection name."""
        for conn in self.tool_manager.connections.values():
            if getattr(conn, "tool_name", "").lower() == "gmail" and conn.is_active():
                return conn.connection_name
        raise ConnectionConfigurationError(tool_name="Gmail", detail="No active Gmail connection found")


class DriveLibrary(ToolLibraryBase):
    """
    Google Drive Library - Search, upload, and manage files.
    
    Usage:
        from tools import drive
        
        # Search for files
        file_id = await drive.search(name="Report", mime_type="spreadsheet")
        
        # Upload file
        file_id = await drive.upload("path/to/file.pdf", name="Document")
        
        # Get file metadata
        metadata = await drive.get_metadata(file_id)
    """
    
    @property
    def tool_name(self) -> str:
        return "drive"
    
    async def search(self, name: str = "", mime_type: str = "", desc: str = None) -> Optional[str]:
        """
        Search for a file in Google Drive.
        
        Args:
            name: File name to search for
            mime_type: MIME type filter ("spreadsheet", "document", "pdf", etc.)
            desc: Optional description (e.g., "Looking for the sales report")
        
        Returns:
            File ID of first match, or None if not found
        """
        conn_name = self._get_drive_connection()
        default_desc = f"Searching for file: {name}" if name else "Searching Drive"
        if mime_type:
            default_desc += f" ({mime_type})"
        
        def generate_drive_metadata(result):
            """Generate metadata for drive file widget"""
            metadata = {}
            if isinstance(result, dict) and "files" in result:
                files = result.get("files", [])
                if files and isinstance(files, list) and len(files) > 0:
                    first_file = files[0]
                    if isinstance(first_file, dict):
                        file_id = first_file.get("id")
                        file_name = first_file.get("name", name or "Untitled")
                        mime_type_actual = first_file.get("mimeType", "")
                        
                        if file_id:
                            drive_url = f"https://drive.google.com/file/d/{file_id}"
                            metadata["drive_link"] = drive_url
                            metadata["drive_widget"] = {
                                "file_id": file_id,
                                "name": file_name,
                                "mime_type": mime_type_actual,
                                "url": drive_url
                            }
            return metadata
        
        result = await self._execute_tool(
            conn_name, 
            {
                "action": "SEARCH",
                "params": {
                    "name": name,
                    "mimeType": mime_type
                }
            }, 
            desc=desc or default_desc,
            post_process_metadata=generate_drive_metadata
        )
        
        # Extract first file ID from result
        if isinstance(result, dict) and "files" in result:
            files = result.get("files", [])
            if files and isinstance(files, list) and len(files) > 0:
                first_file = files[0]
                if isinstance(first_file, dict):
                    return first_file.get("id")
        
        return None
    
    async def upload(self, file_path_or_bytes, name: str = "", folder_id: str = "", desc: str = None) -> str:
        """
        Upload a file to Google Drive.
        
        Args:
            file_path_or_bytes: Path to file to upload (str) OR raw bytes content.
                      For files uploaded by user: "uploads/{task_id}/filename.ext"
                      For files saved by agent: "uploads/{task_id}/output/filename.ext"
                      Also accepts raw bytes (e.g. from io.BytesIO.getvalue())
            name: Display name in Drive (defaults to filename from path)
            folder_id: Optional Drive folder ID to upload to
            desc: Optional description for UI tracking
            
        Returns:
            str: Full URL to the uploaded file in Google Drive (or File ID if URL creation failed)
            
        Examples:
            # Upload user's file
            link = await drive.upload(
                "uploads/abc123/data.csv",
                name="Sales Data Q4",
                desc="Uploading user's data to Drive"
            )
            
            # Upload raw bytes (e.g. from matplotlib)
            link = await drive.upload(
                buf.getvalue(),
                name="chart.png",
                desc="Uploading chart"
            )
        """
        from pathlib import Path
        import base64
        conn_name = self._get_drive_connection()
        tool_name = self.tool_name
        start_time = time.time()
        
        # Detect if the first argument is raw bytes or a file path
        is_bytes = isinstance(file_path_or_bytes, (bytes, bytearray))
        file_path = None if is_bytes else str(file_path_or_bytes)
        raw_content = file_path_or_bytes if is_bytes else None
        
        # Handle fallback for name
        if not name:
            name = ""
        
        # Auto-detect filename from path if not provided
        if not name and file_path:
            name = Path(file_path).name
        if not name:
            name = "uploaded_file"
        
        # Auto-detect mime_type from file extension
        mime_type = ""
        if file_path:
            import mimetypes
            mime_type = mimetypes.guess_type(file_path)[0] or ""
        
        description = desc or f"Uploading {name} to Drive"

        await _request_unified_approval(
            tool_tracker=self.tool_tracker,
            task_id=self.task_id,
            tool_name="drive",
            action_name="upload",
            confirm_policy=self._get_confirm_policy(conn_name),
            connection_name=conn_name,
            message=description,
            context_payload={"name": name, "folder_id": folder_id},
        )

        # Track start
        if self.tool_tracker:
            await self.tool_tracker.track_start(tool_name, description)

        try:
            # Build params based on whether we have raw bytes or a file path
            params = {
                "name": name,
                "folderId": folder_id
            }
            if raw_content is not None:
                # Pass raw bytes as base64-encoded content
                params["content"] = base64.b64encode(raw_content).decode("ascii")
            else:
                params["file_path"] = file_path
            if mime_type:
                params["mimeType"] = mime_type
            
            result = await self.tool_manager.execute_tool(
                conn_name,
                context={
                    "action": "CREATE",
                    "params": params
                },
                task_id=self.task_id,
                light_llm=self.light_llm,
                heavy_llm=self.heavy_llm,
                agent_id=self.agent_id,
                validation_mode=False
            )
        
        # Extract file_id from result
            file_id = None
            if isinstance(result, dict):
                file_id = result.get("fileId") or result.get("file_id") or result.get("id") or ""
            else:
                file_id = str(result)
            
            # Build Drive URL for metadata
            drive_url = f"https://drive.google.com/file/d/{file_id}" if file_id else None
            
            # Track end with metadata containing the Drive URL
            duration = time.time() - start_time
            ui_metadata = {}
            if drive_url:
                ui_metadata["drive_link"] = drive_url
            
            if self.tool_tracker:
                await self.tool_tracker.track_end(
                    tool_name, 
                    duration, 
                    success=True, 
                    description=description,
                    ui_metadata=ui_metadata if ui_metadata else None
                )
            
            # Track tool usage
            if self.tool_tracker and self.tool_tracker.orchestrator:
                self.tool_tracker.orchestrator.track_tool_usage(self.task_id, tool_name)
            
            return drive_url if drive_url else file_id
        except Exception as e:
            duration = time.time() - start_time
            if self.tool_tracker:
                await self.tool_tracker.track_end(tool_name, duration, success=False, error=str(e), description=description)
            if self.tool_tracker and self.tool_tracker.orchestrator:
                self.tool_tracker.orchestrator.track_tool_usage(self.task_id, tool_name)
            raise
    
    def _get_drive_connection(self) -> str:
        """Get the first active Drive connection name."""
        for conn in self.tool_manager.connections.values():
            if getattr(conn, "tool_name", "").lower() == "drive" and conn.is_active():
                return conn.connection_name
        raise ConnectionConfigurationError(tool_name="Drive", detail="No active Drive connection found")



class DocsLibrary(ToolLibraryBase):
    """
    Google Docs Library - Create, read, and update documents.
    """
    
    @property
    def tool_name(self) -> str:
        return "docs"
    
    def _get_docs_connection(self) -> str:
        """Get the first active Docs connection name."""
        for conn in self.tool_manager.connections.values():
            if getattr(conn, "tool_name", "").lower() == "docs" and conn.is_active():
                return conn.connection_name
        raise ConnectionConfigurationError(tool_name="Docs", detail="No active Docs connection found")

    def _parse_markdown_line(self, line: str, current_index: int) -> tuple[str, list[dict]]:
        """
        Parse a line for markdown elements (bold, italic, strikethrough, code, links).
        Returns (clean_text, ops)
        """
        ops = []
        clean_text = ""
        pattern = re.compile(
            r'(\*\*(.*?)\*\*|__(.*?)__)'       # 1, 2, 3: Bold
            r'|(\*(.*?)\*|_(.*?)_)'            # 4, 5, 6: Italic
            r'|(~~(.*?)~~)'                    # 7, 8: Strike
            r'|(`(.*?)`)'                      # 9, 10: Code
            r'|(\[(.*?)\]\((.*?)\))'           # 11, 12, 13: Link
        )
        last_end = 0
        local_index = 0
        
        for m in pattern.finditer(line):
            pre_text = line[last_end:m.start()]
            clean_text += pre_text
            local_index += len(pre_text)
            
            content = ""
            style = {}
            link_url = None
            
            if m.group(1):
                content = m.group(2) if m.group(2) is not None else m.group(3)
                style = {"bold": True}
            elif m.group(4):
                content = m.group(5) if m.group(5) is not None else m.group(6)
                style = {"italic": True}
            elif m.group(7):
                content = m.group(8)
                style = {"strikethrough": True}
            elif m.group(9):
                content = m.group(10)
                style = {"weightedFontFamily": {"fontFamily": "Courier New"}}
            elif m.group(11):
                content = m.group(12)
                link_url = m.group(13)
                style = {
                    "underline": True,
                    "foregroundColor": {"color": {"rgbColor": {"red": 0.11, "green": 0.53, "blue": 0.98}}}
                }
            
            start_format = current_index + local_index
            clean_text += content
            local_index += len(content)
            end_format = current_index + local_index
            
            if style:
                fields_str = ",".join(list(style.keys()))
                req = {
                    "updateTextStyle": {
                        "range": {"startIndex": start_format, "endIndex": end_format},
                        "textStyle": style,
                        "fields": fields_str
                    }
                }
                if link_url:
                    req["updateTextStyle"]["textStyle"]["link"] = {"url": link_url}
                    req["updateTextStyle"]["fields"] += ",link"
                ops.append(req)
                
            last_end = m.end()
            
        clean_text += line[last_end:]
        return clean_text, ops

    def _markdown_to_ops(self, content: str, start_index: int = 1) -> list[dict]:
        """Convert markdown content to Google Docs batch update operations."""
        ops = []
        current_index = start_index
        lines = content.split('\n')
        in_code_block = False
        
        for line in lines:
            # Code block marker
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                continue 
            
            # Append newline to every line for Docs structure
            text_to_insert = line + "\n"
            
            # 1. Code Block
            if in_code_block:
                ops.append({
                    "insertText": {
                        "text": text_to_insert,
                        "location": {"index": current_index}
                    }
                })
                ops.append({
                    "updateTextStyle": {
                        "range": {
                            "startIndex": current_index,
                            "endIndex": current_index + len(text_to_insert)
                        },
                        "textStyle": {"weightedFontFamily": {"fontFamily": "Courier New"}},
                        "fields": "weightedFontFamily"
                    }
                })
                # Add a light gray background for code? Optional but good.
                # textStyle.backgroundColor?
                current_index += len(text_to_insert)
                continue

            # 2. Heading
            heading_match = re.match(r'^(#{1,6})\s+(.*)', line)
            if heading_match:
                level = len(heading_match.group(1))
                # Remove # and spaces
                clean_content = heading_match.group(2)
                full_insert = clean_content + "\n"
                
                ops.append({
                    "insertText": {
                        "text": full_insert,
                        "location": {"index": current_index}
                    }
                })
                
                style = f"HEADING_{level}"
                ops.append({
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": current_index, 
                            "endIndex": current_index + len(full_insert)
                        },
                        "paragraphStyle": {"namedStyleType": style},
                        "fields": "namedStyleType"
                    }
                })
                current_index += len(full_insert)
                continue

            # 3. Table Row (Monospace substitute for Real Tables)
            if line.strip().startswith('|'):
                # We can't do real tables easily via batchUpdate without index callbacks.
                # Use Courier New for alignment.
                ops.append({
                    "insertText": {
                        "text": text_to_insert,
                        "location": {"index": current_index}
                    }
                })
                ops.append({
                    "updateTextStyle": {
                        "range": {
                            "startIndex": current_index,
                            "endIndex": current_index + len(text_to_insert)
                        },
                        "textStyle": {
                            "weightedFontFamily": {"fontFamily": "Courier New"},
                            "fontSize": {"magnitude": 9, "unit": "PT"}
                        },
                        "fields": "weightedFontFamily,fontSize"
                    }
                })
                current_index += len(text_to_insert)
                continue

            # 4. List Items
            list_match = re.match(r'^(\s*)([-*]|\d+\.)\s+(.*)', line)
            if list_match:
                bullet_type = list_match.group(2)
                content = list_match.group(3)
                clean_line, style_ops = self._parse_markdown_line(content, current_index)
                preset = "NUMBERED_DECIMAL_ALPHA_ROMAN" if bullet_type.endswith('.') else "BULLET_DISC_CIRCLE_SQUARE"
                clean_insert = clean_line + "\n"
                
                ops.append({
                    "insertText": {
                        "text": clean_insert,
                        "location": {"index": current_index}
                    }
                })
                ops.extend(style_ops)
                
                ops.append({
                    "createParagraphBullets": {
                        "range": {
                            "startIndex": current_index,
                            "endIndex": current_index + len(clean_insert)
                        },
                        "bulletPreset": preset
                    }
                })
                current_index += len(clean_insert)
                continue

            # 5. Normal Text (with inline markdown processing)
            clean_line, style_ops = self._parse_markdown_line(line, current_index)
            clean_insert = clean_line + "\n"
            
            ops.append({
                "insertText": {
                    "text": clean_insert,
                    "location": {"index": current_index}
                }
            })
            
            # Apply styling ops (already have correct ranges calculated relative to start)
            ops.extend(style_ops)
            current_index += len(clean_insert)
            
        return ops

    async def create(self, title: str, content: str = "", desc: str = None) -> str:
        import time
        conn_name = self._get_docs_connection()
        start_time = time.time()
        # Track usage
        if self.tool_tracker:
            await self.tool_tracker.track_start("docs", desc or f"Creating doc: {title}")
        
        await _request_unified_approval(
            tool_tracker=self.tool_tracker,
            task_id=self.task_id,
            tool_name="docs",
            action_name="create",
            confirm_policy=self._get_confirm_policy(conn_name),
            connection_name=conn_name,
            message=desc or f"Approve creating document: {title}",
            context_payload={"title": title},
        )

        try:
            # 1. Create the document and update content if supplied
            params = {"title": title}
            if content:
                ops = self._markdown_to_ops(content, start_index=1)
                params["operations"] = ops

            result = await self.tool_manager.execute_tool(
                conn_name,
                context={
                    "action": "CREATE",
                    "params": params
                },
                task_id=self.task_id,
                light_llm=self.light_llm,
                heavy_llm=self.heavy_llm,
                agent_id=self.agent_id,
                validation_mode=False
            )
            
            # Fix key mismatch: tool returns 'document_id', we checked 'documentId'
            doc_id = None
            if isinstance(result, dict):
                doc_id = result.get("documentId") or result.get("document_id")
            else:
                doc_id = str(result)
            
            # The tool executes the operations inline to save a network loop.

            # Metadata for UI
            duration = time.time() - start_time
            ui_metadata = {}
            if doc_id:
                ui_metadata["doc_link"] = f"https://docs.google.com/document/d/{doc_id}"
            
            if self.tool_tracker:
                await self.tool_tracker.track_end("docs", duration, success=True, description=desc or f"Created doc: {title}", ui_metadata=ui_metadata)
            
            return doc_id
        except Exception as e:
            duration = time.time() - start_time
            if self.tool_tracker:
                await self.tool_tracker.track_end("docs", duration, success=False, error=str(e))
            raise

    async def read(self, document_id: str, desc: str = None) -> str:
        conn_name = self._get_docs_connection()
        
        # Helper to generate metadata
        def generate_doc_metadata(result):
            metadata = {}
            if document_id:
                metadata["doc_link"] = f"https://docs.google.com/document/d/{document_id}"
            return metadata

        result = await self._execute_tool(
            conn_name,
            {
                "action": "READ",
                "params": {"documentId": document_id}
            },
            desc=desc or f"Reading doc: {document_id}",
            post_process_metadata=generate_doc_metadata
        )
        if isinstance(result, dict):
            return result.get("content", "")
        return str(result)

    async def update(self, document_id: str, content: str, desc: str = None) -> None:
        conn_name = self._get_docs_connection()
        await _request_unified_approval(
            tool_tracker=self.tool_tracker,
            task_id=self.task_id,
            tool_name="docs",
            action_name="update",
            confirm_policy=self._get_confirm_policy(conn_name),
            connection_name=conn_name,
            message=desc or f"Approve updating document: {document_id}",
            context_payload={"document_id": document_id},
        )
        # Use Markdown-aware operations
        ops = self._markdown_to_ops(content, start_index=1)

        await self.tool_manager.execute_tool(
            conn_name,
            {
                "action": "UPDATE",
                "params": {
                    "documentId": document_id,
                    "operations": ops
                }
            },
            task_id=self.task_id,
            light_llm=self.light_llm,
            heavy_llm=self.heavy_llm,
            agent_id=self.agent_id,
            validation_mode=False
        )


class CalendarLibrary(ToolLibraryBase):
    """
    Google Calendar Library - Create and manage calendar events.
    
    Usage:
        from tools import calendar
        
        # List events
        events = await calendar.list(
            time_min="2025-01-01T00:00:00Z",
            time_max="2025-01-31T23:59:59Z"
        )
        
        # Create event
        await calendar.create(
            summary="Team Meeting",
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z"
        )
    """
    
    @property
    def tool_name(self) -> str:
        return "calendar"
    
    async def list(self, start: str, end: str, max_results: int = 50, desc: str = None) -> List[Dict]:
        """
        List calendar events in a time range.
        
        Args:
            start: Start time (ISO 8601 format: "2025-01-01T00:00:00Z")
            end: End time (ISO 8601 format: "2025-01-31T23:59:59Z")
            desc: Optional description (e.g., "Finding next week's meetings")
        
        Returns:
            List[Dict] - each event dict has: id, summary, start, end, description, location, etc.
        """
        conn_name = self._get_calendar_connection()
        result = await self._execute_tool(conn_name, {
            "action": "LIST",
            "params": {
                "timeMin": start,
                "timeMax": end,
                "maxResults": max_results
            }
        }, desc=desc or f"Listing calendar events")
        
        # Extract events from result dict
        if isinstance(result, dict) and "events" in result:
            return result.get("events", [])
        
        # Fallback if already a list
        return result if isinstance(result, list) else []
    
    async def create(self, summary: str, start: str, end: str,
                    description: str = "", location: str = "", desc: str = None) -> dict:
        """
        Create a calendar event.

        Args:
            summary: Event title
            start: Start time (ISO 8601: "2025-01-15T10:00:00Z")
            end: End time (ISO 8601: "2025-01-15T11:00:00Z")
            desc: Optional description for tracking (e.g., "Creating team meeting")
        """
        conn_name = self._get_calendar_connection()
        await _request_unified_approval(
            tool_tracker=self.tool_tracker,
            task_id=self.task_id,
            tool_name="calendar",
            action_name="create",
            confirm_policy=self._get_confirm_policy(conn_name),
            connection_name=conn_name,
            message=desc or f"Approve creating calendar event: {summary}",
            context_payload={"summary": summary, "start": start, "end": end, "location": location},
        )
        return await self._execute_tool(conn_name, {
            "action": "CREATE",
            "params": {
                "summary": summary,
                "start": start,
                "end": end,
                "description": description,
                "location": location
            }
        }, desc=desc or f"Creating event: {summary}")
    
    def _get_calendar_connection(self) -> str:
        """Get the first active Calendar connection name."""
        for conn in self.tool_manager.connections.values():
            if getattr(conn, "tool_name", "").lower() == "calendar" and conn.is_active():
                return conn.connection_name
        raise ConnectionConfigurationError(tool_name="Calendar", detail="No active Calendar connection found")


class WebSearchLibrary(ToolLibraryBase):
    """
    Web Search Library - Search the internet for information using an LLM.
    
    LLM-powered: Request specific output formats (JSON, numbers, lists) in your query.
    
    Usage:
        # Basic search
        results = await websearch.search("Python async programming best practices")
        
        # Request format - LLM will extract and return data in requested format
        rate = await websearch.search(
            "Current 30-year fixed mortgage rate USA? Return ONLY the percentage number"
        )
        
        # JSON format request
        stats = await websearch.search(
            "COVID cases by country. Return as JSON: {country: cases}"
        )
    """
    
    def __init__(self, tool_manager, task_id: str, agent_id: str, light_llm: str, heavy_llm: str, tool_tracker=None,
                 vision_llm: Optional[str] = None, search_llm: Optional[str] = None, memory: Optional[Any] = None):
        """Override base __init__ to extract llm from WebSearch connection if available"""
        super().__init__(tool_manager, task_id, agent_id, light_llm, heavy_llm, tool_tracker, vision_llm, search_llm, memory)
        
        # Try to get the llm from WebSearch connection metadata
        # This allows WebSearch to be self-contained with its own model
        if hasattr(tool_manager, 'connections'):
            for conn_name, conn in tool_manager.connections.items():
                if hasattr(conn, 'tool_name') and conn.tool_name.lower() == 'websearch':
                    # Extract llm from connection metadata
                    if hasattr(conn, 'metadata') and conn.metadata and 'llm' in conn.metadata:
                        self.search_llm = conn.metadata['llm']
                        break
    
    @property
    def tool_name(self) -> str:
        return "websearch"
    
    async def search(self, query: str, max_results: int = 5, desc: str = None) -> str:
        """
        Search the web using an LLM-powered interface.
        
        Include format instructions in the query for structured results.
        
        Args:
            query: Search query with optional format instructions
                   Examples: "Return percentage", "Format as JSON", "List as 1. 2. 3."
            max_results: Maximum results (unused - kept for compatibility)
            desc: Optional description for logging
        
        Returns:
            str - Formatted search results per your query instructions
        """
        import time
        from ..tools.websearch import web_search
        
        tool_name = "websearch"
        description = desc or f"Searching: {query}"
        start_time = time.time()
        
        if self.tool_tracker:
            await self.tool_tracker.track_start(tool_name, description, model=self.search_llm)
        
        try:
            result, token_info = await web_search(
                query=query,
                task_id=self.task_id,
                model=self.search_llm,
                agent_id=self.agent_id,
            )
            
            duration = time.time() - start_time
            
            # Build success description with token info
            success_desc = description
            if token_info:
                tokens_used = token_info.get("tokens_used", 0)
                input_tokens = token_info.get("input_tokens", 0)
                output_tokens = token_info.get("output_tokens", 0)
                success_desc = f"{description}\nTokens: In: {input_tokens}, Out: {output_tokens}, Tot: {tokens_used}"
            
            if self.tool_tracker:
                await self.tool_tracker.track_end(tool_name, duration, success=True, description=success_desc, model=self.search_llm)
            if self.tool_tracker and self.tool_tracker.orchestrator:
                self.tool_tracker.orchestrator.track_tool_usage(self.task_id, tool_name)
            
            return result if isinstance(result, str) else str(result)
        except Exception as e:
            duration = time.time() - start_time
            if self.tool_tracker:
                await self.tool_tracker.track_end(tool_name, duration, success=False, error=str(e), description=description, model=self.search_llm)
            raise


class MemoryLibrary(ToolLibraryBase):
    """
    Memory Library - Persistent memory writes for durable facts/preferences.

    `memory.save(...)` is always available in generated code:
    - If memory backend is configured: persists facts. Ensure facts are formatted in markdown.
    - If not configured: no-op with a single useful warning.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._warned_no_backend = False

    @property
    def tool_name(self) -> str:
        return "memory"

    async def save(self, content: str, desc: str = None) -> bool:
        """Save memory facts. Returns True when persisted, False when skipped/no-op."""
        import time

        text = (content or "").strip()
        if not text:
            return False

        start = time.time()
        description = desc or "Saving memory facts"

        if self.tool_tracker:
            await self.tool_tracker.track_start(self.tool_name, description)

        if not self.memory:
            if not self._warned_no_backend:
                console.warning(
                    "Memory disabled",
                    "memory.save(...) called but no Memory backend was configured. Call skipped.",
                    task_id=self.task_id,
                    agent_id=self.agent_id,
                )
                self._warned_no_backend = True

            duration = time.time() - start
            if self.tool_tracker:
                await self.tool_tracker.track_end(self.tool_name, duration, success=True, description="Skipped (no backend)")
            if self.tool_tracker and self.tool_tracker.orchestrator:
                self.tool_tracker.orchestrator.track_tool_usage(self.task_id, self.tool_name)
            return False

        try:
            self.memory.save(text)
            duration = time.time() - start
            if self.tool_tracker:
                await self.tool_tracker.track_end(self.tool_name, duration, success=True, description=description)
            if self.tool_tracker and self.tool_tracker.orchestrator:
                self.tool_tracker.orchestrator.track_tool_usage(self.task_id, self.tool_name)
            return True
        except Exception as e:
            duration = time.time() - start
            if self.tool_tracker:
                await self.tool_tracker.track_end(self.tool_name, duration, success=False, error=str(e), description="Memory save failed")
            console.warning(
                "Memory save failed",
                f"memory.save(...) was skipped: {e}",
                task_id=self.task_id,
                agent_id=self.agent_id,
            )
            return False


class LLMLibrary(ToolLibraryBase):
    """
    LLM Library - Universal AI for analysis, summarization, content generation, and structured extraction.
    
    Usage:
        from tools import llm
        
        # Analyze text
        summary = await llm.call("Summarize this sales data: " + str(data))
        
        # Generate content
        email_body = await llm.call("Write a professional email about project update")
        
        # Extract structured data
        extracted = await llm.call("From this text, extract names and emails as JSON: " + text)
        
        # Analyze files (images, documents, etc.)
        analysis = await llm.call("Describe this image", file_data=[file_content])
    """
    
    @property
    def tool_name(self) -> str:
        return "llm"
    
    def __getattr__(self, name):
        """Intercept ALL hallucinated methods (e.g. analyze_image, describe) and route to call."""
        if name in ['__class__', '__dict__', '__bases__', 'tool_name', 'tool_tracker', 'light_llm', 'heavy_llm', 'vision_llm', 'task_id', 'agent_id']:
            raise AttributeError(name)
        async def wrapper(*args, **kwargs):
            return await self.call(*args, **kwargs)
        return wrapper
        
    async def __call__(self, *args, **kwargs):
        return await self.call(*args, **kwargs)

    async def call(self, *args, prompt: str = None, desc: str = None, file_data: Optional[List[Union[str, Dict[str, Any]]]] = None, max_tokens: int = 2000, **kwargs) -> str:
        """
        Universal AI method for text analysis, file analysis, content generation, and JSON extraction.
        
        The framework automatically selects the optimal model:
        - If file_data is provided: uses vision model for accurate analysis
        - Otherwise: uses the standard AI model for text tasks
        
        Args:
            prompt: Description/instruction for what to do (text analysis, generation, etc.)
            desc: Optional description for logging (e.g., "Analyzing sales data")
            file_data: Optional list of file content (images, documents, etc.) to analyze. Can be:
                - List of dicts from filesystem.read_media_file(): [{"data": "base64_string", "mime_type": "image/jpeg"}]
            max_tokens: Maximum response length (default 2000)
        """
        # Defensive parsing against LLM hallucinating args: `llm.call(media, prompt="...")`
        
        # If args has a dict or a list that looks like file data, extract it
        if args and isinstance(args[0], (dict, list)):
            item = args[0][0] if isinstance(args[0], list) and len(args[0]) > 0 else args[0]
            if isinstance(item, dict) and ('data' in item or 'url' in item):
                if file_data is None:
                    file_data = args[0] if isinstance(args[0], list) else [args[0]]
                args = args[1:]
            
        if prompt is None and len(args) > 0:
            prompt = str(args[0])
        elif prompt is not None and len(args) > 0:
            # Reconstruct intended prompt if LLM messed up positional/kwargs
            prompt = str(prompt) + " " + str(args[0])
        elif prompt is None:
            prompt = ""
            
        # Catch common LLM hallucinated kwarg 'image'
        if file_data is None and 'image' in kwargs:
            file_data = [kwargs['image']] if not isinstance(kwargs['image'], list) else kwargs['image']
            
        # Catch common LLM hallucinated kwargs 'data' and 'mime_type' when trying to pass file data directly
        if file_data is None and 'data' in kwargs:
            mime = kwargs.get('mime_type', 'image/jpeg')
            file_data = [{"data": kwargs['data'], "mime_type": mime}]
            
        import time
        
        # Determine which LLM model will be used BEFORE tracking start (Agent shouldn't choose)
        if file_data:
            llm_model = self.vision_llm
        else:
            llm_model = self.heavy_llm
        
        # Track LLM call start
        start_time = time.time()
        # Create more informative description if none provided
        if desc:
            display_desc = desc
        else:
            # Extract first 60 chars of prompt for context
            prompt_preview = prompt[:60].replace('\n', ' ').strip()
            if len(prompt) > 60:
                prompt_preview += "..."
            display_desc = f"{prompt_preview}"
        
        if self.tool_tracker:
            ui_metadata = {
                "_tool_trace_args": {"prompt": prompt[:500] + ("..." if len(prompt) > 500 else ""), "max_tokens": max_tokens},
                "_tool_action": "call"
            }
            if desc: ui_metadata["_tool_trace_args"]["desc"] = desc
            await self.tool_tracker.track_start("llm", display_desc, model=llm_model, ui_metadata=ui_metadata)
        
        try:
            # Use internal LLM action
            from cortex._engine.internal.llm import llm_completion_async
            from cortex._engine.utils.llm_utils import normalize_llm_result
            
            llm_result = await llm_completion_async(
                model=llm_model,
                prompt=prompt,
                temperature=0.0,
                max_tokens=max_tokens,
                response_format=None,
                images=file_data
            )
            
            # Normalize result and extract tokens for logging
            response_text, norm_token_info = normalize_llm_result(llm_result)
            
            result_str = str(response_text).strip()
            
            # Track LLM call end (timing + model)
            duration = time.time() - start_time
            if self.tool_tracker:
                end_meta = {"_tool_trace_result": result_str[:500] + ("..." if len(result_str) > 500 else "")}
                await self.tool_tracker.track_end("llm", duration, success=True, model=llm_model, ui_metadata=end_meta)
            
            # Track tool usage - record that llm was used
            if self.tool_tracker and hasattr(self.tool_tracker, 'orchestrator') and self.tool_tracker.orchestrator:
                self.tool_tracker.orchestrator.track_tool_usage(self.task_id, "llm")
            
            # Track tokens and cost in orchestrator logger so they appear in summary
            orchestrator = getattr(self.tool_tracker, "orchestrator", None) if self.tool_tracker else None
            logger = getattr(orchestrator, "logger", None) if orchestrator else None
            if logger and norm_token_info:
                try:
                    logger.add_tokens(self.task_id, norm_token_info, llm_model, "llm")
                except Exception:
                    # Never break execution if token logging fails
                    pass
            
            # Return only the content to the agent, never token info
            if isinstance(response_text, str):
                return response_text.strip()
            return result_str
        except Exception as e:
            # Track LLM call failure
            duration = time.time() - start_time
            if self.tool_tracker:
                await self.tool_tracker.track_end("llm", duration, success=False, error=str(e), model=llm_model, ui_metadata={"_tool_trace_error": str(e)})
            raise
    
def _bind_arguments(fn: Any, args: tuple, kwargs: dict) -> dict:
    import inspect

    def _truncate(v: Any) -> Any:
        s = str(v)
        return (s[:500] + "...") if len(s) > 500 else v

    def _tool_from_callable(candidate: Any) -> Any:
        if type(candidate).__name__ == "Tool":
            return candidate
        bound_self = getattr(candidate, "__self__", None)
        if type(bound_self).__name__ == "Tool":
            return bound_self
        return None

    try:
        tool_obj = _tool_from_callable(fn)

        # Prefer Tool schema metadata because wrapped callables often expose only
        # generic signatures like (*args, **kwargs).
        if tool_obj and getattr(tool_obj, "parameters", None):
            param_names = list(tool_obj.parameters.keys())
            bound_args = {}
            for i, val in enumerate(args):
                if i < len(param_names) and param_names[i] not in kwargs:
                    bound_args[param_names[i]] = val
                else:
                    bound_args[f"arg_{i}"] = val
            for k, v in kwargs.items():
                bound_args[k] = v
            return {k: _truncate(v) for k, v in bound_args.items()}

        target_fn = fn
        if tool_obj and getattr(tool_obj, "_func", None):
            target_fn = tool_obj._func
        elif hasattr(fn, "_func") and getattr(fn, "_func", None):
            target_fn = fn._func
        elif hasattr(fn, "func") and getattr(fn, "func", None):
            target_fn = fn.func

        sig = inspect.signature(target_fn)
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()

        resolved = dict(bound.arguments)
        # Flatten generic wrappers that only expose args/kwargs.
        if set(resolved.keys()).issubset({"args", "kwargs"}):
            flat = {}
            for i, val in enumerate(resolved.get("args", ())):
                flat[f"arg_{i}"] = val
            flat.update(resolved.get("kwargs", {}))
            resolved = flat

        return {k: _truncate(v) for k, v in resolved.items()}
    except Exception:
        args_dict = {f"arg_{i}": val for i, val in enumerate(args)}
        args_dict.update(kwargs)
        return {k: _truncate(v) for k, v in args_dict.items()}

async def _execute_tracked_callable(
    *,
    tool_tracker: Any,
    call_name: str,
    description: str,
    callable_obj: Any,
    args: tuple,
    kwargs: dict,
    ui_metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Execute sync/async callables with consistent start/end tracking metadata."""
    import inspect
    import time

    start_time = time.time()
    await tool_tracker.track_start(call_name, description, ui_metadata=ui_metadata)
    try:
        if inspect.iscoroutinefunction(callable_obj) or (hasattr(callable_obj, "__call__") and inspect.iscoroutinefunction(callable_obj.__call__)):
            result = await callable_obj(*args, **kwargs)
        else:
            result = callable_obj(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result

        duration = time.time() - start_time
        await tool_tracker.track_end(
            call_name,
            duration,
            description=f"Executed {call_name}",
            success=True,
            ui_metadata={"_tool_trace_result": str(result)[:500]}
        )
        
        # Track tool usage - extract tool name from call_name (e.g., "filesystem.read_file" -> "filesystem")
        tool_name = call_name.split('.')[0] if '.' in call_name else call_name
        if tool_tracker and hasattr(tool_tracker, 'orchestrator') and tool_tracker.orchestrator:
            tool_tracker.orchestrator.track_tool_usage(tool_tracker.task_id, tool_name)
        
        return result
    except Exception as e:
        duration = time.time() - start_time
        await tool_tracker.track_end(
            call_name,
            duration,
            description=f"Failed: {str(e)}",
            success=False,
            error=str(e),
            ui_metadata={"_tool_trace_error": str(e)}
        )
        raise


def _wrap_for_tracking(tool_name: str, tool_obj: Any, tool_tracker: Any) -> Any:
    """Recursively wrap custom tools and MCP namespaces to enable tracing."""
    if not tool_tracker:
        return tool_obj

    # It's an MCP Tool Namespace, we need to wrap the return values of __getattr__
    if type(tool_obj).__name__ == "MCPToolNamespace":
        class MCPNamespaceTrackerProxy:
            def __init__(self, original):
                self._original = original

            def _get_mcp_tool_description(self, action_name: str) -> str:
                # Prefer local compiled namespace metadata.
                tools_dict = getattr(self._original, "_tools", {})
                tool_def = tools_dict.get(action_name)
                if tool_def is not None:
                    desc = getattr(tool_def, "description", None)
                    if isinstance(desc, str) and desc.strip():
                        return desc

                # Fallback to registry summaries.
                try:
                    from .tool_registry import TOOL_ACTION_SUMMARIES
                    summaries = TOOL_ACTION_SUMMARIES.get(tool_name, {})
                    action_key = action_name.upper().replace("-", "_")
                    return summaries.get(action_key, "")
                except Exception:
                    return ""

            def _find_connection_confirm_policy(self):
                orchestrator = getattr(tool_tracker, "orchestrator", None)
                if not orchestrator or not getattr(orchestrator, "tools", None):
                    return None, False

                connections = getattr(orchestrator.tools, "connections", {})
                for conn in connections.values():
                    if getattr(conn, "tool_name", "").lower() == str(tool_name).lower() and conn.is_active():
                        return conn, getattr(conn, "confirm", True)
                return None, True
                
            def __getattr__(self, name: str):
                if name.startswith("_"):
                    return getattr(self._original, name)
                
                # In MCPToolNamespace, __getattr__ usually returns the 'tool.execute' coroutine
                attr = getattr(self._original, name)
                if callable(attr):
                    # Wrap the function
                    async def mcp_tool_wrapper(*args, **kwargs):
                        full_name = f"{tool_name}.{name}"
                        bound_args = _bind_arguments(attr, args, kwargs)
                        ui_metadata = {"_tool_trace_args": bound_args}

                        conn, confirm_policy = self._find_connection_confirm_policy()
                        tool_description = self._get_mcp_tool_description(name)
                        await _request_unified_approval(
                            tool_tracker=tool_tracker,
                            task_id=tool_tracker.task_id,
                            tool_name=tool_name,
                            action_name=name,
                                                        confirm_policy=confirm_policy,
                            connection_name=getattr(conn, "connection_name", tool_name),
                            message=f"Approve MCP call {full_name}",
                            context_payload={
                                "classification": classify_tool(name, tool_description),
                                "args": bound_args,
                            },
                            ui_metadata={
                                "mcp_tool": tool_name,
                                "mcp_method": name,
                                "mcp_args": bound_args,
                            },
                        )

                        return await _execute_tracked_callable(
                            tool_tracker=tool_tracker,
                            call_name=full_name,
                            description=f"Executing {full_name}",
                            callable_obj=attr,
                            args=args,
                            kwargs=kwargs,
                            ui_metadata=ui_metadata,
                        )
                    return mcp_tool_wrapper
                return attr
        return MCPNamespaceTrackerProxy(tool_obj)
        
    # Standard custom tool wrapped natively via delfhos.Tool
    if type(tool_obj).__name__ == "Tool" or callable(tool_obj):
        # We need a callable proxy that wraps the call
        class CustomToolTrackerProxy:
            def __init__(self, original):
                self._original = original
                
            def __getattr__(self, name: str):
                # Fallback to original
                return getattr(self._original, name)
                
            async def __call__(self, *args, **kwargs):
                ui_metadata = {"_tool_trace_args": _bind_arguments(self._original, args, kwargs)}
                tool_confirm_policy = getattr(self._original, "confirm", None)
                description = getattr(self._original, "description", "")
                await _request_unified_approval(
                    tool_tracker=tool_tracker,
                    task_id=tool_tracker.task_id,
                    tool_name=tool_name,
                    action_name=None,
                    confirm_policy=True,
                    tool_confirm_policy=tool_confirm_policy,
                    connection_name=tool_name,
                    message=f"Approve custom tool call: {tool_name}",
                    context_payload={"args": ui_metadata["_tool_trace_args"]},
                    ui_metadata={"custom_tool_args": ui_metadata["_tool_trace_args"]},
                )
                return await _execute_tracked_callable(
                    tool_tracker=tool_tracker,
                    call_name=tool_name,
                    description=f"Executing {tool_name}",
                    callable_obj=self._original,
                    args=args,
                    kwargs=kwargs,
                    ui_metadata=ui_metadata,
                )
                    
        return CustomToolTrackerProxy(tool_obj)

    return tool_obj

def create_tool_libraries(tool_manager, task_id: str, agent_id: str, light_llm: str, heavy_llm: str,
                         tool_tracker=None, vision_llm: Optional[str] = None,
                         memory: Optional[Any] = None) -> dict:
    """
    Create all tool library instances for a task execution.
    
    Args:
        tool_tracker: Optional ToolExecutionTracker for tracking tool usage with descriptions
    
    Returns:
        Dict of tool name -> library instance
    """
    base_kwargs = {
        "tool_manager": tool_manager,
        "task_id": task_id,
        "agent_id": agent_id,
        "light_llm": light_llm,
        "heavy_llm": heavy_llm,
        "tool_tracker": tool_tracker,
        "vision_llm": vision_llm,
        "memory": memory,
    }
    
    libraries = {}
    
    # Check which tools are available:
    # 1. From tool_manager.tools (direct tool functions)
    # 2. From tool_manager.connection_to_tool (connections that provide tools)
    available_tools = set(tool_manager.tools.keys())
    
    # Add tool names from connections
    if hasattr(tool_manager, 'connection_to_tool'):
        for connection_name, tool_name in tool_manager.connection_to_tool.items():
            if tool_name:
                available_tools.add(tool_name.lower())

    connection_libraries = {
        "sql": SQLLibrary,
        "sheets": SheetsLibrary,
        "gmail": GmailLibrary,
        "drive": DriveLibrary,
        "docs": DocsLibrary,
        "calendar": CalendarLibrary,
    }
    for tool_name, lib_cls in connection_libraries.items():
        if tool_name in available_tools:
            libraries[tool_name] = lib_cls(**base_kwargs)

    always_available_libraries = {
        "llm": LLMLibrary,
        "files": FilesLibrary,
        "websearch": WebSearchLibrary,
        "memory": MemoryLibrary,
    }
    for tool_name, lib_cls in always_available_libraries.items():
        libraries[tool_name] = lib_cls(**base_kwargs)
    
    # Pass through any other tools registered in ToolContainer directly
    # This allows MCP namespaces and user-defined @tool functions to be used natively
    for tool_name, tool_func in tool_manager.tools.items():
        if tool_name not in libraries:
            libraries[tool_name] = _wrap_for_tracking(tool_name, tool_func, tool_tracker)
            
    return libraries


class FilesLibrary(ToolLibraryBase):
    """
    Files library for working with uploaded files.
    Provides intelligent parsing and analysis.
    """
    
    @property
    def tool_name(self) -> str:
        return "files"
    
    async def list(self, desc: str = None) -> List[Dict[str, Any]]:
        """List all files uploaded for this task."""
        from .files import load_task_files
        
        file_handlers = await load_task_files(self.task_id)
        return [f.to_dict() for f in file_handlers]
    
    async def read(self, filename: str, desc: str = None, for_llm: bool = False) -> Union[str, List[Dict], Dict]:
        """
        Read and intelligently parse a file.
        Auto-detects type and returns appropriate structure.
        
        Args:
            filename: Name of the file to read, or full path (e.g., "file.csv" or "uploads/task_id/output/file.csv")
            desc: Optional description for UI tracking
            for_llm: If True and file is an image, returns dict format compatible with LLMs
                     If False, returns base64 string (backward compatible)
        
        Returns:
            - CSV: List[Dict]
            - JSON: Dict or List
            - Excel: List[Dict]
            - Text/Markdown: str
            - PDF: str (extracted text)
            - Image: base64 string (if for_llm=False) or dict with data/mime_type (if for_llm=True)
        """
        from .files import load_task_files
        from pathlib import Path as PathLib
        
        # If filename is a full path, extract just the filename
        if "/" in filename or "\\" in filename:
            # It's a path, extract the filename
            path_obj = PathLib(filename)
            filename = path_obj.name
        
        file_handlers = await load_task_files(self.task_id)
        
        # Find file by name
        handler = None
        for fh in file_handlers:
            if fh.file_path.name == filename or fh.file_path.stem == Path(filename).stem:
                handler = fh
                break
        
        if not handler:
            raise FileNotFoundError(f"File not found: {filename}")
        
        # Auto-parse based on type
        if handler.file_type == 'csv':
            return handler.read_csv()
        elif handler.file_type == 'json':
            return handler.read_json()
        elif handler.file_type == 'excel':
            return handler.read_excel()
        elif handler.file_type == 'text' or handler.file_type == 'markdown':
            return handler.read_text()
        elif handler.file_type == 'pdf':
            return handler.read_pdf_text()
        elif handler.file_type == 'image':
            # Return format compatible with LLMs
            base64_data = handler.read_image_base64()
            
            if for_llm:
                # Determine MIME type from file extension
                mime_type_map = {
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.png': 'image/png',
                    '.gif': 'image/gif',
                    '.webp': 'image/webp',
                    '.svg': 'image/svg+xml',
                }
                ext = handler.file_path.suffix.lower()
                mime_type = mime_type_map.get(ext, 'image/png')
                
                # Return dict format compatible with Gemini
                return {
                    "type": "image",
                    "data": base64_data,
                    "mime_type": mime_type,
                    "filename": handler.file_path.name
                }
            else:
                # Backward compatible: return base64 string
                return base64_data
        else:
            return handler.read_text()
    
    async def save(self, filename: str, content: Union[str, bytes, List[Dict], Dict], desc: str = None) -> str:
        """
        Save output file. Auto-converts data structures to appropriate format (requires approval).
        
        Args:
            filename: Name of the file to save (e.g., "output.csv", "data.json")
            content: Content to save - can be:
                - str: Raw string content (e.g., CSV string from sql.query(as_csv=True))
                - bytes: Binary content
                - List[Dict]: List of dictionaries (auto-converted to CSV)
                - Dict: Dictionary (auto-converted to JSON)
            desc: Optional description for UI tracking
        
        Returns:
            str: File path of the saved file (usable in gmail.send attachments)
        """
        from .files import save_output_file
        from pathlib import Path as PathLib
        import json
        from delfhos.errors import ToolExecutionError, ConnectionConfigurationError
        import csv
        import io
        
        # Auto-convert data to appropriate format
        if isinstance(content, list) and len(content) > 0 and isinstance(content[0], dict):
            # List of dicts -> CSV
            if not filename.endswith('.csv'):
                filename = f"{PathLib(filename).stem}.csv"
            
            output = io.StringIO()
            if content:
                writer = csv.DictWriter(output, fieldnames=content[0].keys())
                writer.writeheader()
                writer.writerows(content)
                content = output.getvalue()
        elif isinstance(content, dict):
            # Dict -> JSON
            if not filename.endswith('.json'):
                filename = f"{PathLib(filename).stem}.json"
            content = json.dumps(content, indent=2, ensure_ascii=False)
        elif isinstance(content, (list, tuple)) and not isinstance(content, bytes):
            # List -> JSON
            if not filename.endswith('.json'):
                filename = f"{PathLib(filename).stem}.json"
            content = json.dumps(content, indent=2, ensure_ascii=False)
        # If content is already str or bytes, use it as-is
        
        # Calculate file size
        if isinstance(content, str):
            size_bytes = len(content.encode('utf-8'))
        elif isinstance(content, bytes):
            size_bytes = len(content)
        else:
            size_bytes = 0
        size_display = _format_size_display(size_bytes)
        preview_metadata = _build_file_preview_metadata(content, filename)

        await _request_unified_approval(
            tool_tracker=self.tool_tracker,
            task_id=self.task_id,
            tool_name="files",
            action_name="save",
            confirm_policy="write",
            connection_name="files",
            message=desc or f"Approve saving file: {filename}",
            context_payload={
                "filename": filename,
                "size_bytes": size_bytes,
                "can_preview": preview_metadata["can_preview"],
            },
            ui_metadata={
                "filename": filename,
                "size_bytes": size_bytes,
                "size_display": size_display,
                "preview_content": preview_metadata["preview_content"],
                "preview_table_data": preview_metadata["preview_table_data"],
                "is_table_format": preview_metadata["is_table_format"],
                "can_preview": preview_metadata["can_preview"],
            },
        )
        
        file_path = await save_output_file(self.task_id, filename, content, self.agent_id)
        return file_path


