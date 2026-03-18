import os
import re
import sqlite3
from typing import List, Dict, Optional, Union, Iterator
import threading
from datetime import datetime

from .types import Message


class Chat:
    """
    Session memory for an Agent — keeps recent conversation history and auto-summarizes.
    
    The agent appends messages to this Chat. Once the message count exceeds `keep`,
    the oldest messages are summarized asynchronously and removed.
    
    Example:
        chat = Chat()  # Auto-summarizes old messages, keeps last 10
        agent = Agent(tools=[Gmail()], chat=chat, llm="gemini-3.1-flash-lite-preview")
        # Agent remembers last 10 messages + a summary of older ones
    
    Args:
        keep: Max messages to retain before summarizing (default: 10). 0 = summarize all.
        summarize: If True (default), compress old messages into a summary. If False, just truncate.
        persist: If False (default), keep chat only in memory for this run.
                 If True, persist chat state in SQLite.
        path: SQLite file path for persisted chat state (used only when persist=True).
              If omitted, defaults to ~/delfhos/chat/<namespace>.db.
        namespace: Namespace key to isolate multiple chats in the same DB.
    """
    def __init__(
        self,
        keep: int = 10,
        summarize: bool = True,
        persist: bool = False,
        path: Optional[str] = None,
        namespace: str = "default",
    ):
        self.keep = keep
        self.summarize = summarize
        self.persist = persist
        self.namespace = namespace
        self.path = os.path.expanduser(path) if path else self._default_path_for_namespace(namespace)
        self._messages: List[Message] = []
        self._summary: str = ""
        self._lock = threading.Lock()

        if self.persist:
            self._init_db()
            self._load_state()

    @staticmethod
    def _sanitize_namespace(namespace: str) -> str:
        raw = (namespace or "default").strip()
        if not raw:
            raw = "default"
        # Keep filenames portable and predictable across platforms.
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw)
        return safe or "default"

    @classmethod
    def _default_path_for_namespace(cls, namespace: str) -> str:
        filename = f"{cls._sanitize_namespace(namespace)}.db"
        return os.path.expanduser(os.path.join("~", "delfhos", "chat", filename))

    def _init_db(self):
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    namespace TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_state (
                    namespace TEXT PRIMARY KEY,
                    summary TEXT NOT NULL DEFAULT '',
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_ns ON chat_messages(namespace)")

    def _load_state(self):
        with sqlite3.connect(self.path) as conn:
            # Added created_at column to support Message timestamp reading
            rows = conn.execute(
                "SELECT role, content, created_at FROM chat_messages WHERE namespace = ? ORDER BY id ASC",
                (self.namespace,),
            ).fetchall()

            summary_row = conn.execute(
                "SELECT summary, updated_at FROM chat_state WHERE namespace = ?",
                (self.namespace,),
            ).fetchone()

        # Parse string datetime back to python datetime if available
        def _parse_ts(ts_str):
            if not ts_str: return datetime.now()
            try:
                # Basic standard format for SQLite current_timestamp: YYYY-MM-DD HH:MM:SS
                return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return datetime.now()

        self._messages = [
            Message(
                role=r[0], 
                content=r[1], 
                timestamp=_parse_ts(r[2]), 
                namespace=self.namespace,
                is_summary=False
            ) for r in rows
        ]
        
        self._summary = summary_row[0] if summary_row and summary_row[0] else ""

    def _persist_message(self, role: str, content: str):
        if not self.persist:
            return
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT INTO chat_messages (namespace, role, content) VALUES (?, ?, ?)",
                (self.namespace, role, content),
            )

    def _persist_summary(self, summary: str):
        if not self.persist:
            return
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO chat_state (namespace, summary)
                VALUES (?, ?)
                ON CONFLICT(namespace) DO UPDATE SET
                    summary = excluded.summary,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (self.namespace, summary),
            )

    def _delete_oldest_messages(self, count: int):
        if count <= 0 or not self.persist:
            return
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                DELETE FROM chat_messages
                WHERE id IN (
                    SELECT id FROM chat_messages
                    WHERE namespace = ?
                    ORDER BY id ASC
                    LIMIT ?
                )
                """,
                (self.namespace, count),
            )
        
    def append(self, role: str, content: str):
        """Add a message to the conversation history."""
        with self._lock:
            msg = Message(
                role=role, 
                content=content, 
                timestamp=datetime.now(), 
                namespace=self.namespace, 
                is_summary=False
            )
            self._messages.append(msg)
            self._persist_message(role, content)
        
    def clear(self):
        """Remove all messages and summaries. Use before starting a new conversation."""
        with self._lock:
            self._messages.clear()
            self._summary = ""
            if self.persist:
                with sqlite3.connect(self.path) as conn:
                    conn.execute("DELETE FROM chat_messages WHERE namespace = ?", (self.namespace,))
                    conn.execute("DELETE FROM chat_state WHERE namespace = ?", (self.namespace,))
        
    def needs_compression(self) -> bool:
        """Check if message count exceeds the `keep` threshold and should be summarized.
        
        Usually called internally by the agent — not for manual use.
        
        Returns:
            True if compression (summarization) should run, False otherwise.
        """
        # If keeping 0, compress immediately
        if self.keep == 0 and self.summarize:
            return len(self._messages) > 0
            
        return len(self._messages) > self.keep
        
    def get_messages_for_compression(self) -> List[Dict[str, str]]:
        """Return a snapshot of all current messages for safe async summarization.
        
        Used internally — developers don't call this directly.
        """
        with self._lock:
            return [{"role": m.role, "content": m.content} for m in self._messages]
        
    def apply_compression(self, new_summary: str, compressed_count: int):
        """Apply the summarized version and discard old messages safely.
        
        Called internally after async summarization completes. Handles race conditions
        where new messages arrived during summarization.
        
        Args:
            new_summary: The AI-generated summary of old messages.
            compressed_count: How many original messages were summarized.
        """
        with self._lock:
            if new_summary:
                self._summary = new_summary
                self._persist_summary(new_summary)
                
            # Only remove the number of messages that were actually compressed,
            # leaving any brand new messages that arrived during generation intact.
            if compressed_count > 0 and len(self._messages) >= compressed_count:
                if self.keep > 0:
                    # E.g. compressed 12 messages, keep is 10. we discard the first 2.
                    # However we want to discard exactly (compressed_count - keep)
                    discard_count = compressed_count - self.keep
                    if discard_count > 0:
                        self._messages = self._messages[discard_count:]
                        self._delete_oldest_messages(discard_count)
                else:
                    self._messages = self._messages[compressed_count:]
                    self._delete_oldest_messages(compressed_count)

    # ------------------------------------------------------------------
    # Pythonic API
    # ------------------------------------------------------------------

    @property
    def messages(self) -> List[Dict[str, str]]:
        # Provided strictly for backward compatibility for internal consumers
        return [{"role": m.role, "content": m.content} for m in self._messages]
        
    @property
    def summary(self) -> Optional[str]:
        return self._summary if self._summary else None

    def by_role(self, role: str) -> List[Message]:
        return [m for m in self._messages if m.role == role]

    def __iter__(self) -> Iterator[Message]:
        return iter(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def __getitem__(self, key: Union[int, slice]) -> Union[Message, List[Message]]:
        return self._messages[key]

    def __str__(self) -> str:
        count = len(self._messages)
        sum_str = "yes" if self._summary else "no"
        title = f"Chat — {count} messages (summary: {sum_str})"
        
        lines = [title, "─" * 42]
        
        if self._summary:
            import textwrap
            wrapped = textwrap.fill(self._summary, width=60, subsequent_indent="          ")
            lines.append(f"[summary] {wrapped}\n")
            
        for i, msg in enumerate(self._messages, 1):
            # Shorten output content slightly for aesthetics
            val = msg.content
            if len(val) > 60:
                val = val[:57] + "..."
            # Format role column nicely
            role_fmt = f"{msg.role:<10}"
            lines.append(f"[{i}] {role_fmt} {val}")
            
        lines.append("─" * 42)
        return "\n".join(lines)


