"""Type stubs for delfhos.memory.persistent — Long-term semantic memory."""

from typing import Iterator, List, Optional, Union, Tuple, Dict
from delfhos.memory.types import Fact

class EmbeddingModelInfo:
    """Auto-detect embedding model capabilities and requirements.
    
    Supports any sentence-transformers model with automatic detection of:
    - Whether trust_remote_code is required
    - Whether instruction/prefix tokens are needed
    """
    
    REQUIRES_TRUST_REMOTE: frozenset[str]
    MODELS_WITH_PREFIXES: Dict[str, Tuple[str, str]]
    
    @staticmethod
    def _matches_pattern(model_name: str, pattern: str) -> bool: ...
    
    @classmethod
    def requires_trust_remote_code(cls, model_name: str) -> bool:
        """Check if model requires trust_remote_code=True."""
        ...
    
    @classmethod
    def get_prefixes(cls, model_name: str) -> Optional[Tuple[str, str]]:
        """Get (document_prefix, query_prefix) if model uses them, else None."""
        ...
    
    @classmethod
    def normalize_model_name(cls, model_name: str, aliases: Dict[str, str]) -> str:
        """Resolve aliases and normalize model name."""
        ...

class Memory:
    """
    Long-term, persistent, SQLite-backed memory with semantic retrieval.

    Uses local sentence-transformer embeddings by default — no API key needed,
    nothing leaves your machine.

    Supports ANY sentence-transformers model with automatic detection of
    model-specific requirements (trust_remote_code, instruction prefixes, etc.).

    Popular models::

        # Default — all-MiniLM-L6-v2, ~90MB download (good balance)
        memory = Memory()
        
        # All models from https://www.sbert.net/docs/pretrained_models.html work
        memory = Memory(embedding_model="all-mpnet-base-v2")      # Higher quality
        memory = Memory(embedding_model="nomic-embed-text")       # Auto-detected prefixes
        memory = Memory(embedding_model="bge-small-en-v1.5")      # BGE models
        
        # HuggingFace model IDs work directly too
        memory = Memory(embedding_model="sentence-transformers/all-MiniLM-L6-v2")

    Built-in aliases for convenience::

        all-MiniLM-L6-v2  -> sentence-transformers/all-MiniLM-L6-v2
        nomic-embed-text  -> nomic-ai/nomic-embed-text-v1.5

    Args:
        guidelines: Optional guidelines for memory retrieval behavior.
        path: SQLite file path. Defaults to ~/delfhos/memory/<namespace>.db.
        namespace: Namespace to isolate facts (default: "default").
        embedding_model: Any sentence-transformer model name, HF model ID, or alias
                        (default: "all-MiniLM-L6-v2").
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
