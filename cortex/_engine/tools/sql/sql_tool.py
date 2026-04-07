from __future__ import annotations

from typing import Any, Dict, Optional
from delfhos.errors import ToolExecutionError, ConnectionConfigurationError

from ...utils.console import console
from .sql_client import SQLClient, SQLClientError

async def sql_tool(
    user_input: Any = "",
    action: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
    light_llm: Optional[str] = None,  # unused, kept for signature compatibility
    heavy_llm: Optional[str] = None,  # unused, kept for signature compatibility
    agent_id: Optional[str] = None,
    validation_mode: bool = False,
    credentials: Optional[Dict[str, Any]] = None,
    connection: Optional[Any] = None,
    **kwargs: Any,
):
    """
    SQL tool - unified DSL wrapper for PostgreSQL and MySQL/MariaDB.

    - Uses a *connection URL* stored in the connection credentials (credentials.url).
    - Supports two main actions:
        - SCHEMA: inspect database structure (tables/columns, PK/FK) and return a compact string.
        - QUERY: execute an SQL query and return rows as a list of objects.

    The agent is expected to:
      1) Call sql(action:"SCHEMA") first to understand the structure.
      2) Use LLM to generate a precise SQL query from the schema + user request.
      3) Call sql(action:"QUERY", params:{sql:"SELECT ..."}) to fetch the results.
    """
    context = user_input if isinstance(user_input, dict) else {}
    action = (action or context.get("action") or "").upper()
    params = params or context.get("params") or {}

    if not action:
        raise ToolExecutionError(tool_name="sql", detail="SQL tool requires an action (SCHEMA, QUERY).")

    # [SANDBOX INTERCEPTOR]
    if connection and getattr(connection, "is_sandbox", False):
        if action == "SCHEMA":
            schema = connection.get_mock_schema()
            return {
                "message": "Database schema retrieved successfully.",
                "schema": schema,
                "db_type": "sqlite",
                "database": "sandbox",
            }
        elif action in ["QUERY", "EXECUTE"]:
            sql_text = params.get("sql") or params.get("query")
            if not sql_text or not isinstance(sql_text, str):
                raise ToolExecutionError(tool_name="sql", detail="sql QUERY requires params.sql (SQL query string).")
            
            rows = connection.execute_mock_query(sql_text)
            return {
                "message": f"Sandbox query executed successfully.",
                "rows": rows if isinstance(rows, list) else [],
                "row_count": len(rows) if isinstance(rows, list) else rows,
                "db_type": "sqlite",
                "database": "sandbox",
                "read_only": action == "QUERY",
            }

    # Resolve connection credentials
    creds: Optional[Dict[str, Any]] = None
    if credentials and isinstance(credentials, dict):
        creds = credentials
    if not creds and connection is not None:
        try:
            creds_payload = connection.get_credentials()
            if isinstance(creds_payload, dict):
                creds = creds_payload
        except Exception:
            creds = None

    if not creds:
        raise ConnectionConfigurationError(
            tool_name="sql", detail="SQL connection credentials not found. Provide a url or host/database/user/password parameters."
        )

    # Determine if we have a URL or individual params
    url = (
        creds.get("url")
        or creds.get("connection_url")
        or creds.get("connectionUrl")
    )

    if url:
        client = SQLClient(url)
    elif creds.get("host"):
        # Individual params — pass the dict directly
        client = SQLClient(creds)
    else:
        raise ConnectionConfigurationError(
            tool_name="sql", detail="SQL connection requires either a 'url' or 'host' in credentials. Example: SQLConnection(url='postgresql://...') or SQLConnection(host='...', database='...', user='...', password='...')"
        )

    import asyncio

    if action == "SCHEMA":
        try:
            schema = await asyncio.to_thread(client.get_schema)

            return {
                "message": "Database schema retrieved successfully.",
                "schema": schema,
                "db_type": client.parsed.db_type,
                "database": client.parsed.database,
            }
        except SQLClientError as exc:
            console.error(
                "[SQL ERROR] Failed to retrieve schema",
                details=str(exc),
                task_id=task_id,
                agent_id=agent_id,
            )
            raise

    if action == "QUERY":
        sql_text = params.get("sql") or params.get("query")
        if not sql_text or not isinstance(sql_text, str):
            raise ToolExecutionError(tool_name="sql", detail="sql QUERY requires params.sql (SQL query string).")

        # Optional format hint: as_csv true → return CSV string for easy ingestion by other tools (e.g. sheets)
        as_csv = bool(params.get("as_csv"))

        # Force read-only mode: only allow SELECT / safe queries
        try:
            message, rows = await asyncio.to_thread(client.execute_query, sql_text, True)


            if as_csv:
                # Convert rows (list of dicts) to CSV string: header row + data rows
                import csv
                from io import StringIO

                output = StringIO()
                if rows:
                    # Collect all keys from first row as header
                    header = list(rows[0].keys())
                    writer = csv.writer(output)
                    writer.writerow(header)
                    for row in rows:
                        writer.writerow([row.get(col) for col in header])
                csv_data = output.getvalue()
                output.close()
                return csv_data

            return {
                "message": message,
                "rows": rows,
                "row_count": len(rows),
                "db_type": client.parsed.db_type,
                "database": client.parsed.database,
                "read_only": True,
            }
        except SQLClientError as exc:
            console.error(
                "[SQL ERROR] Query failed",
                details=str(exc),
                task_id=task_id,
                agent_id=agent_id,
            )
            raise

    if action == "EXECUTE":
        sql_text = params.get("sql") or params.get("query")
        if not sql_text or not isinstance(sql_text, str):
            raise ToolExecutionError(tool_name="sql", detail="sql EXECUTE requires params.sql (SQL query string).")

        # Execute write operations (UPDATE, INSERT, DELETE, etc.) - NO read-only restriction
        try:
            message, rows = await asyncio.to_thread(client.execute_query, sql_text, False)
            return {
                "message": message,
                "rows": rows if rows else [],
                "row_count": len(rows) if rows else 0,
                "db_type": client.parsed.db_type,
                "database": client.parsed.database,
                "read_only": False,
            }
        except SQLClientError as exc:
            console.error(
                "[SQL ERROR] Write operation failed",
                details=str(exc),
                task_id=task_id,
                agent_id=agent_id,
            )
            raise

            raise ToolExecutionError(tool_name="sql", detail=f"Unsupported SQL tool action '{action}'.\n\n📋 Available SQL actions:\n    • SCHEMA - Get database schema information\n    • QUERY - Execute a SELECT query\n    • EXECUTE - Execute INSERT/UPDATE/DELETE operations\n\nUse one of these actions in your next request.")


