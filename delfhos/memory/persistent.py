import os
import json
import sqlite3
import logging
import re
from typing import List, Dict, Optional, Any, Tuple
import threading
import io
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
from typing import Union, Iterator
from .types import Fact


class EmbeddingModelInfo:
    """
    Auto-detect embedding model capabilities and requirements.
    
    Supports any sentence-transformers model with automatic detection of:
    - Whether trust_remote_code is required
    - Whether instruction/prefix tokens are needed
    - Model dimension (inferred after loading)
    """
    
    # Models that require trust_remote_code=True for safety/licensing
    REQUIRES_TRUST_REMOTE = frozenset([
        "nomic-embed-text",
        "nomic-ai/nomic-embed-text",
        "bge-",  # All BGE models
        "jina-",  # All Jina models
    ])
    
    # Models with instruction/prefix requirements (e.g., search_document/search_query)
    MODELS_WITH_PREFIXES = {
        "nomic-embed-text": ("search_document: ", "search_query: "),
        "nomic-ai/nomic-embed-text-v1.5": ("search_document: ", "search_query: "),
        "nomic-ai/nomic-embed-text-v1": ("search_document: ", "search_query: "),
    }
    
    @staticmethod
    def _matches_pattern(model_name: str, pattern: str) -> bool:
        """Check if model name contains or starts with pattern."""
        model_lower = model_name.lower()
        return pattern.lower() in model_lower or model_lower.startswith(pattern.lower())
    
    @classmethod
    def requires_trust_remote_code(cls, model_name: str) -> bool:
        """Check if model requires trust_remote_code=True."""
        model_lower = model_name.lower()
        return any(
            cls._matches_pattern(model_lower, pattern)
            for pattern in cls.REQUIRES_TRUST_REMOTE
        )
    
    @classmethod
    def get_prefixes(cls, model_name: str) -> Optional[Tuple[str, str]]:
        """Get (document_prefix, query_prefix) if model uses them, else None."""
        # Exact matches in registry
        for registered_name, prefixes in cls.MODELS_WITH_PREFIXES.items():
            if model_name == registered_name or model_name.endswith("/" + registered_name.split("/")[-1]):
                return prefixes
        
        # Pattern-based detection for nomic models
        if "nomic" in model_name.lower() and "embed-text" in model_name.lower():
            return ("search_document: ", "search_query: ")
        
        return None
    
    @classmethod
    def normalize_model_name(cls, model_name: str, aliases: Dict[str, str]) -> str:
        """Resolve aliases and normalize model name."""
        return aliases.get(model_name, model_name)


