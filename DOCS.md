# API Reference

Complete reference for every public class and function in Delfhos.

---

## Agent

```python
from delfhos import Agent
```

The main entry point. Creates an autonomous agent that executes natural-language tasks using your configured tools.

### Constructor

```python
Agent(
    tools        = [...],
    llm          = "gemini-2.0-flash-lite",

    # Advanced model split (use instead of llm)
    light_llm    = None,
    heavy_llm    = None,
    code_llm     = None,
    vision_llm   = None,

    # Memory
    chat         = None,
    memory       = None,

    # Behaviour
    system_prompt   = None,
    on_confirm      = None,
    verbose         = False,
    enable_prefilter = False,
    retry_count     = 1,
    providers       = None,
)
```

| Parameter | Type | Description |
|---|---|---|
| `tools` | `list` | Service tools (`Gmail`, `SQL`, …), `@tool` functions, or `Connection` instances. |
| `llm` | `str` | Single model for all operations. Shorthand for setting all four model roles to the same value. |
| `light_llm` | `str` | Fast model for tool prefiltering. Requires `heavy_llm`. |
| `heavy_llm` | `str` | Stronger model for code generation. Requires `light_llm`. |
| `code_llm` | `str` | Model used specifically for Python code generation. Defaults to `heavy_llm`. |
| `vision_llm` | `str` | Model used for image/multimodal tasks. Defaults to `heavy_llm`. |
| `chat` | `Chat` | Session memory. Keeps the last N messages in context, with optional auto-summarisation. |
| `memory` | `Memory` | Persistent semantic memory across sessions. Automatically creates a `Chat` if not provided. |
| `system_prompt` | `str` | Custom role or instructions injected into every LLM call. |
| `on_confirm` | `Callable[[str], bool]` | Approval callback. Receives a plain-English description of the pending action, returns `True` to approve. |
| `verbose` | `bool` | Print detailed execution traces (generated code, tool calls, timings). |
| `enable_prefilter` | `bool` | Use `light_llm` to pre-select relevant tools before code generation. Default `False`. |
| `retry_count` | `int` | Auto-retry count on execution failure. Default `1` (no retry). |
| `providers` | `dict` | Override API keys: `{"google": "...", "openai": "...", "anthropic": "..."}`. |

### Methods

#### `run(task, timeout=60.0) → Response`

Submit a task and block until it completes.

```python
r = agent.run("Summarise unread emails and log them to the database.")
print(r.text)     # the agent's answer
print(r.status)   # True = success
```

#### `run_async(task) → None`

Submit a task in the background without waiting.

#### `arun(task, timeout=60.0) → Response`

Async version of `run()`. Use inside an `async` function.

```python
r = await agent.arun("Fetch the latest report and email it.")
```

#### `run_chat(timeout=120.0) → None`

Start an interactive terminal chat session. Requires a `Chat` to be passed at construction.

```python
agent = Agent(tools=[...], llm="...", chat=Chat())
agent.run_chat()   # type /help inside the session
```

Terminal commands: `/help`, `/stop`, `/clear`, `/exit`.

#### `stop()`

Release resources (threads, connections). Always call this when you are done, or use the context manager instead.

#### `start() → self`

Explicitly start the agent. Usually not needed — `run()` starts it automatically.

#### `get_pending_approvals() → list`

Return all approval requests waiting for a human decision.

#### `approve(request_id, response="Approved") → bool`

Approve a pending action.

#### `reject(request_id, reason="Rejected") → bool`

Reject a pending action.

#### `info() → dict`

Return the current agent state (running tasks, tools, models).

### Properties

| Property | Description |
|---|---|
| `usage` | Token usage statistics across the agent's lifetime. |
| `chat` | The attached `Chat` instance, or `None`. |
| `memory` | The attached `Memory` instance, or `None`. |
| `agent_id` | Unique string identifier for this agent instance. |
| `retry_count` | Get/set the auto-retry count. |

### Context manager

