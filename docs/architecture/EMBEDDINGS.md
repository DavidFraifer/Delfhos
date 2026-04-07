# Embedding Model Support (v0.6.1+)

Delfhos supports 100+ embedding models for persistent semantic memory, with automatic detection of model-specific requirements.

## Overview

Embedding models power **long-term semantic memory** in Delfhos:

```python
from delfhos import Agent, Memory

agent = Agent(
    tools=[...],
    llm="gemini-2.5-flash",
    memory=Memory(namespace="my_agent"),  # Uses embeddings for semantic search
)

# On first run, memory is stored with embeddings
agent.run("Store that the user's favorite color is blue")

# On later runs, semantic search retrieves relevant context
agent.run("What color do I like?")  # Memory finds and includes the earlier fact
```

## Supported Models

Delfhos auto-detects and loads 100+ models from Hugging Face:

### Popular (Pre-installed)

These work with `pip install delfhos` (sentence-transformers includes them):

- **MiniLM** (fastest, smallest)
  - `all-MiniLM-L6-v2` (22.7MB, 384-dim)
  - `all-MiniLM-L12-v2` (33.6MB, 384-dim)
- **MPNET** (balanced accuracy/speed)
  - `all-mpnet-base-v2` (438MB, 768-dim)
  - `mpnet-base-v2` (438MB, 768-dim)
- **RoBERTa** (high quality)
  - `all-roberta-large-v1` (694MB, 1024-dim)

### Specialized Models

Require explicit model name in Memory():

**BGE (Baidu, Alibaba) — High quality, multilingual**
```python
Memory(namespace="my_app", embedding_model="BAAI/bge-small-en-v1.5")
Memory(namespace="my_app", embedding_model="BAAI/bge-base-en-v1.5")
Memory(namespace="my_app", embedding_model="BAAI/bge-large-en-v1.5")
```

**Jina — Long-context (8192 tokens)**
```python
Memory(namespace="my_app", embedding_model="jinaai/jina-embeddings-v2-small-en")
Memory(namespace="my_app", embedding_model="jinaai/jina-embeddings-v2-base-en")
```

**Nomic Embed — High-quality, instruction-aware**
```python
Memory(namespace="my_app", embedding_model="nomic-ai/nomic-embed-text-v1.5")
```

**NV-Embed (NVIDIA) — Enterprise**
```python
Memory(namespace="my_app", embedding_model="nvidia/NV-Embed-v1")
```

**OpenAI (via API)**
```python
Memory(namespace="my_app", embedding_model="text-embedding-3-small")
Memory(namespace="my_app", embedding_model="text-embedding-3-large")
```

**Cohere**
```python
Memory(namespace="my_app", embedding_model="cohere/embed-english-v3.0")
```

### Full List

See [EMBEDDING_MODELS_GUIDE.md](../EMBEDDING_MODELS_GUIDE.md) for the complete list of 100+ models with:
- Model names and aliases
- Dimensions
- Performance benchmarks
- Known issues/workarounds

---

## Auto-Detection Features

Delfhos automatically handles model-specific quirks:

### 1. Trust Remote Code

Some models (BGE, Jina) require downloading code from Hugging Face. Delfhos detects and loads safely:

```python
# No action needed — auto-detected
Memory(embedding_model="BAAI/bge-small-en-v1.5")
# Internally: trust_remote_code=True is set automatically
```

### 2. Instruction Prefixes

Some models expect instruction prefixes:

- **Nomic Embed:** Requires `"search_document: "` prefix for documents
- **Jina:** Expects task descriptions like `"Given a web search query, retrieve relevant documents"`

Delfhos detects and applies these automatically:

```python
# No action needed — auto-detected
Memory(embedding_model="nomic-ai/nomic-embed-text-v1.5")
# Internally: "search_document: " prepended to all documents automatically
```

### 3. Model Dimensions

Delfhos infers vector dimensions on first load (lazy initialization):

```python
mem = Memory(embedding_model="all-MiniLM-L6-v2")
# On first call: model loaded, 384-dim detected, database schema created
```

---

## Usage Examples

### Simple: Default MiniLM

```python
from delfhos import Agent, Memory

agent = Agent(
    tools=[...],
    llm="gemini-2.5-flash",
    memory=Memory(namespace="my_agent"),  # Uses all-MiniLM-L6-v2
)

agent.run("Remember: I prefer coffee over tea")
agent.run("What's my beverage preference?")  # Retrieves via semantic search
```

### Production: BGE for Quality

```python
agent = Agent(
    tools=[...],
    llm="gemini-2.5-flash",
    memory=Memory(
        namespace="production_agent",
        embedding_model="BAAI/bge-large-en-v1.5",
    ),
)
```

### Multilingual: BGE Multilingual

```python
agent = Agent(
    tools=[...],
    llm="gemini-2.5-flash",
    memory=Memory(
        namespace="multi_agent",
        embedding_model="BAAI/bge-m3",  # Works in 100+ languages
    ),
)

agent.run("Recuerda: Me encanta el chocolate")  # Spanish
agent.run("What do I like? (reply in Spanish)")  # Retrieved & answered
```

