"""Type stubs for delfhos.memory.chat — Session memory with auto-summarization."""

from typing import Dict, Iterator, List, Optional, Union

from delfhos.memory.types import Message

class Chat:
    """
    Session memory for an Agent — keeps recent conversation history and auto-summarizes.

    The agent appends messages to this Chat. Once the message count exceeds ``keep``,
    the oldest messages are summarized asynchronously and removed.

    Example:
        chat = Chat(summarizer_llm="gemini-3.1-flash-lite-preview")  # Auto-summarizes old messages, keeps last 10
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
        summarizer_llm: LLM model used for chat compression (e.g., "gemini-3.1-flash-lite-preview").
                        If not provided, must be set before the agent attempts compression.
    """
    keep: int
    summarize: bool
    persist: bool
    namespace: str
    path: str
    summarizer_llm: Optional[str]

    def __init__(
        self,
        keep: int = 10,
        summarize: bool = True,
        persist: bool = False,
        path: Optional[str] = None,
        namespace: str = "default",
        summarizer_llm: Optional[str] = None,
    ) -> None: ...

    def append(self, role: str, content: str) -> None:
        """Add a message to the conversation history."""
        ...

    def clear(self) -> None:
        """Remove all messages and summaries. Use before starting a new conversation."""
        ...

    def needs_compression(self) -> bool:
        """Check if message count exceeds the ``keep`` threshold and should be summarized.

        Usually called internally by the agent — not for manual use.

        Returns:
            True if compression (summarization) should run, False otherwise.
        """
        ...

    def get_messages_for_compression(self) -> List[Dict[str, str]]:
        """Return a snapshot of all current messages for safe async summarization.

        Used internally — developers don't call this directly.
        """
        ...

    def apply_compression(self, new_summary: str, compressed_count: int) -> None:
        """Apply the summarized version and discard old messages safely.

        Called internally after async summarization completes.

        Args:
            new_summary: The AI-generated summary of old messages.
            compressed_count: How many original messages were summarized.
        """
        ...

    @property
    def messages(self) -> List[Dict[str, str]]:
        """List of messages as dicts with 'role' and 'content' keys."""
        ...

    @property
    def summary(self) -> Optional[str]:
        """Current summary of old messages, or None if no summary exists."""
        ...

    def by_role(self, role: str) -> List[Message]:
        """Filter messages by role (e.g., 'user', 'assistant')."""
        ...

    def __iter__(self) -> Iterator[Message]: ...
    def __len__(self) -> int: ...
    def __getitem__(self, key: Union[int, slice]) -> Union[Message, List[Message]]: ...
    def __str__(self) -> str: ...
