import os
import json
import sqlite3
from typing import List, Dict, Optional, Any
import threading


import os
import json
import sqlite3
from typing import List, Dict, Optional, Any
import threading

class Memory:
    """
    Long-term, persistent, SQLite-backed memory with semantic retrieval.

    Uses local sentence-transformer embeddings by default — no API key needed,
    nothing leaves your machine. Good enough for matching business facts like
    "Acme Corp billing email" against "process Acme invoice".

    Usage::

        # Default — local all-MiniLM-L6-v2, ~90MB download (cached forever)
        memory = Memory()

        # Better quality local model
        memory = Memory(embedding_model="nomic-embed-text")

    Supported local models::

        all-MiniLM-L6-v2    — 90MB, fast, good quality (default)
        nomic-embed-text     — 270MB, better quality
    """

    _SUPPORTED_MODELS = {"all-MiniLM-L6-v2", "nomic-embed-text"}

    def __init__(
        self,
        guidelines: Optional[str] = None,
        path: str = "~/.delfhos/memory.db",
        namespace: str = "default",
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        self.guidelines = guidelines
        self.path = os.path.expanduser(path)
        self.namespace = namespace
        self.embedding_model_name = embedding_model

        # Lazy-loaded embedding model (heavy import, only pay once)
        self._model = None
        self._embed_dim: Optional[int] = None

        self._init_db()
        
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

        if self.embedding_model_name == "nomic-embed-text":
            self._model = SentenceTransformer(
                "nomic-ai/nomic-embed-text-v1.5",
                trust_remote_code=True,
            )
        else:
            self._model = SentenceTransformer("all-MiniLM-L6-v2")

        self._embed_dim = self._model.get_sentence_embedding_dimension()
        return self._model

    def _embed(self, texts: List[str]):
        """Return numpy array of shape (len(texts), dim)."""
        import numpy as np
        model = self._get_model()
        if self.embedding_model_name == "nomic-embed-text":
            # nomic requires a task prefix
            texts = [f"search_document: {t}" for t in texts]
        return model.encode(texts, normalize_embeddings=True)

    def _embed_query(self, query: str):
        """Embed a single query string. Returns 1-D numpy array."""
        model = self._get_model()
        if self.embedding_model_name == "nomic-embed-text":
            query = f"search_query: {query}"
        return model.encode([query], normalize_embeddings=True)[0]

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
        """Fetch all stored long-term memory for this namespace (full dump)."""
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

    def retrieve(self, query: str, top_k: int = 5, threshold: float = 0.3) -> str:
        """Retrieve the most relevant memories for *query* using cosine similarity.

        Returns a newline-joined string of the top-k facts above *threshold*,
        or an empty string if nothing matches.
        """
        import numpy as np

        with sqlite3.connect(self.path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT m.id, m.content, e.embedding
                   FROM memories m
                   JOIN memory_embeddings e ON e.memory_id = m.id
                   WHERE m.namespace = ?""",
                (self.namespace,),
            )
            rows = cursor.fetchall()

        if not rows:
            # Fallback: return full context if no embeddings yet
            return self.context()

        query_vec = self._embed_query(query)
        scored = []
        for _id, content, blob in rows:
            vec = self._blob_to_vec(blob)
            sim = float(np.dot(query_vec, vec))  # both L2-normalized → dot = cosine
            if sim >= threshold:
                scored.append((sim, content))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]
        return "\n".join(fact for _, fact in top) if top else ""

    def save(self, content: str):
        """Save extracted knowledge to long-term memory with embeddings."""
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

    def backfill_embeddings(self):
        """Generate embeddings for any memories that don't have them yet.

        Useful after upgrading from a pre-embedding Memory database.
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
