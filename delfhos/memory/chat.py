import os
import re
import sqlite3
from typing import List, Dict, Optional
import threading


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
          path: SQLite file path for persisted chat state.
              If omitted, defaults to ~/delfhos/chat/<namespace>.db.
        namespace: Namespace key to isolate multiple chats in the same DB.
    """
    def __init__(
        self,
        keep: int = 10,
        summarize: bool = True,
        path: Optional[str] = None,
        namespace: str = "default",
    ):
        self.keep = keep
        self.summarize = summarize
        self.namespace = namespace
        self.path = os.path.expanduser(path) if path else self._default_path_for_namespace(namespace)
        self.messages: List[Dict[str, str]] = []
        self.summary: str = ""
        self._lock = threading.Lock()

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
            rows = conn.execute(
                "SELECT role, content FROM chat_messages WHERE namespace = ? ORDER BY id ASC",
                (self.namespace,),
            ).fetchall()

            summary_row = conn.execute(
                "SELECT summary FROM chat_state WHERE namespace = ?",
                (self.namespace,),
            ).fetchone()

        self.messages = [{"role": r[0], "content": r[1]} for r in rows]
        self.summary = summary_row[0] if summary_row and summary_row[0] else ""

    def _persist_message(self, role: str, content: str):
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT INTO chat_messages (namespace, role, content) VALUES (?, ?, ?)",
                (self.namespace, role, content),
            )

    def _persist_summary(self, summary: str):
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
        if count <= 0:
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
        """Add a message to the conversation history.
        
        Args:
            role: Message source — typically "user", "assistant", or "system".
            content: The message text.
        
        Example::
        
            chat = Chat(keep=10)
            chat.append("user", "What's the weather?")
            chat.append("assistant", "It's sunny today.")
        """
        with self._lock:
            self.messages.append({"role": role, "content": content})
            self._persist_message(role, content)
        
    def clear(self):
        """Remove all messages and summaries. Use before starting a new conversation."""
        with self._lock:
            self.messages.clear()
            self.summary = ""
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
            return len(self.messages) > 0
            
        return len(self.messages) > self.keep
        
    def get_messages_for_compression(self) -> List[Dict[str, str]]:
        """Return a snapshot of all current messages for safe async summarization.
        
        Used internally — developers don't call this directly.
        """
        with self._lock:
            return list(self.messages)
        
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
                self.summary = new_summary
                self._persist_summary(new_summary)
                
            # Only remove the number of messages that were actually compressed,
            # leaving any brand new messages that arrived during generation intact.
            if compressed_count > 0 and len(self.messages) >= compressed_count:
                if self.keep > 0:
                    # E.g. compressed 12 messages, keep is 10. we discard the first 2.
                    # However we want to discard exactly (compressed_count - keep)
                    discard_count = compressed_count - self.keep
                    if discard_count > 0:
                        self.messages = self.messages[discard_count:]
                        self._delete_oldest_messages(discard_count)
                else:
                    self.messages = self.messages[compressed_count:]
                    self._delete_oldest_messages(compressed_count)


