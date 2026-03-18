"""delfhos.memory — Session and long-term memory for AI agents.

**Chat** — session memory with auto-summarization (in-memory by default)::

    from delfhos.memory import Chat
    chat = Chat(namespace="support_bot")  # in-memory for this run only
    agent = Agent(tools=[...], chat=chat)

To persist Chat in SQLite across runs::

    chat = Chat(namespace="support_bot", persist=True)
    # default path when persist=True: ~/delfhos/chat/support_bot.db

**Memory** — persistent, semantic embeddings::

    from delfhos.memory import Memory
    memory = Memory(namespace="user_docs")  # default path: ~/delfhos/memory/user_docs.db
    # Retrieve relevant facts from long-term storage

Both are optional — agents work fine without explicit memory.
"""
from .chat import Chat
from .persistent import Memory

__all__ = ["Chat", "Memory"]
