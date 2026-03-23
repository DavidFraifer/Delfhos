"""Type stubs for delfhos.memory.persistent — Long-term semantic memory."""

from typing import Iterator, List, Optional, Union
from delfhos.memory.types import Fact

class Memory:
    """
    Long-term, persistent, SQLite-backed memory with semantic retrieval.

    Uses local sentence-transformer embeddings by default — no API key needed,
    nothing leaves your machine.

    Usage::

        # Default — local all-MiniLM-L6-v2, ~90MB download (cached forever)
        memory = Memory()

        # Better quality local model
        memory = Memory(embedding_model="nomic-embed-text")

        # Use a specific namespace to isolate facts
        user_memory = Memory(namespace="user_profile")
        user_memory.save("User likes Python.")

    Any Sentence Transformers-compatible embedding model can be used.
    Built-in aliases::

        all-MiniLM-L6-v2      -> sentence-transformers/all-MiniLM-L6-v2 (default)
        nomic-embed-text      -> nomic-ai/nomic-embed-text-v1.5

    Args:
        guidelines: Optional guidelines for memory retrieval behavior.
        path: SQLite file path. Defaults to ~/delfhos/memory/<namespace>.db.
        namespace: Namespace to isolate facts (default: "default").
        embedding_model: Sentence-transformer model name or alias (default: "all-MiniLM-L6-v2").
    """
    guidelines: Optional[str]
    namespace: str
    path: str
    embedding_model_name: str

    def __init__(
        self,
        guidelines: Optional[str] = None,
        path: Optional[str] = None,
        namespace: str = "default",
        embedding_model: str = "all-MiniLM-L6-v2",
    ) -> None: ...

    def context(self) -> str:
        """Retrieve all stored memories for this namespace, in chronological order.

        Returns the complete long-term memory dump — useful for logging or inspection.
        Much slower than ``search()`` which uses semantic search.

        Returns:
            Newline-joined string of all facts, or empty string if empty.
        """
        ...

    def search(self, query: str, top_k: int = 5, threshold: float = 0.3) -> List[Fact]:
        """Fetch the most relevant memories using semantic similarity.

        Uses local embeddings (no API calls) to find the closest match to your query.

        Args:
            query: A natural-language question or topic (e.g., "user billing email").
            top_k: Max number of results to return (default 5).
            threshold: Min similarity score (0.0–1.0) to include. Lower = broader matches.

        Returns:
            List of ``Fact`` objects above threshold, or empty list if no matches.

        Example::

            memory = Memory(namespace="user_profile")
            memory.save("User is David. Likes Python. Works at Acme Corp.")
            results = memory.search("What's the user's company?")
            print(results[0].content)  # → "Works at Acme Corp."
        """
        ...

    def retrieve(self, query: str, top_k: int = 5, threshold: float = 0.3) -> str:
        """Alias for ``search()`` that returns newline-joined content strings."""
        ...

    def add(self, content: str) -> None:
        """Manually add information to memory from the outside (string or .txt/.md file path)."""
        ...
        
    def save(self, content: str) -> None:
        """Store facts in long-term semantic memory.

        Splits content by newline into individual facts, embeds each one,
        and stores in SQLite.

        Args:
            content: One fact per line (or a multi-sentence block). Empty lines ignored.

        Example::

            memory = Memory(namespace="customer_acme")
            memory.save("Account holder: Alice\\nBilling email: alice@acme.com\\nTier: Enterprise")
        """
        ...

    def backfill_embeddings(self) -> None:
        """Generate embeddings for memories missing them (e.g., after DB migration)."""
        ...

    def clear(self) -> None:
        """Irreversibly delete all facts in this namespace."""
        ...

    def __iter__(self) -> Iterator[Fact]: ...
    def __len__(self) -> int: ...
    def __getitem__(self, key: Union[int, slice]) -> Union[Fact, List[Fact]]: ...
    def __str__(self) -> str: ...
