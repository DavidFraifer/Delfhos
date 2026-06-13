# Delfhos

**Python SDK for building AI agents that use real tools** — Gmail, SQL, Drive, Sheets, Calendar, Docs, REST APIs, web search, and your own functions — with safe, human-in-the-loop execution.

> Full documentation in **[DOCS.md](DOCS.md)** · **[delfhos.com/docs](https://delfhos.com/docs)**

---

## How it works

You describe a task in plain English. Delfhos:

1. **Picks** the relevant tools from the ones you configured
2. **Writes** Python code to accomplish the task
3. **Executes** that code in a sandbox against your real services
4. **Retries** automatically if something fails, and can **replan** mid-task

You stay in control: restrict which actions each tool can take, and require human approval before any write, send, or delete.

---

## Key features

- **Real tools, not just chat** — first-class Gmail, SQL, Google Drive/Sheets/Docs/Calendar, web search, and any REST API via OpenAPI. Plus your own functions with a `@tool` decorator.
- **Code-writing agent** — the LLM writes and runs Python, so it can loop, branch, and chain tools in one task instead of one-call-at-a-time.
- **Human-in-the-loop** — per-action `allow` and `confirm` controls; approve or reject sends/writes/deletes from code, a callback, or the terminal.
- **Multi-provider** — Gemini, OpenAI, and Anthropic out of the box, plus any OpenAI-compatible endpoint (Ollama, vLLM, Groq, Together…). Mix a fast model with a strong one via dual-LLM.
- **Concurrent by default** — fire many tasks at once on a single agent; each runs in parallel and is tracked independently.
- **Serve over HTTP** — expose an agent as an authenticated HTTP API in one line, to drive it from any language or service.
- **Memory** — short-term session chat plus long-term semantic memory (100+ embedding models).
- **Sandboxed execution** — runs locally or in a disposable Docker container with OS-level isolation.

---

## Install

```bash
pip install delfhos
```

## API keys

Export the key for the provider you want to use:

```bash
export GOOGLE_API_KEY="..."      # Gemini
export OPENAI_API_KEY="..."      # OpenAI
export ANTHROPIC_API_KEY="..."   # Anthropic (Claude)
```

---

## Quickstart — try it instantly (no credentials needed)

The sandbox tools come pre-loaded with dummy data, so you can run your first agent right now:

```python
from delfhos import Agent
from delfhos.sandbox import MockEmail, MockDatabase

agent = Agent(
    tools=[MockEmail(confirm=False), MockDatabase(confirm=False)],
    llm="gemini-3.5-flash",
)

agent.run(
    "Read my unread emails. If any mention a support ticket, "
    "look it up in the database and summarise the customer name, "
    "open tickets, and total order value."
)
agent.stop()
```

Or run the included example:

```bash
python examples/hello_delfhos.py
```

**What it looks like end-to-end:**

```
Input ──────────────────────────────────────────────────────────
"Read my unread emails. If any mention a support ticket,
 look it up in the database and reply with a short summary of
 the customer's name, their open tickets, and their total order value."

Agent ──────────────────────────────────────────────────────────
  [tool]  MockEmail.list_unread_emails()
  [tool]  MockDatabase.query("SELECT * FROM tickets WHERE id = 'TCK8843'")
  [tool]  MockDatabase.query("SELECT * FROM users WHERE email = 'alice@example.com'")
  [tool]  MockDatabase.query("SELECT SUM(amount) FROM orders WHERE user_id = 1")
  [tool]  MockEmail.send_email(to="alice@example.com", subject="Re: Overdue invoice")

Output ─────────────────────────────────────────────────────────
Sent a reply to alice@example.com.

Summary:
  Customer:     Alice (alice@example.com)
  Open tickets: TCK8843 — "Invoice #1042 overdue" (open)
  Total orders: $2,340.00
```

`agent.run()` returns a `Response`:

```python
r = agent.run("...")
print(r.text)         # the agent's answer
print(r.status)       # True if the task succeeded
print(r.cost_usd)     # cost in dollars, e.g. 0.00021
print(r.duration_ms)  # wall-clock time in milliseconds
```

---

## Your first real agent

Configure built-in tools with credentials, scope their actions with `allow`, and gate risky ones with `confirm`:

```python
from delfhos import Agent, Gmail, SQL, Drive

gmail = Gmail(oauth_credentials="client_secrets.json", allow=["read", "send"], confirm=["send"])
db    = SQL(url="postgresql://user:pass@host/db",       allow=["schema", "query"])
drive = Drive(oauth_credentials="client_secrets.json",  confirm=True)

agent = Agent(tools=[gmail, db, drive], llm="gemini-3.5-flash")
agent.run("Check unread emails and log any order mentions to the database.")
agent.stop()
```

- **`allow`** — restrict which actions the tool exposes (`["read", "send"]`, `["schema", "query"]`, …).
- **`confirm`** — when human approval is required: `True` (all actions), `False` (none), or a list of specific actions.

**Built-in tools:**

```python
from delfhos import Gmail, SQL, Sheets, Drive, Calendar, Docs, WebSearch, APITool
```

---

## Custom tools

Decorate any Python function with `@tool` and the agent can call it. The docstring and type hints tell the agent how to use it:

```python
from delfhos import Agent, tool

@tool
def calculate_discount(price: float, pct: float) -> float:
    """Return the price after applying a percentage discount."""
    return price * (1 - pct / 100)

agent = Agent(tools=[calculate_discount], llm="gemini-3.1-flash-lite")
agent.run("What is the price of a $120 item with a 15% discount?")
agent.stop()
```

---

## Connect any REST API (APITool)

Point `APITool` at an OpenAPI 3.x spec and every endpoint becomes callable — no custom code:

```python
from delfhos import Agent, APITool

petstore = APITool(
    spec="https://petstore3.swagger.io/api/v3/openapi.json",
    allow=["list_pets", "get_pet_by_id"],
    confirm=["create_pet", "delete_pet"],
)

# Private API with auth — credentials are injected, never seen by the agent
internal = APITool(
    spec="./openapi.yaml",
    base_url="https://api.internal.corp/v1",
    headers={"Authorization": "Bearer sk_..."},
)

agent = Agent(tools=[petstore, internal], llm="gemini-3.5-flash")
agent.run("List all pets and create a new one named 'Buddy'")
```

`headers=`, `params=`, and `path_params=` are injected automatically; `$ref` schemas are resolved; specs are compiled once and cached. Inspect endpoints with `petstore.inspect()`.

---

## Run many tasks at once

A single agent runs tasks **concurrently**. Submit with `submit()` (returns a `task_id` immediately) and poll each one independently — they never interfere:

```python
import time
from delfhos import Agent, Gmail

agent = Agent(tools=[Gmail(oauth_credentials="client_secrets.json")], llm="gemini-3.5-flash")

task_ids = [
    agent.submit("Summarise today's unread emails"),
    agent.submit("Find any pending invoices"),
    agent.submit("Draft a reply to Ana's last email"),
]

pending = set(task_ids)
while pending:
    for tid in list(pending):
        snap = agent.poll(tid)            # state, events, output, cost, tokens
        if snap.is_terminal:
            print(tid, "->", snap.result or snap.error)
            pending.discard(tid)
    time.sleep(0.3)

agent.stop()
```

For a single blocking call use `run()`; inside async code use `await agent.arun(...)`.

---

## Serve an agent over HTTP

Expose an agent as an authenticated HTTP API in one line — call it from any language or service:

```python
from delfhos import Agent, WebSearch

agent = Agent(tools=[WebSearch(llm="gpt-5.4-mini", confirm=False)], llm="gpt-5.4-mini")

agent.serve(host="0.0.0.0", port=8080, api_key="sk-my-secret")
```

| Endpoint              | Purpose                                              |
|-----------------------|------------------------------------------------------|
| `POST /run`           | Body `{"task": "..."}` → `{"task_id": "..."}`        |
| `GET  /tasks/{id}`    | JSON snapshot — state, events, output, cost, tokens  |
| `GET  /health`        | `{"ok": true}` (always public)                       |

```bash
curl -H "Authorization: Bearer sk-my-secret" \
     -X POST localhost:8080/run -H 'content-type: application/json' \
     -d '{"task": "Find this week's AI news"}'
# {"task_id": "..."}

curl -H "X-API-Key: sk-my-secret" localhost:8080/tasks/<task_id>   # poll until is_terminal
```

- **Auth** — pass `api_key` (a string or list of keys) or set `DELFHOS_API_KEY`. Clients send `Authorization: Bearer <key>` or `X-API-Key: <key>`.
- **Fail-closed** — binding to a public interface without a key is refused. Put HTTPS (Caddy/Nginx/Cloudflare) in front in production.
- **Mount it** — `app.mount("/agent", agent.asgi_app(api_key="sk-my-secret"))` to compose with an existing FastAPI app.

---

## Model support

**Cloud providers** — Gemini, OpenAI, or Anthropic:

```python
agent = Agent(tools=[...], llm="gemini-3.5-flash")       # or gemini-3.1-flash-lite, gemini-3.1-pro
agent = Agent(tools=[...], llm="gpt-5.5")                # or gpt-5.4-mini
agent = Agent(tools=[...], llm="claude-sonnet-4-6")      # or claude-opus-4-8
```

**Local & custom models** — `LLMConfig` for any OpenAI-compatible endpoint:

```python
from delfhos import Agent, LLMConfig

# Local Ollama
agent = Agent(tools=[...], llm=LLMConfig(model="llama3.2", base_url="http://localhost:11434/v1"))

# Enterprise vLLM / hosted providers (Groq, Together, …)
agent = Agent(tools=[...], llm=LLMConfig(
    model="meta-llama/Llama-3-70b-chat-hf",
    base_url="https://api.together.xyz/v1",
    api_key="...",
))
```

**Dual-LLM** — pair a fast model for routing with a strong one for code:

```python
agent = Agent(
    tools=[...],
    light_llm=LLMConfig(model="qwen2.5:7b", base_url="http://localhost:11434/v1"),
    heavy_llm="gemini-3.5-flash",
)
```

---

## Memory & interactive chat

Add short-term session memory and long-term semantic memory:

```python
from delfhos import Agent, Chat, Memory

agent = Agent(
    tools=[...],
    llm="gemini-3.5-flash",
    chat=Chat(keep=8, summarize=True, namespace="my_agent"),   # short-term
    memory=Memory(namespace="my_agent"),                        # long-term semantic
)

agent.run_chat()   # interactive terminal session — type /help for commands
```

Semantic memory supports 100+ embedding models (OpenAI, Cohere, Google, Sentence-Transformers, BGE, Jina, Nomic, NV-Embed) and local-first backends via Ollama or Hugging Face. See [EMBEDDING_MODELS_GUIDE.md](https://github.com/Delfhos/delfhos/blob/main/EMBEDDING_MODELS_GUIDE.md).

---

## Automatic cleanup

Use the agent as a context manager and it shuts down on exit:

```python
with Agent(tools=[...], llm="gemini-3.5-flash") as agent:
    agent.run("Summarise last week's sales and email it to the team.")
```

---

For the full API reference and advanced guides, see **[DOCS.md](DOCS.md)** or **[delfhos.com/docs](https://delfhos.com/docs)**.

## License

Apache-2.0