```python
with Agent(tools=[...], llm="gemini-2.0-flash-lite") as agent:
    agent.run("Archive old reports.")
# agent.stop() called automatically
```

---

## Response

Returned by `agent.run()` and `agent.arun()`.

```python
from cortex._engine.types import Response
```

| Field | Type | Description |
|---|---|---|
| `text` | `str` | The agent's final answer or output. |
| `status` | `bool` | `True` if the task completed successfully. |
| `error` | `str \| None` | Error message if `status` is `False`. |
| `cost_usd` | `float \| None` | Estimated cost in USD for this task. |
| `duration_ms` | `int` | Wall-clock execution time in milliseconds. |
| `trace` | `any` | Execution trace for debugging (tool calls, timings). |

---

## @tool

```python
from delfhos import tool, ToolException
```

Decorate any Python function to make it available as an agent tool.

### Basic usage

```python
@tool
def get_exchange_rate(from_currency: str, to_currency: str) -> float:
    """Return the current exchange rate between two currencies."""
    # ... call an API ...
    return 1.08
```

Rules:
- The **docstring** becomes the tool's description visible to the LLM. Make it clear and specific.
- **Type annotations** are required for all parameters. They are used to build the JSON schema.
- Supported parameter types: `str`, `int`, `float`, `bool`, `list`, `dict`, and `TypedDict` subclasses.

### With options

```python
@tool(confirm=True)
def send_invoice(customer_id: str, amount: float) -> str:
    """Send an invoice email to a customer."""
    ...
```

| Option | Default | Description |
|---|---|---|
| `confirm` | `False` | If `True`, require human approval before every call. |
| `handle_error` | `False` | If `True`, catch all exceptions and return the error string instead of crashing. |

### ToolException — recoverable errors

Raise `ToolException` inside a tool when the error is something the agent can work around:

```python
@tool
def search_product(name: str) -> dict:
    """Look up a product by name."""
    result = db.find(name)
    if not result:
        raise ToolException(f"No product found for '{name}'. Try a shorter search term.")
    return result
```

The exception message is sent back to the LLM, which can adjust its approach and retry. Regular exceptions crash the task.

### TypedDict parameters

```python
from typing import TypedDict

class Address(TypedDict):
    street: str
    city: str
    zip_code: str

@tool
def validate_address(address: Address) -> bool:
    """Check whether a mailing address is valid."""
    ...
```

---

## Built-in tools

Import from `delfhos`:

```python
from delfhos import Gmail, SQL, Sheets, Drive, Calendar, Docs, WebSearch, MCP
```

All built-in tools share two common parameters:

| Parameter | Type | Description |
|---|---|---|
| `allow` | `list[str] \| None` | Whitelist of permitted actions. `None` = all actions allowed. |
| `confirm` | `bool \| list[str]` | `True` = require approval for every action. `False` = never. List = only for those action names. |

---

### Gmail

```python
gmail = Gmail(
    oauth_credentials = "client_secrets.json",  # path to Google OAuth file
    allow   = ["read", "send"],   # restrict to these actions
    confirm = ["send"],           # ask before sending
    name    = "gmail",            # optional label
)
```

Available actions: `read`, `send`.

---

### SQL

```python
db = SQL(
    url     = "postgresql://user:pass@host:5432/mydb",
    allow   = ["schema", "query"],   # read-only
    confirm = ["write"],
)
```

Supported connection strings: PostgreSQL (`postgresql://…`), MySQL (`mysql://…`), SQLite (`sqlite:///path.db`).

Available actions: `schema`, `query`, `write`.

---

### Sheets

```python
sheets = Sheets(
    oauth_credentials = "client_secrets.json",
    allow   = ["read", "write"],
    confirm = ["write"],
)
```

Available actions: `read`, `write`, `create`.

---

### Drive

```python
drive = Drive(
    oauth_credentials = "client_secrets.json",
    allow   = ["read", "upload"],
    confirm = True,   # confirm everything
)
```

Available actions: `read`, `upload`, `download`, `delete`, `move`, `copy`.

---

