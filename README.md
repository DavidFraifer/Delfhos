# Delfhos

**Delfhos** is an open-source AI agent SDK. Give it connections to your tools and describe what you want in plain English — Delfhos takes care of the rest.

```python
from delfhos import Agent
from delfhos.tools import Gmail, SQL

gmail = Gmail(oauth_credentials="client_secrets.json")
db    = SQL(url="postgresql://user:pass@host/mydb")

with Agent(tools=[gmail, db]) as agent:
    agent.run("How many users signed up this week? Email a summary to the team.")
```

---

## Install

```bash
pip install delfhos
```

Or from source:

```bash
git clone https://github.com/DavidFraifer/delfhos
cd delfhos
pip install -e .
```

**Requirements:** Python ≥ 3.9, a Gemini API key.

```bash
export GEMINI_API_KEY="your-key-here"
```

---

## Quickstart

```bash
python -m examples.PersistentMemory.memory_demo
```

```python
from delfhos import Agent
from delfhos.tools import WebSearch

with Agent(
    tools=[WebSearch()],
    system_prompt="You are a helpful research assistant.",
) as agent:
    agent.run("What are the top 3 AI trends in 2026? Give a brief summary.")
```

---

## Error Handling

Delfhos uses a unified error system in [delfhos/errors.py](delfhos/errors.py).

All SDK errors include:
1. A stable error code (for logs and support)
2. A clear message with context
3. A fix-oriented hint

Example output shape:

```text
❌ [ERR_TOOL_001] Delfhos Error
----------------------------------------
Message: Tool 'web_search' failed during execution: network timeout
----------------------------------------
💡 Hint: Review the arguments sent to the tool...
```

Common error families:

| Code | Exception | Typical Cause |
|---|---|---|
| `ERR_TOOL_001` | `ToolExecutionError` | Tool runtime failure |
| `ERR_TOOL_002` | `ToolDefinitionError` | Invalid custom tool definition |
| `ERR_CONN_001` | `ConnectionConfigurationError` | Missing/invalid connection config |
| `ERR_CONN_002` | `ConnectionFileNotFoundError` | Credentials file path not found |
| `ERR_ENV_001` | `EnvironmentKeyError` | Missing environment variable |
| `ERR_REQ_001` | `OptionalDependencyError` | Missing optional package |
| `ERR_MCP_001` | `MCPConnectionError` | MCP server start/connect issues |

Catch by base class when you want one handler for all SDK-level failures:

```python
from delfhos.errors import DelfhosConfigError

try:
    agent.run("Send a summary email to the team")
except DelfhosConfigError as exc:
    print(str(exc))  # Includes code + message + hint
```

Notes:
1. Some errors keep compatibility with Python built-ins for existing code:
   - `ToolDefinitionError` is also a `TypeError`
   - `ConnectionConfigurationError` is also a `ValueError`
   - `ConnectionFileNotFoundError` is also a `FileNotFoundError`

---

## Authentication

All Google connections (Gmail, Sheets, Drive, Calendar, Docs) support three auth methods.

### Service Account (recommended for servers)