### Enterprise: NVIDIA NV-Embed

```python
agent = Agent(
    tools=[...],
    llm="gemini-2.5-flash",
    memory=Memory(
        namespace="enterprise_agent",
        embedding_model="nvidia/NV-Embed-v1",
    ),
)
```

### Long Documents: Jina 8K

```python
agent = Agent(
    tools=[...],
    llm="gemini-2.5-flash",
    memory=Memory(
        namespace="long_context_agent",
        embedding_model="jinaai/jina-embeddings-v2-base-en",  # 8192 token support
    ),
)

# Can store and retrieve from very long documents
agent.run("Remember this long policy document...")
```

---

## Model Selection Guide

| Use Case | Recommended Model | Size | Speed | Quality |
|----------|-------------------|------|-------|---------|
| **Development** | `all-MiniLM-L6-v2` | 22.7MB | ⚡⚡⚡ | ⭐⭐⭐ |
| **Production** | `all-mpnet-base-v2` | 438MB | ⚡⚡ | ⭐⭐⭐⭐ |
| **High Quality** | `BAAI/bge-large-en-v1.5` | 1.3GB | ⚡ | ⭐⭐⭐⭐⭐ |
| **Multilingual** | `BAAI/bge-m3` | 2.3GB | ⚡ | ⭐⭐⭐⭐⭐ |
| **Long Docs** | `jinaai/jina-embeddings-v2-base-en` | 568MB | ⚡⚡ | ⭐⭐⭐⭐ |
| **Enterprise** | `nvidia/NV-Embed-v1` | 768MB | ⚡⚡⚡ | ⭐⭐⭐⭐⭐ |

---

## Performance Benchmarks

(From [EMBEDDING_MODELS_GUIDE.md](../EMBEDDING_MODELS_GUIDE.md))

```
Model                          | MTEB Score | Size    | Speed    | Notes
-------------------------------|------------|---------|----------|----------
all-MiniLM-L6-v2               | 58.86      | 22.7MB  | ⚡⚡⚡    | Fast, good
all-mpnet-base-v2              | 63.30      | 438MB   | ⚡⚡     | Balanced
all-roberta-large-v1           | 65.38      | 694MB   | ⚡       | High quality
BAAI/bge-small-en-v1.5         | 63.98      | 33MB    | ⚡⚡⚡    | BGE small
BAAI/bge-base-en-v1.5          | 65.02      | 210MB   | ⚡⚡     | BGE balanced
BAAI/bge-large-en-v1.5         | 65.64      | 1.3GB   | ⚡       | BGE best
BAAI/bge-m3                    | 64.13      | 2.3GB   | ⚡       | Multilingual
jinaai/jina-embeddings-v2-base | 65.30      | 568MB   | ⚡⚡     | Long context
nvidia/NV-Embed-v1             | 66.24      | 768MB   | ⚡⚡⚡    | Enterprise
```

---

## Configuration

### Explicit Model Selection

```python
from delfhos import Memory

# Any model from HuggingFace
mem = Memory(
    namespace="my_app",
    embedding_model="all-mpnet-base-v2"
)

# or use full model ID
mem = Memory(
    namespace="my_app",
    embedding_model="sentence-transformers/all-mpnet-base-v2"
)
```

### Database Configuration

By default, memory uses SQLite at `~/.delfhos/memory_{namespace}.db`:

```python
# Use custom path or in-memory DB
mem = Memory(
    namespace="my_app",
    db_path="/custom/path/memory.db",
)

# Or in-memory for testing
mem = Memory(
    namespace="my_app",
    db_path=":memory:",
)
```

---

## Troubleshooting

### Model Download Takes Forever

Large models (1GB+) download to `~/.cache/huggingface/hub/` on first use. This is cached — subsequent uses are instant.

```bash
# Check cache size
du -sh ~/.cache/huggingface/hub/
```

### "trust_remote_code not available" Error

Delfhos auto-detects this. If you see it, report to GitHub. Workaround:

```python
# Use a simpler model temporarily
mem = Memory(embedding_model="all-MiniLM-L6-v2")
```

### Out of Memory (OOM) Errors

Reduce batch size or use smaller model:

```python
# Smaller model uses less VRAM
mem = Memory(embedding_model="all-MiniLM-L6-v2")

# vs
mem = Memory(embedding_model="all-roberta-large-v1")
```

### Slow Embeddings with CPU

Embeddings run on CPU by default. On GPU:

```python
# Delfhos auto-detects CUDA/MPS if available
# No explicit configuration needed
mem = Memory(embedding_model="all-mpnet-base-v2")
# Runs on GPU automatically if torch detects it
```

---

## Summary

Delfhos supports **100+ embedding models** with zero configuration. Pick one:

1. **Development:** `all-MiniLM-L6-v2` (22.7MB, instant)
2. **Production:** `all-mpnet-base-v2` (438MB, quality + speed)
3. **High Quality:** `BAAI/bge-large-en-v1.5` (1.3GB, best scores)
4. **Multilingual:** `BAAI/bge-m3` (2.3GB, 100+ languages)

All model-specific quirks (trust_remote_code, instruction prefixes, dimensions) are handled automatically.
