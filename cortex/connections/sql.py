"""
SQLConnection — Authenticated link to a SQL database.

Currently supports: PostgreSQL, MySQL, MariaDB

Supported actions: "schema", "query"

Example (URL):
    db = SQLConnection(url="postgresql://user:password@host:5432/mydb")

Example (parameters):
    db = SQLConnection(
        host="db.example.supabase.co",
        port=5432,
        database="postgres",
        user="postgres",
        password="my-secret-password",
    )
"""

from typing import List, Optional, Dict, Any, Union
from cortex._engine.connection import AuthType
from .base import BaseConnection
from delfhos.errors import ConnectionConfigurationError


class SQLConnection(BaseConnection):
    """
    SQL database connection.

    Auth methods (use one):
        url:        Full connection string, e.g. "postgresql://user:pass@host/db"
        host+user:  Individual parameters (host, port, database, user, password)

    Args:
        url:       Database connection string.
        host:      Database hostname or IP.
        port:      Database port (default: 5432 for PostgreSQL, 3306 for MySQL).
        database:  Database name.
        user:      Database username.
        password:  Database password.
        db_type:   "postgresql" or "mysql" (default: "postgresql"). Only needed with params.
        actions:   ["schema", "query"] — which operations are allowed.
        name:      Label for this connection (default: "sql").
        metadata:  Extra info, e.g. {"description": "Read-only analytics DB"}.
    """

    TOOL_NAME = "sql"
    ALLOWED_ACTIONS = ["schema", "query", "write"]

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        db_type: str = "postgresql",
        allowed: Optional[Union[str, List[str]]] = None,
        name: str = "sql",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        if url:
            credentials = {"url": url}
        elif host:
            # Build credentials from individual parameters
            db_type_lower = db_type.lower()
            if db_type_lower not in ("postgresql", "postgres", "mysql", "mariadb"):
                raise ConnectionConfigurationError(
                    tool_name="SQLConnection",
                    detail=f"Unsupported db_type '{db_type}'. Use 'postgresql', 'mysql', or 'mariadb'."
                )
            default_port = 5432 if db_type_lower in ("postgresql", "postgres") else 3306

            credentials = {
                "host": host,
                "port": port or default_port,
                "database": database or "",
                "user": user or "",
                "password": password or "",
                "db_type": db_type_lower,
            }
        else:
            raise ConnectionConfigurationError(
                tool_name="SQLConnection",
                detail="Requires either: url='postgresql://user:pass@host/db' OR host='...', database='...', user='...', password='...'"
            )

        super().__init__(
            credentials=credentials,
            allowed=allowed,
            name=name,
            auth_type=AuthType.BASIC_AUTH,
            metadata=metadata,
        )