class Memory:
    """
    Long-term, persistent, SQLite-backed memory with semantic retrieval.

    Uses local sentence-transformer embeddings by default — no API key needed,
    nothing leaves your machine. Good enough for matching business facts like
    "Acme Corp billing email" against "process Acme invoice".

    Supports ANY sentence-transformers model automatically. Popular choices::

        # Default — all-MiniLM-L6-v2, ~90MB download (good balance)
        memory = Memory()
        
        # All models from https://www.sbert.net/docs/pretrained_models.html work
        memory = Memory(embedding_model="all-mpnet-base-v2")      # Higher quality
        memory = Memory(embedding_model="nomic-embed-text")       # Auto-detected prefixes
        memory = Memory(embedding_model="bge-small-en-v1.5")      # BGE models
        
        # Use HuggingFace model IDs directly
        memory = Memory(embedding_model="sentence-transformers/all-MiniLM-L6-v2")
        
        # Use a specific namespace to isolate facts
        user_memory = Memory(namespace="user_profile")
        user_memory.save("User likes Python.")

    Model requirements are auto-detected. Supports:
    - Instruction-based models (nomic-embed-text, BGE, Jina, etc.)
    - Standard embedding models (all-MiniLM, MPNET, etc.)
    - Any future sentence-transformers compatible model
    
    Built-in aliases for convenience::
        all-MiniLM-L6-v2  -> sentence-transformers/all-MiniLM-L6-v2
        nomic-embed-text  -> nomic-ai/nomic-embed-text-v1.5
    """

    _DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
    _MODEL_ALIASES = {
        "all-MiniLM-L6-v2": "all-MiniLM-L6-v2",
        "nomic-embed-text": "nomic-ai/nomic-embed-text-v1.5",
        # Add more aliases as needed
    }

    def __init__(
        self,
        guidelines: Optional[str] = None,
        path: Optional[str] = None,
        namespace: str = "default",
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        self.guidelines = guidelines
        self.namespace = namespace
        self.path = os.path.expanduser(path) if path else self._default_path_for_namespace(namespace)
        model_name = (embedding_model or self._DEFAULT_EMBEDDING_MODEL).strip()
        self.embedding_model_name = model_name or self._DEFAULT_EMBEDDING_MODEL

        # Lazy-loaded embedding model (heavy import, only pay once)
        self._model = None
        self._embed_dim: Optional[int] = None

        self._init_db()

    @staticmethod
    def _sanitize_namespace(namespace: str) -> str:
        raw = (namespace or "default").strip()
        if not raw:
            raw = "default"
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw)
        return safe or "default"

    @classmethod
    def _default_path_for_namespace(cls, namespace: str) -> str:
        filename = f"{cls._sanitize_namespace(namespace)}.db"
        return os.path.expanduser(os.path.join("~", "delfhos", "memory", filename))
        
    def _init_db(self):
        """Initialize SQLite database and schema (text + embedding tables)."""
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    namespace TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute("CREATE INDEX IF NOT EXISTS idx_namespace ON memories(namespace)")

            # Embeddings table — one row per memory row
            conn.execute('''
                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    memory_id INTEGER PRIMARY KEY REFERENCES memories(id),
                    embedding BLOB NOT NULL
                )
            ''')

    # ------------------------------------------------------------------
    # Embedding helpers
    # ------------------------------------------------------------------

    def _resolve_embedding_model_name(self) -> str:
        """Resolve user-provided model name, preserving compatibility aliases."""
        return EmbeddingModelInfo.normalize_model_name(
            self.embedding_model_name, 
            self._MODEL_ALIASES
        )

    def _get_model(self):
        """Lazy-load the sentence-transformer model once."""
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            from delfhos.errors import OptionalDependencyError
            raise OptionalDependencyError(
                package="sentence-transformers",
                detail="It is required for persistent memory embeddings."
            )

        # Reduce noisy third-party download/model-load logs globally.
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
        logging.getLogger("transformers").setLevel(logging.ERROR)

        try:
            from huggingface_hub.utils import logging as hf_logging
            hf_logging.set_verbosity_error()
        except Exception:
            pass

        try:
            from transformers import logging as tf_logging
            tf_logging.set_verbosity_error()
        except Exception:
            pass

        # Log model loading for user visibility using official console
        import time
        model_load_start = time.time()
        
        # Import console for official logging
        try:
            from cortex._engine.utils.console import console
        except ImportError:
            # Fallback if cortex is not available
            console = None
        
        target_model = self._resolve_embedding_model_name()
        msg = f"Loading embedding model ({target_model})..."
        if console:
            console.info("Memory", msg)

        # Auto-detect if model requires trust_remote_code
        trust_remote = EmbeddingModelInfo.requires_trust_remote_code(target_model)
        kwargs = {"trust_remote_code": trust_remote} if trust_remote else {}

        # Silence residual noisy third-party model loading output that bypasses
        # logger settings (stderr/stdout writes).
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self._model = SentenceTransformer(target_model, **kwargs)
        except Exception as e:
            # If loading fails without trust_remote_code, try with it as fallback
            if not trust_remote:
                try:
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        self._model = SentenceTransformer(target_model, trust_remote_code=True)
                except Exception:
                    raise e  # Raise original error
            else:
                raise
        
        model_load_time = time.time() - model_load_start
        ready_msg = f"Embedding model ready ({model_load_time:.1f}s)"
        if console:
            console.info("Memory", ready_msg)

        self._embed_dim = self._model.get_sentence_embedding_dimension()
        return self._model

    def _embed(self, texts: List[str]):
        """Return numpy array of shape (len(texts), dim)."""
        import numpy as np
        model = self._get_model()
        
        # Auto-detect if model requires instruction prefixes
        prefixes = EmbeddingModelInfo.get_prefixes(self._resolve_embedding_model_name())
        
        texts_to_encode = texts
        if prefixes:
            doc_prefix = prefixes[0]
            texts_to_encode = [f"{doc_prefix}{t}" for t in texts]
        
        return model.encode(texts_to_encode, normalize_embeddings=True)

    def _embed_query(self, query: str):
        """Embed a single query string. Returns 1-D numpy array."""
        model = self._get_model()
        
        # Auto-detect if model requires instruction prefixes
        prefixes = EmbeddingModelInfo.get_prefixes(self._resolve_embedding_model_name())
        
        query_to_encode = query
        if prefixes:
            query_prefix = prefixes[1]
            query_to_encode = f"{query_prefix}{query}"
        
        return model.encode([query_to_encode], normalize_embeddings=True)[0]

    @staticmethod
    def _blob_to_vec(blob: bytes):
        import numpy as np
        return np.frombuffer(blob, dtype=np.float32)

    @staticmethod
    def _vec_to_blob(vec) -> bytes:
        import numpy as np
        return np.asarray(vec, dtype=np.float32).tobytes()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def context(self) -> str:
        """Retrieve all stored memories for this namespace, in chronological order.
        
        Returns the complete long-term memory dump — useful for logging or inspection.
        Much slower than `retrieve()` which uses semantic search.
        
        Returns:
            Newline-joined string of all facts, or empty string if empty.
        """
        with sqlite3.connect(self.path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT content FROM memories WHERE namespace = ? ORDER BY timestamp ASC",
                (self.namespace,),
            )
            rows = cursor.fetchall()
            
        if not rows:
            return ""
            
        return "\n".join(row[0] for row in rows)

    def _parse_ts(self, ts_str: str) -> datetime:
        if not ts_str: return datetime.now()
        try:
            return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return datetime.now()

    def search(self, query: str, top_k: int = 5, threshold: float = 0.3) -> List[Fact]:
        """Fetch the most relevant memories using semantic similarity.
        
        Uses local embeddings (no API calls) to find the closest match to your query.
        Great for: "Find facts about Acme Corp", "What does the user prefer?", etc.
        
        Args:
            query: A natural-language question or topic (e.g., "user billing email").
            top_k: Max number of results to return (default 5).
            threshold: Min similarity score (0.0–1.0) to include. Lower = broader matches.
        
        Returns:
            List of `Fact` objects above threshold, or empty list if no matches.
        
        Example::
        
            memory = Memory(namespace="user_profile")
            memory.save("User is David. Likes Python. Works at Acme Corp.")
            results = memory.search("What's the user's company?")
            print(results[0].content)  # → "Works at Acme Corp."
        """
        import numpy as np

        with sqlite3.connect(self.path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT m.id, m.content, m.timestamp, e.embedding
                   FROM memories m
                   JOIN memory_embeddings e ON e.memory_id = m.id
                   WHERE m.namespace = ?""",
                (self.namespace,),
            )
            rows = cursor.fetchall()

        if not rows:
            return []

        query_vec = self._embed_query(query)
        scored = []
        for _id, content, timestamp, blob in rows:
            vec = self._blob_to_vec(blob)
            sim = float(np.dot(query_vec, vec))  # both L2-normalized → dot = cosine
            if sim >= threshold:
                fact = Fact(
                    content=content,
                    saved_at=self._parse_ts(timestamp),
                    namespace=self.namespace
                )
                scored.append((sim, fact))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]
        return [fact for _, fact in top]

    # Alias for backward compatibility
    def retrieve(self, query: str, top_k: int = 5, threshold: float = 0.3) -> str:
        results = self.search(query, top_k, threshold)
        return "\n".join(f.content for f in results) if results else ""

    def save(self, content: str):
        """Store facts in long-term semantic memory.
        
        Splits content by newline into individual facts, embeds each one,
        and stores in SQLite. Later calls to `retrieve()` will efficiently
        find matching facts by meaning, not just keywords.
        
        Args:
            content: One fact per line (or a multi-sentence block). Empty lines ignored.
        
        Example::
        
            memory = Memory(namespace="customer_acme")
            memory.save("Account holder: Alice\nBilling email: alice@acme.com\nTier: Enterprise")
            # Now retrieve("contact email") will find: "Billing email: alice@acme.com"
        """
        if not content or not content.strip():
            return

        # Split multi-line content into individual facts for granular retrieval
        facts = [line.strip() for line in content.split("\n") if line.strip()]
        if not facts:
            return

        embeddings = self._embed(facts)

        with sqlite3.connect(self.path) as conn:
            for fact, vec in zip(facts, embeddings):
                cursor = conn.execute(
                    "INSERT INTO memories (namespace, content) VALUES (?, ?)",
                    (self.namespace, fact),
                )
                mem_id = cursor.lastrowid
                conn.execute(
                    "INSERT INTO memory_embeddings (memory_id, embedding) VALUES (?, ?)",
                    (mem_id, self._vec_to_blob(vec)),
                )

    def add(self, content: str):
        """
        Manually add information to memory from the outside.
        
        Args:
            content: A direct text string to store, or a path to a .txt or .md file.
                     If it's a file path, its text will be read and saved to memory.
        """
        import os
        
        content = str(content).strip()
        if not content:
            return

        # Check if it's a path to a supported file
        if os.path.isfile(content) and (content.lower().endswith('.txt') or content.lower().endswith('.md')):
            try:
                with open(content, 'r', encoding='utf-8') as f:
                    file_text = f.read()
                    if file_text.strip():
                        self.save(file_text)
                    else:
                        from cortex._engine.utils.console import console
                        if console:
                            console.warning("Memory", f"File is empty: {content}")
            except Exception as e:
                from cortex._engine.utils.console import console
                if console:
                    console.warning("Memory", f"Failed to read file {content}: {e}")
        else:
            # Direct text string
            self.save(content)

    def backfill_embeddings(self):
        """Generate embeddings for memories missing them (e.g., after DB migration).
        
        If you imported old memory data or upgraded the Memory class without
        embeddings, run this once to enable semantic search on those facts.
        
        Runs in-process (may take a few seconds for large databases).
        """
        with sqlite3.connect(self.path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT m.id, m.content FROM memories m
                   LEFT JOIN memory_embeddings e ON e.memory_id = m.id
                   WHERE m.namespace = ? AND e.memory_id IS NULL""",
                (self.namespace,),
            )
            rows = cursor.fetchall()

        if not rows:
            return

        ids = [r[0] for r in rows]
        texts = [r[1] for r in rows]
        vecs = self._embed(texts)

        with sqlite3.connect(self.path) as conn:
            for mid, vec in zip(ids, vecs):
                conn.execute(
                    "INSERT OR IGNORE INTO memory_embeddings (memory_id, embedding) VALUES (?, ?)",
                    (mid, self._vec_to_blob(vec)),
                )

    # ------------------------------------------------------------------
    # Pythonic API
    # ------------------------------------------------------------------

    def _get_all_facts(self) -> List[Fact]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT content, timestamp FROM memories WHERE namespace = ? ORDER BY timestamp ASC",
                (self.namespace,),
            ).fetchall()
            
        return [
            Fact(
                content=row[0], 
                saved_at=self._parse_ts(row[1]), 
                namespace=self.namespace
            ) for row in rows
        ]

    def __iter__(self) -> Iterator[Fact]:
        return iter(self._get_all_facts())

    def __len__(self) -> int:
        with sqlite3.connect(self.path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE namespace = ?", 
                (self.namespace,)
            ).fetchone()
            return count[0] if count else 0

    def __getitem__(self, key: Union[int, slice]) -> Union[Fact, List[Fact]]:
        facts = self._get_all_facts()
        return facts[key]

    def clear(self):
        """Irreversibly delete all facts in this namespace."""
        with sqlite3.connect(self.path) as conn:
            # Deletes embeddings first due to ON DELETE CASCADE (or explicitly here)
            conn.execute(
                """DELETE FROM memory_embeddings 
                   WHERE memory_id IN (SELECT id FROM memories WHERE namespace = ?)""", 
                (self.namespace,)
            )
            conn.execute("DELETE FROM memories WHERE namespace = ?", (self.namespace,))

    def __str__(self) -> str:
        facts = self._get_all_facts()
        count = len(facts)
        
        lines = [f"Memory — {count} facts  [namespace: {self.namespace}]", "─" * 42]
        
        for i, fact in enumerate(facts, 1):
            date_str = fact.saved_at.strftime("%Y-%m-%d")
            # Break content into lines & wrap
            import textwrap
            wrapped = textwrap.fill(fact.content, width=55, subsequent_indent="                ")
            lines.append(f"[{i}] {date_str}  {wrapped}\n")
            
        lines.append("─" * 42)
        return "\n".join(lines)
