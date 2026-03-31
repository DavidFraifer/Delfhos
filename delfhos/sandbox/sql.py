import sqlite3
import json
from cortex.connections.sql import SQLConnection

def _init_mock_db(conn):
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT,
            email TEXT,
            status TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            amount DECIMAL(10,2),
            product TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE tickets (
            ticket_id TEXT PRIMARY KEY,
            user_id INTEGER,
            subject TEXT,
            status TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    
    # Insert Mock Data
    users = [
        (1, 'Alice Smith', 'alice@example.com', 'active'),
        (2, 'Bob Jones', 'bob@example.com', 'inactive'),
        (3, 'Charlie Brown', 'charlie@example.com', 'active')
    ]
    cursor.executemany('INSERT INTO users VALUES (?,?,?,?)', users)

    orders = [
        (101, 1, 1250.00, 'Enterprise License'),
        (102, 1, 45.50, 'Support Add-on'),
        (103, 3, 99.00, 'Pro License')
    ]
    cursor.executemany('INSERT INTO orders VALUES (?,?,?,?)', orders)

    tickets = [
        ('TCK8843', 1, 'Invoice Overdue from Acme Corp?', 'open'),
        ('TCK-9921', 2, 'Cannot login', 'closed'),
        ('TCK-9950', 3, 'Upgrade request', 'open')
    ]
    cursor.executemany('INSERT INTO tickets VALUES (?,?,?,?)', tickets)
    
    conn.commit()


class MockDatabase(SQLConnection):
    """
    In-memory SQLite database pre-populated with dummy enterprise data.
    Requires ZERO configuration. Perfect for testing and tutorials.
    """
    
    TOOL_NAME = "sql"
    ALLOWED_ACTIONS = ["schema", "query", "write"]

    @classmethod
    def inspect(cls, verbose: bool = False) -> dict:
        """Inspect available mock SQL actions without creating an instance."""
        return super().inspect(verbose=verbose)
    
    def __init__(self, name: str = "db", allow=None, confirm=True):
        # We don't need real credentials, but the base class expects something
        super().__init__(
            host="sandbox-memory-db",
            database="sandbox",
            user="sandbox",
            password="pwd",
            name=name,
            allow=allow,
            confirm=confirm,
        )
        # Mark this as a sandbox connection so the internal tool knows to intercept
        self.is_sandbox = True
        
        # Maintain a persistent in-memory connection
        self._sqlite_conn = sqlite3.connect('file::memory:?cache=shared', uri=True, check_same_thread=False)
        self._sqlite_conn.row_factory = sqlite3.Row
        _init_mock_db(self._sqlite_conn)

    def execute_mock_query(self, query: str):
        cursor = self._sqlite_conn.cursor()
        cursor.execute(query)
        if query.strip().upper().startswith("SELECT"):
            columns = [column[0] for column in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            return results
        else:
            self._sqlite_conn.commit()
            return cursor.rowcount
            
    def get_mock_schema(self) -> str:
        return (
            "users: id(INTEGER)[PK], name(TEXT), email(TEXT), status(TEXT)\\n"
            "orders: id(INTEGER)[PK], user_id(INTEGER)[FK], amount(DECIMAL), product(TEXT)\\n"
            "tickets: ticket_id(TEXT)[PK], user_id(INTEGER)[FK], subject(TEXT), status(TEXT)"
        )
