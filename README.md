# Delfhos

Python SDK for building AI agents that use real tools — Gmail, SQL, Drive, Sheets, MCP servers, and your own functions — with safe, human-in-the-loop execution.

> Full documentation at **[delfhos.com/docs](https://delfhos.com/docs)**

---

## How it works

You describe a task in plain English. Delfhos:

1. **Picks** the relevant tools from the ones you configured
2. **Writes** Python code to accomplish the task
3. **Executes** that code in a sandbox against your real services
4. **Retries** automatically if something fails

You stay in control: restrict which actions each tool can take, and require approval before any write, send, or delete.

---

## Install

```bash
pip install delfhos
```

## API Key

Delfhos supports Gemini, OpenAI, and Anthropic models. Export the key for the provider you want to use:

```bash
export GOOGLE_API_KEY="..."    # Gemini
export OPENAI_API_KEY="..."    # OpenAI
export ANTHROPIC_API_KEY="..."  # Claude
```

---

## Try it instantly (no credentials needed)

The sandbox tools come pre-loaded with dummy data so you can run your first agent right now:

```python
from delfhos import Agent
from delfhos.sandbox import MockEmail, MockDatabase

agent = Agent(
    tools=[MockEmail(confirm=False), MockDatabase(confirm=False)],
    llm="gemini-3.1-flash-lite-preview",
)

agent.run(
    "Read my unread emails. If any mention a support ticket, "
    "look it up in the database and summarise the customer name, "
    "open tickets, and total order value."
)
agent.stop()
```

Or just run the included example:

```bash
python examples/hello_delfhos.py
```

---

## Custom tools

Decorate any Python function with `@tool` and the agent can call it:

```python
from delfhos import Agent, tool

@tool
def calculate_discount(price: float, pct: float) -> float:
    """Return price after applying a percentage discount."""
    return price * (1 - pct / 100)

agent = Agent(tools=[calculate_discount], llm="gemini-3.1-flash-lite-preview")
agent.run("What is the price of a $120 item with a 15% discount?")
agent.stop()
```

---

## Built-in tools

```python
from delfhos import Gmail, SQL, Sheets, Drive, Calendar, Docs, WebSearch, MCP, APITool
```

```python
gmail = Gmail(oauth_credentials="client_secrets.json", allow=["read", "send"], confirm=["send"])
db    = SQL(url="postgresql://user:pass@host/db",       allow=["schema", "query"])
drive = Drive(oauth_credentials="client_secrets.json",  confirm=True)

agent = Agent(tools=[gmail, db, drive], llm="gemini-3.1-flash-lite-preview")
agent.run("Check unread emails and log any order mentions to the database.")
agent.stop()
```

**`allow`** — restrict which actions are available on the tool (`["read", "send"]`, `["schema", "query"]`, …).  
**`confirm`** — when human approval is required: `True` (all), `False` (none), or a list of specific actions.

---

## REST API Integration (APITool)

Connect any REST API with an OpenAPI 3.x specification — no custom code needed.

```python
from delfhos import Agent, APITool

# From a public OpenAPI spec
petstore = APITool(
    spec="https://petstore3.swagger.io/api/v3/openapi.json",
    allow=["list_pets", "get_pet_by_id"],
    confirm=["create_pet", "delete_pet"],
)

# From a local spec with authentication
internal = APITool(
    spec="./openapi.yaml",
    base_url="https://api.internal.corp/v1",
    auth={"Authorization": "Bearer sk_..."},
)

# Inspect available endpoints
print(petstore.inspect())  # Compact: endpoint names
print(petstore.inspect(verbose=True))  # Detailed: methods, paths, descriptions

agent = Agent(tools=[petstore, internal], llm="gemini-2.5-flash")
agent.run("List all pets and create a new one named 'Buddy'")
```

**Features:**
- Automatic endpoint compilation from OpenAPI specs (no LLM needed)
- Path, query, and request body parameters extracted and typed
- Auth headers and query params injected per-endpoint
- `$ref` resolution for complex schemas
- `allow=` and `confirm=` support for fine-grained access control
- Caching: specs compiled once and cached to `~/delfhos/api_cache/`

---

## Interactive chat

```python
from delfhos import Agent, Chat, Gmail

agent = Agent(
    tools=[Gmail(oauth_credentials="client_secrets.json")],
    llm="gemini-3.1-flash-lite-preview",
    chat=Chat(summarizer_llm="gemini-3.1-flash-lite-preview"),
)

agent.run_chat()  # starts a terminal session — type /help for commands
```

---

## Memory & Long-term Context

Delfhos supports both session memory and persistent semantic memory with 100+ embedding models.

```python
from delfhos import Agent, Chat, Memory

agent = Agent(
    tools=[...],
    llm="gemini-3.1-flash-lite-preview",
    chat=Chat(keep=8, summarize=True, namespace="my_agent"),    # short-term
    memory=Memory(namespace="my_agent"),                         # long-term semantic
)
```

**100+ Embedding Models:** Automatic detection and compatibility for:
- **Proprietary:** OpenAI, Cohere, Anthropic, Google
- **Open-source:** Sentence-Transformers (MiniLM, all-MiniLM, all-mpnet, etc.)
- **Specialized:** BGE models (Alibaba), Jina, Nomic Embed, NV-Embed
- **Local-first:** Run models locally via Ollama or Hugging Face Transformers

Auto-detects model requirements:
- `trust_remote_code` toggles (for BGE, Jina, etc.)
- Instruction/prefix tokens (e.g., Nomic's "search_document:" prefix)
- Model dimensions (inferred after loading)

See [EMBEDDING_MODELS_GUIDE.md](https://github.com/Delfhos/delfhos/blob/main/EMBEDDING_MODELS_GUIDE.md) for the full compatibility matrix.

---

## MCP servers

```python
from delfhos import Agent, MCP

fs = MCP("server-filesystem", args=["."], allow=["read_file", "write_file"])
agent = Agent(tools=[fs], llm="gemini-3.1-flash-lite-preview")
agent.run("List all Python files and write a one-line summary for each.")
agent.stop()
```

---

## Response object

`agent.run()` returns a `Response` with the result, status, cost, and trace:

```python
r = agent.run("How many users signed up this week?")

print(r.text)        # agent's answer
print(r.status)      # True if task succeeded
print(r.cost_usd)    # cost in dollars (e.g. 0.0003)
print(r.duration_ms) # wall-clock time in milliseconds
```

---

## Model support

**Cloud providers:** Gemini, OpenAI, or Anthropic

```python
# Gemini
agent = Agent(tools=[...], llm="gemini-2.0-flash-lite")
agent = Agent(tools=[...], llm="gemini-2.0-flash")

# OpenAI
agent = Agent(tools=[...], llm="gpt-5")
agent = Agent(tools=[...], llm="gpt-4o")

# Anthropic
agent = Agent(tools=[...], llm="claude-4-5-haiku")
agent = Agent(tools=[...], llm="claude-4-6-sonnet")
```

**Local & custom models:** Use `LLMConfig` for any OpenAI-compatible endpoint

```python
from delfhos import Agent, LLMConfig

# Local Ollama model
agent = Agent(
    tools=[...],
    llm=LLMConfig(model="llama3.2", base_url="http://localhost:11434/v1")
)

# Enterprise vLLM server
agent = Agent(
    tools=[...],
    llm=LLMConfig(
        model="mistral-7b-instruct",
        base_url="https://llm.corp.internal/v1",
        api_key="internal-token"
    )
)

# Any OpenAI-compatible provider (Groq, Together, Anyscale, etc.)
agent = Agent(
    tools=[...],
    llm=LLMConfig(
        model="meta-llama/Llama-3-70b-chat-hf",
        base_url="https://api.together.xyz/v1",
        api_key="..."
    )
)
```

**Dual-LLM optimization:** Use fast local + strong cloud model

```python
agent = Agent(
    tools=[...],
    light_llm=LLMConfig(model="qwen2.5:7b", base_url="http://localhost:11434/v1"),
    heavy_llm="gemini-2.5-flash",  # or Claude, OpenAI, etc.
)
```

---

## Context manager

The agent cleans up automatically when used as a context manager:

```python
with Agent(tools=[...], llm="gemini-3.1-flash-lite-preview") as agent:
    agent.run("Summarise last week's sales and email it to the team.")
```

---

For the full API reference and advanced guides see [DOCS.md](DOCS.md) or **[delfhos.com/docs](https://delfhos.com/docs)**.

## License

Apache-2.0