Download a service account JSON key from [Google Cloud Console](https://console.cloud.google.com/iam-admin/serviceaccounts), then:

```python
from delfhos.connections import GmailConnection

gmail = GmailConnection(
    service_account="path/to/service-account.json",
    delegated_user="admin@company.com",   # impersonate a Workspace user
    actions=["read"],                      # optional: restrict capabilities
)
```

> **Note:** Service accounts require Google Workspace and domain-wide delegation enabled by a Workspace admin.

### OAuth Client Secrets (for personal accounts)

Download a `client_secrets.json` from [Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials):

```python
gmail = GmailConnection(
    oauth_credentials="path/to/client_secrets.json",
    actions=["read", "send"],
)
# First run: opens browser for consent → token cached to ~/.cortex/tokens/
# Subsequent runs: token loaded automatically and refreshed if expired.
```

### Action restrictions & scope mapping

The `actions` parameter controls **what the agent can do** and **what OAuth scopes are requested** — minimal privilege by default:

| Connection | Action | Scope requested |
|---|---|---|
| Gmail | `read` | `gmail.readonly` |
| Gmail | `send` | `gmail.send` |
| Gmail | *(all)* | `gmail.modify` |
| Sheets | `read` | `spreadsheets.readonly` |
| Sheets | `write`, `create` | `spreadsheets` |
| Drive | `search`, `get` | `drive.readonly` |
| Drive | `create`, `update`, `delete`, `share` | `drive` |
| Calendar | `list` | `calendar.readonly` |
| Calendar | `create`, `update`, `delete` | `calendar` |
| Docs | `read` | `documents.readonly` |
| Docs | `create`, `update`, `delete` | `documents` + `drive` |

---

## SQL Authentication

`SQLConnection` supports both full connection URLs and individual parameters.

### Connection URL
```python
from delfhos.connections import SQLConnection
db = SQLConnection(url="postgresql://user:pass@host:5432/dbname")
```

### Individual Parameters
Recommended if your password contains special characters (like `@`) that would otherwise need URL-encoding.

```python
db = SQLConnection(
    host="db.example.co",
    port=5432,
    database="postgres",
    user="postgres",
    password="your-password",
    db_type="postgresql" # or "mysql"
)
```

---

## Built-in Connections

| Connection | Auth | What it does |
|---|---|---|
| `WebSearchConnection` | None | Search the web |
| `GmailConnection` | SA / OAuth | Read and send emails |
| `SQLConnection` | URL | Query PostgreSQL / MySQL databases |
| `SheetsConnection` | SA / OAuth | Read and write Google Sheets |
| `DriveConnection` | SA / OAuth | Upload, organize, and share files |
| `CalendarConnection` | SA / OAuth | Create and manage calendar events |
| `DocsConnection` | SA / OAuth | Create and edit Google Docs |

```python
# Multiple accounts of the same type
work  = GmailConnection(service_account="sa.json", delegated_user="work@co.com", name="work")
inbox = GmailConnection(oauth_credentials="secrets.json", name="personal")

agent = Agent(connections=[work, inbox, db])
```

---

## Supported Models

Delfhos supports multiple LLM providers:

| Provider | Model | Notes |
|---|---|---|
| Google | `gemini-2.5-flash` | Default, fast |
| Google | `gemini-2.5-flash-lite` | Lighter, cheaper |
| Google | `gemini-3-flash-preview` | Preview |
| Google | `gemini-3.1-flash-lite-preview` | Latest lite |
| Inception | `mercury-2` | Diffusion-based, very fast |

```python
agent = Agent(
    connections=[...],
    light_llm="mercury-2",
    heavy_llm="mercury-2",
)
```

> **Note:** Mercury-2 requires an `INCEPTION_AI` API key in your `.env` file.

---

## Agent Options

```python
agent = Agent(
    connections=[...],
    system_prompt="You are a finance assistant.", # optional role description
    confirm="write",                          # deployment-time confirm policy
    on_confirm=my_confirm_callback,             # auto-enables approval callbacks
    validation_mode=True,                      # dry-run, no real writes
    light_llm="gemini-3.1-flash-lite-preview", # fast model for filtering
    heavy_llm="gemini-3.1-flash-lite-preview", # powerful model for code gen
)
```

### Run modes

```python
agent.run_async("Do something")         # async, fire and forget (returns immediately)
agent.run("Do something", timeout=60)   # blocks until done (synchronous)
```

### Context manager (Recommended)

```python
with Agent(tools=[...]) as agent:
    agent.run("Generate the monthly report.")
```
Using the context manager ensures that memory persists correctly when the session exits.

### Default Memory and Chat settings
If you add `Memory` to your agent, a `Chat(keep=8, summarize=True)` instance is automatically configured:

```python
from delfhos import Agent, Memory

# Sensible defaults for chat memory are handled automatically
with Agent(tools=[...], memory=Memory("~/.delfhos/agent_memory.db")) as agent:
    agent.run("Process overdue invoices")
```

### Human approval

```python
with Agent(tools=[...], enable_human_approval=True) as agent:
    agent.run("Delete all files older than 90 days.")

    pending = agent.get_pending_approvals()
    agent.approve(pending[0]["request_id"])   # or agent.reject(...)
```

If you provide `on_confirm=...`, approval is enabled automatically. Use `enable_human_approval=True` when you want manual approve/reject flow without a callback.
Recommended callback return is `bool` (or `(bool, "reason")` for an explicit message).

`confirm` policy is unified across tool types:
- Agent deployment policy: `confirm=["send", "delete"]`
- Tool static nature: pass `kind="send"` in `@tool(...)`
- Hard override: `@tool(confirm=True)` always requires confirmation, regardless of agent policy

---

## Creating Custom Tools

Delfhos makes it very easy to inject your own APIs, scraping scripts, or internal systems as tools. Define functions and decorate them with `@tool`.

```python
from delfhos import Agent, tool

# Define your logic
@tool(kind="read")
async def check_inventory(product_id: str) -> str:
    """Mock checking a product database."""
    return f"Product {product_id} has 42 units in stock."

# Pass it to the agent alongside built-in connections
with Agent(
    tools=[check_inventory],
    system_prompt="You are a warehouse assistant."
) as agent:
    agent.run("How many units of product 12345 do we have?")
```

See **[examples/CustomTools/custom_tool_example.py](examples/CustomTools/custom_tool_example.py)** for a full script using `@tool`.

---

## Adding a Custom Connection

If your tool requires OAuth or deep integration with the internal Cortex engine, follow the structure below and mirror patterns in `cortex/connections/` and `cortex/_engine/tools/`.

In short, you need to create 4 things:

```
cortex/connections/slack.py     ← credentials + config
cortex/tool_docs/slack.py       ← what the LLM knows about this tool
cortex/_engine/tools/slack/     ← execution code (the actual API calls)
```

Then register it in `cortex/tool_docs/__init__.py`, `cortex/connections/__init__.py`, and `cortex/__init__.py`.

For Google services, subclass `GoogleBaseConnection` instead of `BaseConnection` to get service account + OAuth support for free.

---

## Project Structure

```
delfhos/                         ← Public API (import from here)
├── __init__.py                  # Agent + connections re-exports
└── connections/
    └── __init__.py              # All connection classes

cortex/                          ← Internal engine
├── __init__.py
├── cortex.py                    # Cortex class (the agent)
├── google_auth.py               # Google auth: scope mapping, SA/OAuth loaders
│
├── connections/                 # User-facing: one file per service
│   ├── base.py                  # BaseConnection + GoogleBaseConnection
│   ├── gmail.py
│   ├── sql.py
│   └── ...
│
├── tool_docs/                   # LLM prompt documentation for each tool
│   ├── gmail.py                 # (ACTIONS, PYTHON_API, EXAMPLES)
│   └── ...
│
└── _engine/                     # Internal engine (you don't need to touch this)
    ├── agent.py                 # Orchestration loop
    ├── connection.py            # Connection base class + manager
    ├── internal/llm.py          # Multi-provider LLM abstraction
    └── tools/                   # Tool executors (actual API call implementations)

examples/
├── Advanced/                    # Multi-tool and model comparison demos
├── ChatMemory/                  # Chat memory and summarization demos
├── CustomTools/                 # @tool and confirmation policy demos
├── MCPTools/                    # MCP integration demos
├── NativeTools/                 # Built-in Gmail/SQL/WebSearch flows
└── PersistentMemory/            # Persistent memory demos

tests/                           # Unit and integration-style automated tests
```

> **Note:** The `_engine/` directory is the internal implementation. You only need to look in there if you're adding execution code for a new tool.

---

## Publishing

### PyPI package build and validation

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
```

### Upload to PyPI

```bash
# TestPyPI first (recommended)
python -m twine upload --repository testpypi dist/*

# Production PyPI
python -m twine upload dist/*
```

### GitHub release checklist

1. Ensure `pyproject.toml` version matches release tag (for example `v0.4.0`).
2. Commit and push all release changes.
3. Create and push an annotated git tag.
4. Create a GitHub Release from that tag with highlights and migration notes.
5. Validate install from a clean environment: `pip install delfhos==<version>`.

---

## License

[Apache 2.0](LICENSE)
