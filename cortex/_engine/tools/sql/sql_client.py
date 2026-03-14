from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse, unquote

import psycopg2
import mysql.connector
from delfhos.errors import ToolExecutionError


class SQLClientError(ToolExecutionError):
    """Base error for SQL client operations."""

    def __init__(self, message: str):
        super().__init__(tool_name="sql", detail=message)


@dataclass
class ParsedURL:
    db_type: str
    host: str
    port: int
    database: str
    user: str | None
    password: str | None


def _parse_db_url(url: str) -> ParsedURL:
    """
    Parse a database connection URL into components.

    Supported schemes:
      - postgresql://user:pass@host:5432/dbname
      - postgres://user:pass@host:5432/dbname
      - mysql://user:pass@host:3306/dbname
      - mariadb://user:pass@host:3306/dbname
    """
    if not url or not isinstance(url, str):
        raise SQLClientError("Database URL is required and must be a string.")

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()

    if scheme in ("postgresql", "postgres"):
        db_type = "postgresql"
        default_port = 5432
    elif scheme in ("mysql", "mariadb"):
        db_type = "mysql" if scheme == "mysql" else "mariadb"
        default_port = 3306
    else:
        raise SQLClientError(
            f"Unsupported database URL scheme '{scheme}'. "
            "Use postgresql:// or mysql:// / mariadb://"
        )

    host = parsed.hostname or "localhost"
    port = parsed.port or default_port
    database = (parsed.path or "").lstrip("/") or ""
    user = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None

    if not database:
        raise SQLClientError("Database name is missing in URL path.")

    return ParsedURL(
        db_type=db_type,
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
    )


