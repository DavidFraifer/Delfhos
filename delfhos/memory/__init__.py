"""delfhos.memory — Session and long-term memory for AI agents.

**Chat** — session memory with auto-summarization, persisted in local SQLite::

    from delfhos.memory import Chat
    chat = Chat(namespace="support_bot")  # default path: ~/delfhos/chat/support_bot.db
    agent = Agent(tools=[...], chat=chat)

**Memory** — persistent, semantic embeddings::

    from delfhos.memory import Memory
    memory = Memory(namespace="user_docs")  # default path: ~/delfhos/memory/user_docs.db
    # Retrieve relevant facts from long-term storage

Both are optional — agents work fine without explicit memory.
"""
from .chat import Chat
from .persistent import Memory

__all__ = ["Chat", "Memory"]
