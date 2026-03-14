import os
import json
import sqlite3
from typing import List, Dict, Optional, Any
import threading


class Chat:
    """
    Short-term, ephemeral session memory for an Agent.
    Lives only for the current session and manages conversation truncation/summarization.
    """
    def __init__(self, keep: int = 10, summarize: bool = False):
        self.keep = keep
        self.summarize = summarize
        self.messages: List[Dict[str, str]] = []
        self.summary: str = ""
        self._lock = threading.Lock()
        
    def append(self, role: str, content: str):
        """Append a generic message to the chat."""
        with self._lock:
            self.messages.append({"role": role, "content": content})
        
    def clear(self):
        """Clear all messages and summaries for the next session."""
        with self._lock:
            self.messages.clear()
            self.summary = ""
        
    def needs_compression(self) -> bool:
        """Check if the internal message list exceeds the keep threshold."""
        # If keeping 0, compress immediately
        if self.keep == 0 and self.summarize:
            return len(self.messages) > 0
            
        return len(self.messages) > self.keep
        
    def get_messages_for_compression(self) -> List[Dict[str, str]]:
        """Return a snapshot of the current messages to safely compress in the background."""
        with self._lock:
            return list(self.messages)
        
    def apply_compression(self, new_summary: str, compressed_count: int):
        """Safely apply an asynchronously generated summary and slice the compressed messages."""
        with self._lock:
            if new_summary:
                self.summary = new_summary
                
            # Only remove the number of messages that were actually compressed,
            # leaving any brand new messages that arrived during generation intact.
            if compressed_count > 0 and len(self.messages) >= compressed_count:
                if self.keep > 0:
                    # E.g. compressed 12 messages, keep is 10. we discard the first 2.
                    # However we want to discard exactly (compressed_count - keep)
                    discard_count = compressed_count - self.keep
                    if discard_count > 0:
                        self.messages = self.messages[discard_count:]
                else:
                    self.messages = self.messages[compressed_count:]