### Calendar

```python
calendar = Calendar(
    oauth_credentials = "client_secrets.json",
    allow   = ["read", "create"],
    confirm = ["create", "delete"],
)
```

Available actions: `read`, `create`, `update`, `delete`.

---

### Docs

```python
docs = Docs(
    oauth_credentials = "client_secrets.json",
    allow   = ["read", "write"],
    confirm = ["write"],
)
```

Available actions: `read`, `write`, `create`.

---

### WebSearch

```python
search = WebSearch(
    llm   = "gemini-2.0-flash-lite",   # required — model to use for search synthesis
    allow = ["search"],
)
```

`WebSearch` requires an explicit `llm` model string.

**Tip:** Ask for a specific format in your task to get clean results:

```python
agent.run("Find the current EUR/USD rate. Return only the number.")
agent.run("Top 3 Python testing frameworks. Format: 1. name — one sentence.")
```

Available actions: `search`.

---

### MCP (Model Context Protocol)

Connect to any MCP-compatible server:

```python
fs = MCP(
    "server-filesystem",      # server name / command
    args  = ["/home/user"],   # arguments passed to the server process
    allow = ["read_file", "write_file"],
    confirm = ["write_file"],
)
```

```python
agent = Agent(tools=[fs], llm="gemini-2.0-flash-lite")
agent.run("Find all TODO comments across the project and save a report.")
```

---

## Chat

```python
from delfhos import Chat
```

Maintains conversation history across multiple `agent.run()` calls within a session.

```python
chat = Chat(
    keep          = 8,                          # keep last N messages in context
    summarize     = True,                       # auto-compress older messages
    summarizer_llm = "gemini-2.0-flash-lite",  # model used for summarisation
    persist       = False,                      # persist to disk between runs
    path          = "~/.delfhos/chat.db",       # SQLite path (when persist=True)
    namespace     = "my_agent",                 # isolate from other agents
)
```

| Parameter | Default | Description |
|---|---|---|
| `keep` | `8` | Number of recent messages kept verbatim in the LLM context. |
| `summarize` | `False` | When `True`, messages beyond `keep` are summarised rather than dropped. |
| `summarizer_llm` | `None` | Model to use for summarisation. Required when `summarize=True`. |
| `persist` | `False` | Save chat history to a SQLite file so it survives process restarts. |
| `path` | auto | SQLite file path. Defaults to a temporary directory. |
| `namespace` | `"default"` | Namespace for isolating multiple agents' histories. |

---

## Memory

```python
from delfhos import Memory
```

Long-term semantic memory that persists facts across sessions. The agent can store and retrieve relevant context automatically.

```python
memory = Memory(
    namespace = "my_agent",   # isolates memories per agent
)

agent = Agent(
    tools=[...],
    llm="gemini-2.0-flash-lite",
    chat=Chat(keep=8, summarize=True),   # short-term
    memory=Memory(namespace="my_agent"), # long-term
)
```

> **Note:** Passing `memory=` without `chat=` auto-creates a `Chat(keep=8, summarize=True)`.

---

## Approval workflow

### Option 1 — Per-tool, per-action (recommended)

Configure `confirm` on each tool. The agent pauses before the specified actions and calls your `on_confirm` callback:

```python
agent = Agent(
    tools=[
        Gmail(oauth_credentials="...", confirm=["send"]),
        SQL(url="...",                 confirm=["write"]),
    ],
    llm="gemini-2.0-flash-lite",
    on_confirm=lambda brief: input(f"\nApprove: {brief}\n[y/N] ").strip().lower() == "y",
)
```

### Option 2 — Programmatic (async UI, web app)

Poll `get_pending_approvals()` and call `approve()` / `reject()`:

```python
import threading, time

agent = Agent(tools=[Gmail(confirm=["send"])], llm="gemini-2.0-flash-lite")
agent.run_async("Send the weekly report to the team.")

# Check for approvals from another thread / event loop
while True:
    for req in agent.get_pending_approvals():
        print(f"Pending: {req['message']}")
        agent.approve(req["request_id"])
    time.sleep(0.5)
```