class SQLClient:
    """Lightweight SQL client for Postgres and MySQL/MariaDB.
    
    Accepts either a connection URL string or a dict of individual params.
    """

    def __init__(self, url_or_params):
        """
        Args:
            url_or_params: Either a URL string (e.g. "postgresql://user:pass@host/db")
                          or a dict with keys: host, port, database, user, password, db_type
        """
        if isinstance(url_or_params, str):
            self.url = url_or_params
            self.parsed = _parse_db_url(url_or_params)
        elif isinstance(url_or_params, dict):
            self.url = None
            db_type = url_or_params.get("db_type", "postgresql").lower()
            if db_type in ("postgresql", "postgres"):
                db_type = "postgresql"
            elif db_type not in ("mysql", "mariadb"):
                raise SQLClientError(f"Unsupported db_type '{db_type}'.")
            default_port = 5432 if db_type == "postgresql" else 3306
            self.parsed = ParsedURL(
                db_type=db_type,
                host=url_or_params.get("host", "localhost"),
                port=int(url_or_params.get("port", default_port)),
                database=url_or_params.get("database", ""),
                user=url_or_params.get("user"),
                password=url_or_params.get("password"),
            )
            if not self.parsed.database:
                raise SQLClientError("Database name is required.")
        else:
            raise SQLClientError("SQLClient requires a URL string or a params dict.")

    # === Public API ===

    def get_schema(self) -> str:
        """
        Return a compact schema description string.

        Format (per table):
          TABLE table_name: col1(type)[PK][FK], col2(type), ...
        """
        if self.parsed.db_type == "postgresql":
            return self._get_postgres_schema()
        elif self.parsed.db_type in ("mysql", "mariadb"):
            return self._get_mysql_schema()
        raise SQLClientError(f"Unsupported db_type '{self.parsed.db_type}' for schema.")

    def execute_query(self, query: str, read_only: bool = True) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Execute SQL query and return (message, rows).

        If read_only=True, simple protection against obvious write operations is applied.
        """
        if not query or not isinstance(query, str):
            raise SQLClientError("SQL query must be a non-empty string.")

        if read_only and not _is_read_only_query(query):
            raise SQLClientError(
                "This SQL tool is in read-only mode. "
                "Only SELECT-like queries are allowed."
            )

        if self.parsed.db_type == "postgresql":
            return self._execute_postgres(query)
        elif self.parsed.db_type in ("mysql", "mariadb"):
            return self._execute_mysql(query)

        raise SQLClientError(f"Unsupported db_type '{self.parsed.db_type}' for execution.")

    # === Internal helpers ===

    def _get_postgres_schema(self) -> str:
        conn = None
        cursor = None
        try:
            conn = psycopg2.connect(
                host=self.parsed.host,
                port=self.parsed.port,
                database=self.parsed.database,
                user=self.parsed.user,
                password=self.parsed.password,
            )
            cursor = conn.cursor()
            query = """
                SELECT 
                    t.table_name,
                    c.column_name,
                    c.data_type,
                    CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END as is_pk,
                    CASE WHEN fk.column_name IS NOT NULL THEN true ELSE false END as is_fk
                FROM information_schema.tables t
                JOIN information_schema.columns c 
                    ON t.table_name = c.table_name 
                    AND t.table_schema = c.table_schema
                LEFT JOIN (
                    SELECT kcu.table_name, kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu 
                        ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.constraint_type = 'PRIMARY KEY' 
                      AND tc.table_schema = 'public'
                ) pk ON t.table_name = pk.table_name AND c.column_name = pk.column_name
                LEFT JOIN (
                    SELECT kcu.table_name, kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu 
                        ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.constraint_type = 'FOREIGN KEY' 
                      AND tc.table_schema = 'public'
                ) fk ON t.table_name = fk.table_name AND c.column_name = fk.column_name
                WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
                ORDER BY t.table_name, c.ordinal_position;
            """
            cursor.execute(query)
            rows = cursor.fetchall()

            tables: Dict[str, List[str]] = {}
            for table_name, col_name, data_type, is_pk, is_fk in rows:
                if table_name not in tables:
                    tables[table_name] = []
                col_str = f"{col_name}({data_type})"
                if is_pk:
                    col_str += "[PK]"
                if is_fk:
                    col_str += "[FK]"
                tables[table_name].append(col_str)

            parts = []
            for table_name, columns in tables.items():
                parts.append(f"{table_name}: {', '.join(columns)}")
            return "\n".join(parts)
        except Exception as exc:
            raise SQLClientError(f"Error retrieving PostgreSQL schema: {exc}") from exc
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _get_mysql_schema(self) -> str:
        conn = None
        cursor = None
        try:
            conn = mysql.connector.connect(
                host=self.parsed.host,
                port=self.parsed.port,
                database=self.parsed.database,
                user=self.parsed.user,
                password=self.parsed.password,
                charset="utf8mb4",
                collation="utf8mb4_general_ci",
            )
            cursor = conn.cursor()
            query = """
                SELECT 
                    c.TABLE_NAME,
                    c.COLUMN_NAME,
                    c.DATA_TYPE,
                    CASE WHEN c.COLUMN_KEY = 'PRI' THEN true ELSE false END as is_pk,
                    CASE WHEN c.COLUMN_KEY = 'MUL' THEN true ELSE false END as is_fk
                FROM information_schema.COLUMNS c
                JOIN information_schema.TABLES t 
                    ON c.TABLE_NAME = t.TABLE_NAME 
                    AND c.TABLE_SCHEMA = t.TABLE_SCHEMA
                WHERE c.TABLE_SCHEMA NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
                    AND t.TABLE_TYPE = 'BASE TABLE'
                ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION;
            """
            cursor.execute(query)
            rows = cursor.fetchall()

            tables: Dict[str, List[str]] = {}
            for table_name, col_name, data_type, is_pk, is_fk in rows:
                if table_name not in tables:
                    tables[table_name] = []
                col_str = f"{col_name}({data_type})"
                if is_pk:
                    col_str += "[PK]"
                if is_fk:
                    col_str += "[FK]"
                tables[table_name].append(col_str)

            parts = []
            for table_name, columns in tables.items():
                parts.append(f"{table_name}: {', '.join(columns)}")
            return "\n".join(parts)
        except Exception as exc:
            raise SQLClientError(f"Error retrieving MySQL/MariaDB schema: {exc}") from exc
        finally:
            if cursor:
                cursor.close()
            if conn and hasattr(conn, "close"):
                conn.close()

    def _execute_postgres(self, query: str) -> Tuple[str, List[Dict[str, Any]]]:
        conn = None
        cursor = None
        try:
            conn = psycopg2.connect(
                host=self.parsed.host,
                port=self.parsed.port,
                database=self.parsed.database,
                user=self.parsed.user,
                password=self.parsed.password,
            )
            cursor = conn.cursor()
            cursor.execute(query)

            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                data: List[Dict[str, Any]] = []
                for row in rows:
                    data.append({columns[i]: value for i, value in enumerate(row)})
                return f"Query executed successfully. {len(data)} rows returned.", data
            else:
                conn.commit()
                return "Query executed successfully (no data returned by this query type).", []
        except Exception as exc:
            raise SQLClientError(f"PostgreSQL query error: {exc}") from exc
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _execute_mysql(self, query: str) -> Tuple[str, List[Dict[str, Any]]]:
        conn = None
        cursor = None
        try:
            conn = mysql.connector.connect(
                host=self.parsed.host,
                port=self.parsed.port,
                database=self.parsed.database,
                user=self.parsed.user,
                password=self.parsed.password,
                charset="utf8mb4",
                collation="utf8mb4_general_ci",
            )
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query)

            if cursor.description:
                data = cursor.fetchall()
                return f"Query executed successfully. {len(data)} rows returned.", data
            else:
                conn.commit()
                return "Query executed successfully (no data returned by this query type).", []
        except Exception as exc:
            raise SQLClientError(f"MySQL/MariaDB query error: {exc}") from exc
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()


def _is_read_only_query(query: str) -> bool:
    """Very simple check to block obviously destructive queries."""
    q = " ".join((query or "").strip().lower().split())
    if not q:
        return False
    write_commands = [
        "insert",
        "update",
        "delete",
        "drop",
        "create",
        "alter",
        "truncate",
        "replace",
        "merge",
    ]
    for cmd in write_commands:
        if q.startswith(cmd):
            return False
    return True