### Approval request fields

Each item returned by `get_pending_approvals()` has:

| Field | Description |
|---|---|
| `request_id` | Unique ID — pass to `approve()` or `reject()`. |
| `tool` | Tool name (e.g. `"gmail"`). |
| `method` | Action name (e.g. `"send"`). |
| `message` | Plain-English description of what is about to happen. |
| `context_payload` | Raw parameters the tool was called with. |

---

## Sandbox tools

Zero-config tools for local testing. No API keys or credentials needed.

```python
from delfhos.sandbox import MockEmail, MockDatabase
```

### MockEmail

Behaves exactly like `Gmail` but operates on in-memory dummy data.

Pre-loaded data:
- 2 emails (one from `alice@example.com` about support ticket TCK8843)

```python
MockEmail(confirm=False)
```

### MockDatabase

Behaves exactly like `SQL` but uses an in-memory SQLite database.

Pre-loaded schema and data:
- `users` — Alice Smith, Bob Jones, Charlie Brown
- `orders` — Enterprise License, Support Add-on, Pro License
- `tickets` — TCK8843 (open, Alice), TCK9921 (closed, Bob), TCK9950 (open, Charlie)

```python
MockDatabase(confirm=False)
```

---

## Error handling

### Standardised errors

All Delfhos errors inherit from `DelfhosError` and include:
- An error code (e.g. `ERR-TOOL-001`)
- A human-readable message
- A `resolution` hint

```python
from delfhos.errors import (
    DelfhosError,
    ToolExecutionError,
    ToolDefinitionError,
    ConnectionConfigurationError,
)
```

### In custom tools

```python
@tool
def fetch_record(record_id: str) -> dict:
    """Fetch a record from the external API."""
    resp = api.get(record_id)
    if resp.status_code == 404:
        raise ToolException(f"Record '{record_id}' not found. Verify the ID and try again.")
    if resp.status_code != 200:
        raise ToolExecutionError(tool_name="fetch_record", detail=f"API returned {resp.status_code}")
    return resp.json()
```

---

## Common patterns

### Read-only agent

```python
agent = Agent(
    tools=[
        Gmail(oauth_credentials="...", allow=["read"]),
        SQL(url="...",                 allow=["schema", "query"]),
    ],
    llm="gemini-2.0-flash-lite",
)
```

### Full audit trail with verbose output

```python
agent = Agent(tools=[...], llm="gemini-2.0-flash-lite", verbose=True)
```

### Persistent chat assistant

```python
agent = Agent(
    tools=[Gmail(oauth_credentials="...")],
    llm="gemini-2.0-flash-lite",
    chat=Chat(keep=10, summarize=True, persist=True, namespace="assistant"),
)
agent.run_chat()
```

### Multiple agents, separate namespaces

```python
support_agent = Agent(
    tools=[Gmail(oauth_credentials="support.json"), SQL(url="...")],
    llm="gemini-2.0-flash-lite",
    chat=Chat(namespace="support"),
    memory=Memory(namespace="support"),
    system_prompt="You are a customer support agent. Be concise and helpful.",
)

analytics_agent = Agent(
    tools=[SQL(url="..."), Sheets(oauth_credentials="...")],
    llm="gemini-2.0-flash",
    chat=Chat(namespace="analytics"),
    system_prompt="You are a data analyst. Show your work.",
)
```

### Google OAuth setup

All Google tools accept either a service account or OAuth client credentials:

```python
# Service account (recommended for servers / automation)
Gmail(service_account="sa-key.json", delegated_user="admin@example.com")

# OAuth browser flow (personal accounts / local development)
Gmail(oauth_credentials="client_secrets.json")
```

Download `client_secrets.json` from the [Google Cloud Console](https://console.cloud.google.com/) under **APIs & Services → Credentials → OAuth 2.0 Client IDs**.

On the first run, a browser window opens for consent. The token is cached locally for subsequent runs.
