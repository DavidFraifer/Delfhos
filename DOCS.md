# Delfhos Documentation

> **Version:** 0.6.8 · **License:** Apache-2.0 · **Python:** ≥ 3.9

Delfhos is a Python SDK for building AI agents that use real tools — Gmail, SQL databases, Google Drive, Sheets, Docs, Calendar, web search, REST APIs, and your own custom functions — with clean orchestration and safe, human-in-the-loop execution.

---

## Table of Contents

1. [Tutorials](#tutorials) — Learn by doing
2. [How-to Guides](#how-to-guides) — Solve specific problems
   → [How to control tool permissions with `allow` and `confirm`](#how-to-control-what-a-tool-can-do-with-allow-and-confirm)
   → [How to configure the execution sandbox](#how-to-configure-the-execution-sandbox)
   → [How to pass input files to the agent workspace](#how-to-pass-input-files-to-the-agent-workspace)
   → [How to extract output files from a task result](#how-to-extract-output-files-from-a-task-result)
3. [Reference](#reference) — Complete API documentation
4. [Explanation](#explanation) — Understand how it works

---

---

# Tutorials

*Tutorials are learning-oriented. They are designed to guide you through the experience of building something real with Delfhos for the first time. Follow them in order.*

---

## Tutorial 1 — Your First Agent

This tutorial gets you from zero to a running AI agent in five minutes.

### Step 1: Install Delfhos

```bash
pip install delfhos
```

### Step 2: Set your API key

Delfhos works with Google Gemini, OpenAI, and Anthropic. Create a `.env` file in your project root:

```bash
# .env
GOOGLE_API_KEY=your_gemini_key_here
```

Or export it in your shell:

```bash
export GOOGLE_API_KEY="your_gemini_key_here"
```

### Step 3: Write and run your first agent

Create a file called `hello_agent.py`:

```python
from delfhos import Agent, WebSearch

# Create an agent with web search capability
agent = Agent(
    tools=[WebSearch(llm="gemini-2.0-flash")],
    llm="gemini-2.0-flash",
)

# Run a task
result = agent.run("What are the top 3 AI trends right now?")

print(result.text)
print(f"Cost: ${result.cost_usd:.4f}")
print(f"Duration: {result.duration_ms}ms")

agent.stop()
```

Run it:

```bash
python hello_agent.py
```

You should see a structured answer, cost, and duration printed to the terminal.

### What just happened?

When you called `agent.run(...)`, Delfhos:

1. Sent your task to the LLM for code generation
2. Generated Python code that calls the WebSearch tool
3. Executed that code in an isolated sandbox environment
4. Returned the result to the LLM to compose a final answer
5. Returned a `Response` object with the answer, cost, and timing

---

## Tutorial 2 — Connecting to Gmail

This tutorial walks you through connecting an agent to a real Gmail account so it can read and send emails.

### Step 1: Get OAuth credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or select an existing one)
3. Enable the **Gmail API**
4. Go to **Credentials → Create Credentials → OAuth client ID**
5. Choose **Desktop app**, download the JSON file
6. Save it as `client_secrets.json` in your project folder

### Step 2: Build the agent

```python
from delfhos import Agent, Gmail

# First run will open a browser for OAuth consent
gmail = Gmail(
    oauth_credentials="client_secrets.json",
    allow=["read", "send"],     # Restrict to only these actions
    confirm=["send"],           # Require human approval before sending
)

agent = Agent(
    tools=[gmail],
    llm="gemini-2.0-flash",
)

result = agent.run("Summarize the 5 most recent unread emails in my inbox.")
print(result.text)

agent.stop()
```

On the first run, your browser opens and asks you to authorize Gmail access. After you click **Allow**, Delfhos saves the token at `~/.config/oauth_gmail.json` and re-uses it automatically on all future runs.

### Step 3: Try sending an email (with approval)

```python
result = agent.run("Send a short greeting email to alice@example.com")
```

Because you set `confirm=["send"]`, the terminal pauses and shows:

```
╔══════════════════════════════════╗
║     ACTION APPROVAL REQUIRED     ║
╠══════════════════════════════════╣
║  Tool: gmail.send                ║
║  To:   alice@example.com         ║
╚══════════════════════════════════╝

  > Approve
    Reject
```

Select **Approve** to let the agent proceed.

---

## Tutorial 3 — Custom Tools

This tutorial teaches you how to expose your own Python functions as agent tools using the `@tool` decorator.

### Step 1: Define a simple tool

```python
from delfhos import Agent, tool

@tool
def calculate_discount(price: float, discount_pct: float) -> float:
    """Calculate the final price after applying a percentage discount."""
    return price * (1 - discount_pct / 100)
```

The decorator automatically extracts the function name, docstring, and type hints to create a schema the LLM can understand.

### Step 2: Register and run

```python
agent = Agent(
    tools=[calculate_discount],
    llm="gemini-2.0-flash",
)

result = agent.run("What is the final price of a $250 item with a 15% discount?")
print(result.text)
# → "The final price after a 15% discount is $212.50."
agent.stop()
```

### Step 3: Add error handling

Use `ToolException` to send error messages back to the LLM instead of crashing:

```python
from delfhos import Agent, tool, ToolException

@tool(confirm=False)
def get_user_tier(user_id: str) -> str:
    """Look up a user's subscription tier: free, pro, or enterprise."""
    users = {"u001": "pro", "u002": "enterprise"}
    if user_id not in users:
        raise ToolException(f"User '{user_id}' not found in the system.")
    return users[user_id]
```

When `ToolException` is raised, Delfhos catches it and feeds the message back to the LLM, which can then try a different approach or ask the user for clarification.

### Step 4: Async tools

Tools can be `async`. Delfhos handles both sync and async transparently:

```python
import aiohttp

@tool
async def fetch_price(symbol: str) -> float:
    """Fetch the current stock price for a ticker symbol."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.example.com/price/{symbol}") as r:
            data = await r.json()
            return data["price"]
```

---

## Tutorial 4 — Chat Mode and Memory

This tutorial shows how to build a persistent, context-aware chat agent.

### Step 1: Enable session memory with Chat

```python
from delfhos import Agent, Chat, Gmail

agent = Agent(
    tools=[Gmail(oauth_credentials="client_secrets.json")],
    llm="gemini-2.0-flash",
    chat=Chat(
        keep=10,                          # Keep the last 10 messages
        summarize=True,                   # Auto-compress older messages
        summarizer_llm="gemini-2.0-flash",
    ),
)

# The agent remembers context across multiple run() calls
agent.run("Who emailed me this morning?")
agent.run("Reply to the first one saying I'll follow up tomorrow")

agent.stop()
```

### Step 2: Start an interactive terminal session

```python
agent.run_chat()   # Launches an interactive REPL in your terminal
```

Inside the session you can type naturally. Special commands:

| Command  | Action                                  |
|----------|-----------------------------------------|
| `/help`  | Show available commands                 |
| `/exit`  | Exit the chat session                   |
| `/stop`  | Stop the agent (restarts on next input) |
| `/clear` | Clear the terminal screen               |

### Step 3: Add persistent long-term memory

```python
from delfhos import Agent, Chat, Memory, Gmail

# Persistent memory survives across program restarts
memory = Memory(namespace="alice_support_agent")

# Pre-load facts once
memory.save("""
Primary contact: Alice Chen, alice@acme.com
Company: Acme Corp, Enterprise tier
Account manager: Bob (bob@ourco.com)
Preferred contact: email, not Slack
""")

agent = Agent(
    tools=[Gmail(oauth_credentials="client_secrets.json")],
    llm="gemini-2.0-flash",
    chat=Chat(summarizer_llm="gemini-2.0-flash"),
    memory=memory,
)

agent.run("Draft a check-in email to our primary contact")
# The agent uses memory to know Alice's email without being told again
```

---

---

# How-to Guides

*How-to guides are problem-oriented. They show you how to accomplish a specific goal, assuming you already have basic familiarity with Delfhos.*

---

## How to connect to a SQL database

```python
from delfhos import Agent, SQL

# Option A: connection URL
db = SQL(url="postgresql://user:password@localhost:5432/mydb")

# Option B: individual parameters
db = SQL(
    host="db.example.supabase.co",
    port=5432,
    database="postgres",
    user="postgres",
    password="secret",
    db_type="postgresql",   # or "mysql" / "mariadb"
)

agent = Agent(tools=[db], llm="gemini-2.0-flash")
result = agent.run("How many users signed up last week?")
print(result.text)
agent.stop()
```

**Supported databases:** PostgreSQL, MySQL, MariaDB.

**Available actions:** `schema` (inspect tables), `query` (SELECT), `write` (INSERT/UPDATE/DELETE).

```python
# Restrict to read-only
db = SQL(url="...", allow=["schema", "query"])
```

---

## How to connect to Google Sheets

```python
from delfhos import Agent, SQL, Sheets

sheets = Sheets(oauth_credentials="client_secrets.json")
db = SQL(url="postgresql://...")

agent = Agent(tools=[db, sheets], llm="gemini-2.0-flash")

result = agent.run(
    "Pull last month's revenue by region from the database "
    "and write it to the 'Revenue Q3' sheet, creating it if it doesn't exist."
)
agent.stop()
```

**Available actions:** `read`, `write`, `create`, `format`, `chart`, `batch`.

---

## How to connect to Google Drive

```python
from delfhos import Agent, Drive, Gmail

drive = Drive(
    oauth_credentials="client_secrets.json",
    allow=["search", "get", "create", "update"],   # No delete or share
    confirm=["create", "update"],                   # Approve writes
)

agent = Agent(tools=[drive, Gmail(oauth_credentials="client_secrets.json")], llm="gemini-2.0-flash")

result = agent.run(
    "Find all PDF files in the 'Reports/Q3' folder and email them to finance@company.com"
)
agent.stop()
```

**Available actions:** `search`, `get`, `create`, `update`, `delete`, `list_permissions`, `share`, `unshare`.

---

## How to connect to Google Docs, Calendar, and more

```python
from delfhos import Agent, Docs, Calendar, WebSearch

docs     = Docs(oauth_credentials="client_secrets.json")
calendar = Calendar(oauth_credentials="client_secrets.json")
search   = WebSearch(llm="gemini-2.0-flash")

agent = Agent(
    tools=[docs, calendar, search],
    llm="gemini-2.0-flash",
)

agent.run(
    "Research the latest Python packaging best practices online "
    "and write a summary document called 'Python Packaging Guide'."
)

agent.run(
    "Find a free 30-minute slot this Friday afternoon "
    "and create a calendar event called 'Team Sync'."
)

agent.stop()
```

**Docs actions:** `read`, `create`, `update`, `format`, `delete`.
**Calendar actions:** `list`, `get`, `create`, `update`, `delete`, `respond`.

---

## How to connect to any REST API

`APITool` turns any OpenAPI 3.x specification into a set of callable agent actions. No code generation needed — the compiler reads the spec and registers every endpoint automatically.

```python
from delfhos import Agent, APITool

# From a public OpenAPI spec URL
petstore = APITool(
    spec="https://petstore3.swagger.io/api/v3/openapi.json",
    allow=["list_pets", "get_pet_by_id"],   # Restrict to specific endpoints
    confirm=["add_pet", "delete_pet"],       # Require approval for writes
)

agent = Agent(tools=[petstore], llm="gemini-2.0-flash")
agent.run("List all available pets and show their names")
agent.stop()
```

```python
# From a local spec file with auth headers
internal = APITool(
    spec="./openapi.yaml",
    base_url="https://api.internal.corp/v1",
    headers={"Authorization": "Bearer sk_..."},
)

# With query-param auth (appended to every request URL)
external = APITool(
    spec="https://api.example.com/openapi.json",
    params={"api_key": "my-key"},
)

# With fixed path parameters (substituted into URL templates)
# e.g. spec has paths like /api/{globalCompanyId}/orders
multitenant = APITool(
    spec="https://api.example.com/openapi.json",
    headers={"Authorization": "Bearer sk_..."},
    path_params={"globalCompanyId": "acme-corp"},
    # The LLM never sees globalCompanyId — it's auto-injected into every URL
)
```

### Discover available endpoints before connecting

```python
# Class-level inspect — no Agent needed
print(APITool.inspect(spec="https://petstore3.swagger.io/api/v3/openapi.json"))
# → {"tool": "petstore3", "methods": ["list_pets", "add_pet", ...], "total": 19}

# Verbose mode shows method + path + description
print(APITool.inspect(spec="./openapi.yaml", verbose=True))
```

### Caching compiled specs

For large specs (Stripe, GitHub, etc.) that rarely change, enable the disk cache so the spec is only parsed once:

```python
api = APITool(
    spec="https://api.stripe.com/openapi.json",
    headers={"Authorization": "Bearer sk_live_..."},
    cache=True,   # Saved to ~/delfhos/api_cache/
)
```

### LLM enrichment — improve descriptions automatically

Pass `enrich=True` and an `llm=` model to have an LLM rewrite every endpoint description and infer missing response schemas before the agent runs. The enriched manifest is cached so the LLM is only called once per spec version.

```python
finnhub = APITool(
    spec="https://finnhub.io/static/swagger.json",
    headers={"X-Finnhub-Token": os.environ["FINNHUB_API_KEY"]},
    cache=True,   # Required to persist enriched manifest
    enrich=True,  # Use LLM to improve descriptions
    llm="gemini-2.5-flash",  # Model used for enrichment
)
```

Token usage and cost for enrichment are tracked separately from task cost and appear in the trace summary:

```
║ API ENRICHMENT            1,823ms                         ║
║   Model                   gemini-2.5-flash                ║
║   Endpoints enriched      12                              ║
║   Tokens in/out           1,024 / 487                     ║
║   Cost USD                $0.000312                       ║
╠═══════════════════════════════════════════════════════════╣
║   Setup cost (API enrich) $0.000312                       ║
║   Task cost               $0.004521                       ║
║   Cost USD                $0.004833                       ║
```

On subsequent runs the manifest loads from cache — the setup line shows `$0.000000 (cached)` and no LLM call is made.

### Background response schema sampling

`sample=True` (the default) silently captures the real response structure after each successful API call and saves it to the cache. No LLM, no tokens, zero latency impact. On the next run the agent's view of each endpoint's return type automatically improves.

```python
finnhub = APITool(
    spec="...",
    cache=True,
    sample=True,  # Default — capture real response schemas in background
)
```

Sampled schemas are stored in `~/delfhos/api_cache/{tool}_{hash}/sampled_schemas.json` and are merged into the manifest on every subsequent `compile()` or `load_cache()` call.

---

## How to use local or custom OpenAI-compatible models

Use `LLMConfig` to point Delfhos at any OpenAI-compatible endpoint — local models, open-source servers, or third-party providers.

```python
from delfhos import Agent, LLMConfig

# Local Ollama model
agent = Agent(
    tools=[...],
    llm=LLMConfig(model="llama3.2", base_url="http://localhost:11434/v1"),
)

# LM Studio
agent = Agent(
    tools=[...],
    llm=LLMConfig(
        model="lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF",
        base_url="http://localhost:1234/v1",
    ),
)

# Groq (cloud, OpenAI-compatible)
agent = Agent(
    tools=[...],
    llm=LLMConfig(
        model="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
        api_key="gsk_...",
    ),
)

# Enterprise server with multiple required auth headers
agent = Agent(
    tools=[...],
    llm=LLMConfig(
        model="llama-3-70b",
        base_url="https://llm.corp.internal/v1",
        headers={
            "X-Tenant-ID": "acme-prod",
            "X-User-Token": "tok_abc123",
            "X-Request-Source": "delfhos",
        },
    ),
)

# Mix: cheap local model for prefilter, strong cloud model for generation
agent = Agent(
    tools=[...],
    light_llm=LLMConfig(model="qwen2.5:7b", base_url="http://localhost:11434/v1"),
    heavy_llm="gemini-2.5-flash",
)

# Per-model generation settings (temperature, top_k, max_tokens, etc.)
agent = Agent(
    tools=[...],
    llm=LLMConfig(
        model="gemini-2.5-flash",
        settings={
            "temperature": 0.8,
            "top_k": 40,
            "max_tokens": 1200,
        },
    ),
)

# Pythonic helper form
cfg = LLMConfig(model="gemini-2.5-flash")
cfg.with_settings(temperature=0.8, top_k=40, max_tokens=1200)

agent = Agent(tools=[...], llm=cfg)
```

`LLMConfig` works wherever a model string is accepted: `llm`, `light_llm`, `heavy_llm`, `code_llm`, `vision_llm`.

> **Note on `headers` vs `api_key`:** Use `api_key` for a single bearer token (`Authorization: Bearer ...`). Use `headers` when your server requires additional fields — tenant IDs, session tokens, routing keys, etc. You can use both together: `api_key` sets the `Authorization` header and `headers` adds anything else on top.

> **Note on `settings` keys:** Use Python keys like `top_k` and `max_tokens`. Aliases like `"top-k"` and `"max-tokens"` are also accepted.

> **Provider inference:** If `base_url` is not set, `LLMConfig` infers native provider from the model name (`gemini-*` → Google, `gpt-*`/`o*` → OpenAI, `claude-*` → Anthropic). If `base_url` is set, it uses OpenAI-compatible protocol for custom endpoints.

---

## How to use multiple LLMs for different tasks

```python
from delfhos import Agent, SQL, Gmail

agent = Agent(
    tools=[SQL(url="..."), Gmail(oauth_credentials="...")],
    light_llm="gemini-2.0-flash",        # Fast model for tool routing
    heavy_llm="gemini-2.0-pro",          # Powerful model for code generation
    code_llm="gemini-2.0-pro",           # Override specifically for code tasks
    vision_llm="gemini-2.0-pro",         # Override for image/multimodal tasks
)
```

Rules:
- If you specify only `llm`, it is used for everything.
- `light_llm` and `heavy_llm` must be specified together.
- `code_llm` and `vision_llm` are optional overrides on top of `heavy_llm`.

Task routing map:

| Model field | Used for these tasks | Fallback behavior |
|-------------|----------------------|-------------------|
| `llm` | Simple mode shortcut. Handles all tasks when you do not split models. | Internally sets both `light_llm` and `heavy_llm` to the same model. |
| `light_llm` | Lightweight tasks: tool prefilter/routing (`enable_prefilter=True`), small parsing/classification helpers, and chat summarization when `Chat.summarizer_llm` is not set. | No fallback at config time: it must be provided together with `heavy_llm` (unless you use `llm`). |
| `heavy_llm` | Main reasoning model: Python code generation, retry/fix loops after execution errors, and text-only calls through `llm.call(...)`. | Base default for specialized models. |
| `code_llm` | Code-generation-specific path only (the model that writes tool-execution Python code). | Falls back to `heavy_llm` if not set. |
| `vision_llm` | Image/multimodal analysis (for example `llm.call(file_data=[...], prompt=...)`). | Falls back to `heavy_llm` if not set. |

In short: keep `light_llm` cheap/fast for routing, keep `heavy_llm` strong for reasoning, and override `code_llm` or `vision_llm` only when a specialized model improves those specific workloads.

---

## How to control what a tool can do with `allow` and `confirm`

`allow` and `confirm` are two independent permission layers present on every built-in connection (`Gmail`, `SQL`, `Drive`, etc.) and on the `@tool` decorator. They are separate controls that serve different purposes:

- **`allow`** — defines which actions the agent is *permitted to use at all*. Actions not in the list are hidden from the LLM entirely: it cannot plan them, generate code for them, or call them. This is an enforcement boundary, not a prompt.
- **`confirm`** — defines which actions must be *approved by a human before they execute*. The agent can plan and generate code for these actions, but execution pauses until you approve or reject.

### Accepted values

Both parameters accept the same three forms:

| Value | Meaning |
|-------|---------|
| `None` (default) | All actions available / no approval required |
| `True` | All actions affected (all allowed / all need approval) |
| `False` | None affected (for `confirm`: skip approval entirely) |
| `["action1", "action2"]` | Only the listed actions affected |
| `"action1"` | Shorthand for a single-item list |

### `allow` — restrict what the agent can do

```python
from delfhos import Agent, SQL

# Read-only: the agent can inspect the schema and run SELECTs, but cannot write
db = SQL(url="postgresql://...", allow=["schema", "query"])

agent = Agent(tools=[db], llm="gemini-2.0-flash")
agent.run("How many users signed up last week?")   # OK
agent.run("Delete all rows from the logs table")   # LLM never sees the write action
```

When `allow` is set, the LLM's tool documentation only includes the listed actions. The restricted actions don't exist from the model's perspective.

### `confirm` — require approval before sensitive actions

```python
from delfhos import Agent, Gmail

gmail = Gmail(
    oauth_credentials="client_secrets.json",
    confirm=["send"],   # Reading is automatic; sending pauses for approval
)

agent = Agent(tools=[gmail], llm="gemini-2.0-flash")
agent.run("Summarize my inbox")           # Runs automatically
agent.run("Send a reply to Alice")        # Pauses — terminal prompt appears
```

### Using both together

`allow` and `confirm` compose naturally. A common pattern is to allow only safe actions and require approval on the ones that mutate state:

```python
from delfhos import Agent, Drive, Sheets

drive = Drive(
    oauth_credentials="client_secrets.json",
    allow=["search", "get", "create", "update"],  # delete and share are off-limits
    confirm=["create", "update"],                  # writes need approval
)

sheets = Sheets(
    oauth_credentials="client_secrets.json",
    allow=["read", "write", "create"],
    confirm=["create"],                            # only creating new sheets needs approval
)

agent = Agent(tools=[drive, sheets], llm="gemini-2.0-flash")
```

### Common patterns

```python
# Read-only — no writes, no approval prompts
Gmail(oauth_credentials="...", allow=["read"], confirm=False)

# Full access, approve everything
Drive(oauth_credentials="...", confirm=True)

# Full access, fully autonomous (no approval at all)
SQL(url="...", confirm=False)

# Allow all actions, but approve only destructive ones
Calendar(oauth_credentials="...", confirm=["delete"])
```

### On `@tool` functions

The `confirm` parameter on `@tool` works the same way — `True` (default) means the function will pause for approval before running; `False` skips the prompt:

```python
from delfhos import tool

@tool(confirm=False)          # always runs automatically
def get_account_balance(account_id: str) -> float:
    """Return the current balance for an account."""
    ...

@tool(confirm=True)           # always pauses for approval
def transfer_funds(from_id: str, to_id: str, amount: float) -> bool:
    """Transfer funds between accounts."""
    ...
```

> **Note:** `@tool` functions do not have an `allow` parameter — they are either registered with the agent or not.

---

## How to require human approval before actions

### Default interactive approval (terminal prompt)

```python
from delfhos import Agent, Gmail

gmail = Gmail(
    oauth_credentials="client_secrets.json",
    confirm=["send"],    # Only "send" needs approval; "read" does not
)

agent = Agent(tools=[gmail], llm="gemini-2.0-flash")
agent.run("Send a weekly digest to team@company.com")
# → Terminal prompt appears: Approve / Reject
```

### Custom approval handler

```python
def slack_approval(request):
    """Return True to approve, False to reject, None for default UI."""
    # request.message contains a human-readable description
    if "delete" in request.message.lower():
        return False      # Always auto-reject deletes
    return True           # Auto-approve everything else

agent = Agent(
    tools=[Gmail(oauth_credentials="...", confirm=True)],
    llm="gemini-2.0-flash",
    on_confirm=slack_approval,
)
```

### Programmatic approval (background agents)

```python
agent = Agent(tools=[...], llm="gemini-2.0-flash")
agent.start()

agent.run_async("Draft and send weekly reports")   # Returns immediately

# Later, in a web handler or another thread:
pending = agent.get_pending_approvals()
for req in pending:
    agent.approve(req["request_id"], response="Looks good!")
    # or
    agent.reject(req["request_id"], reason="Wrong recipient")
```

---

## How to run an agent asynchronously

```python
import asyncio
from delfhos import Agent, Gmail

async def main():
    agent = Agent(
        tools=[Gmail(oauth_credentials="client_secrets.json")],
        llm="gemini-2.0-flash",
    )

    result = await agent.arun("Summarize unread emails", timeout=60.0)
    print(result.text)
    agent.stop()

asyncio.run(main())
```

Alternatively, use a context manager for automatic cleanup:

```python
async def main():
    with Agent(tools=[Gmail(oauth_credentials="...")], llm="gemini-2.0-flash") as agent:
        result = await agent.arun("Summarize unread emails")
        print(result.text)
```

---

## How to use two Gmail accounts in one agent

```python
from delfhos import Agent, Gmail

work = Gmail(
    oauth_credentials="work_oauth.json",
    name="work_email",            # Unique name required
)
personal = Gmail(
    oauth_credentials="personal_oauth.json",
    name="personal_email",
)

agent = Agent(tools=[work, personal], llm="gemini-2.0-flash")
agent.run(
    "Forward the invoice from my work inbox to my personal email address."
)
agent.stop()
```

Any built-in connection type can be instantiated multiple times as long as each has a unique `name`.

---

## How to enable tool prefiltering to reduce costs

When you have many tools, prefiltering uses a fast (cheap) LLM to select only the relevant subset before expensive code generation.

```python
from delfhos import Agent, Gmail, Sheets, Drive, SQL, WebSearch

agent = Agent(
    tools=[Gmail(...), Sheets(...), Drive(...), SQL(...), WebSearch(...)],
    light_llm="gemini-2.0-flash",     # Used for prefiltering
    heavy_llm="gemini-2.0-pro",       # Used for code generation
    enable_prefilter=True,            # Activate the filter
)

agent.run("What is the weather in London?")
# Prefilter selects: [WebSearch]  — Gmail/Sheets/Drive/SQL excluded
```

Typical result: ~60% fewer tokens in the code generation prompt.

---

## How to add long-term memory to an agent

```python
from delfhos import Agent, Memory

memory = Memory(
    namespace="crm_agent",
    embedding_model="all-MiniLM-L6-v2",   # Default; ~90 MB download on first use
)

# Populate once (survives restarts)
memory.save("""
Alice Chen — VP Sales, alice@acme.com, Enterprise tier
Bob Torres — Dev Lead, bob@acme.com, Pro tier
Our SLA: Enterprise 2hr response, Pro 8hr response
""")

agent = Agent(
    tools=[...],
    llm="gemini-2.0-flash",
    memory=memory,
)

agent.run("Draft a response to Alice's support ticket")
# Memory retrieves: Alice's role, email, tier, and SLA expectations
```

You can also load memory from a text or markdown file:

```python
memory.add("knowledge_base.md")   # Reads and stores the file contents
```

---

## How to inspect a connection's available actions

```python
from delfhos import Gmail, Drive, APITool

# Class-level (no auth required)
print(Gmail.inspect())

# Instance-level (includes connection details)
gmail = Gmail(oauth_credentials="client_secrets.json")
print(gmail.inspect())
print(gmail.inspect(verbose=True))   # Full action descriptions

# REST API endpoints
print(APITool.inspect(spec="https://petstore3.swagger.io/api/v3/openapi.json"))
print(APITool.inspect(spec="./openapi.yaml", verbose=True))
```

---

## How to configure cost tracking

Delfhos tracks token usage and estimates costs automatically. Pricing is stored in `~/delfhos/pricing.json`, which is created on first run.

Edit it to add new models or update rates:

```json
{
    "_comment": "USD per 1M tokens",
    "models": {
        "gemini-2.0-flash": {
            "input_per_million": 0.10,
            "output_per_million": 0.40
        },
        "gpt-4o": {
            "input_per_million": 2.50,
            "output_per_million": 10.00
        },
        "gpt-*": {
            "input_per_million": 1.00,
            "output_per_million": 4.00
        }
    }
}
```

Wildcards (`gpt-*`) match any model whose name starts with the prefix.

After a run:

```python
result = agent.run("...")
print(f"${result.cost_usd:.5f}")    # Cost for this task
print(agent.usage)                   # Cumulative token counts
```

### Cost Guardrails and Budgets

You can set a hard limit on the amount of money an `Agent` instance can spend.

1. **At Initialization:** Pass `budget_usd` when instantiating the `Agent`. Cost estimations are computed locally against `~/delfhos/pricing.json`.

```python
agent = Agent(
    tools=[...],
    llm="gpt-4o",
    budget_usd=0.50, # Block new tasks if accumulated cost reaches $0.50 USD
)

# Performs multiple calls...
result = agent.run("Perform an expensive multi-step task")

# If the total agent spend reaches the limit, new .run() calls will
# be immediately rejected, raising an AGT-006 error.
print(f"Total spent so far: ${agent.total_cost_usd:.5f}")
```

2. **Dynamic Resets:** If a task runs out of budget or you want to give the agent more allowance mid-execution (or between requests), you can reset the counter or increase the limit:

```python
# Reset the accumulated cost to $0, keeping the current $0.50 limit
agent.reset_budget()

# Reset the accumulated cost to $0 AND assign a new $1.00 limit
agent.reset_budget(1.00)
```

3. **Status Checks:** You can query the current budget status programmatically prior to or after tasks:

```python
status = agent.status()
print(status["budget"]["limit_usd"])      # Configured budget limit
print(status["budget"]["remaining_usd"])  # Limit minus total_cost_usd
print(status["budget"]["is_exhausted"])   # True if remaining <= 0
```

---

## How to pass API keys programmatically

Instead of environment variables, pass keys directly:

```python
agent = Agent(
    tools=[...],
    llm="gemini-2.0-flash",
    providers={
        "google": "GOOGLE_API_KEY_HERE",
        "openai": "OPENAI_API_KEY_HERE",
    },
)
```

---

## How to add a system prompt

```python
agent = Agent(
    tools=[SQL(url="..."), Gmail(oauth_credentials="...")],
    llm="gemini-2.0-flash",
    system_prompt="""
You are a data analyst for Acme Corp.
- Always cite the SQL query you used.
- Prefer charts over raw numbers when sharing results.
- Never email results to external addresses without explicit confirmation.
""",
)
```

The system prompt is injected into every LLM call.

---

## How to configure the execution sandbox

Delfhos executes LLM-generated code in an isolated sandbox. By default it automatically picks the strongest isolation available on your machine.

### Sandbox modes

| Mode | Behaviour |
|------|-----------|
| `"auto"` (default) | Use Docker if available, fall back to local process sandbox |
| `"docker"` | Require Docker — raise an error if Docker is not running |
| `"local"` | Always use the in-process sandbox (current behaviour before v0.6.8) |

```python
from delfhos import Agent, SQL

# Default — auto-detects Docker, falls back gracefully
agent = Agent(tools=[SQL(url="...")], llm="gemini-2.0-flash")

# Force Docker (fails if Docker is not running)
agent = Agent(
    tools=[SQL(url="...")],
    llm="gemini-2.0-flash",
    sandbox="docker",
)

# Pin to local sandbox (no Docker required)
agent = Agent(
    tools=[SQL(url="...")],
    llm="gemini-2.0-flash",
    sandbox="local",
)
```

### Resource limits (Docker mode only)

Override the defaults with `sandbox_config`:

```python
agent = Agent(
    tools=[...],
    llm="gemini-2.0-flash",
    sandbox="docker",
    sandbox_config={
        "memory_limit": "1g",      # Default: "512m"
        "cpu_limit":    2.0,       # Default: 1.0 CPU core
        "timeout":      600,       # Default: 300 seconds
        "network":      False,     # Default: False (no outbound network)
        "pids_limit":   128,       # Default: 64 (fork-bomb protection)
    },
)
```

### What Docker mode enforces

When Docker is available and `sandbox="docker"` or `sandbox="auto"`, each task execution runs in a disposable container with:

- **No network access** — the container cannot make outbound connections (all API calls go through the host via a Unix socket bridge)
- **Read-only filesystem** — the container rootfs is immutable; only `/tmp` (50 MB, `noexec`) and the task upload directory are writable
- **Memory cap** — the kernel kills the process if it exceeds the limit
- **CPU quota** — prevents runaway computation from starving the host
- **PID limit** — prevents fork bombs
- **No Linux capabilities** — `ALL` capabilities dropped; `no-new-privileges` set
- **Unprivileged user** — agent code runs as a non-root `sandbox` user

Even if generated code escapes the Python-level sandbox (e.g. via object introspection), the container boundary contains the damage.

### Building the Docker image

The sandbox image is built automatically the first time a task runs with Docker enabled. To pre-build it manually (recommended for CI or production deployments):

```python
from cortex._engine.core.sandbox.docker_sandbox import build_image

build_image()          # Skips if image already exists
build_image(force=True)  # Rebuild unconditionally
```

The image is version-tagged to match the installed Delfhos version (e.g. `delfhos-sandbox:0.7.0`) so upgrades automatically use a fresh image.

### Checking sandbox status

```python
from cortex._engine.core.sandbox.executor import _docker_available

print("Docker available:", _docker_available())
```

---

## How to pass input files to the agent workspace

Pass a list of absolute host paths via `files=` when constructing the agent. The files are injected into the sandbox as read-only workspace files so the agent's generated code can read them directly.

```python
from delfhos import Agent, SQL

agent = Agent(
    tools=[SQL(url="postgresql://...")],
    llm="gemini-2.0-flash",
    files=[
        "/data/sales_q3.csv",
        "/data/product_catalog.xlsx",
        "/config/mapping.json",
    ],
)

result = agent.run(
    "Read the sales CSV, join it with the product catalog, "
    "and write a summary to the database."
)
agent.stop()
```

**How the paths are exposed to generated code:**

| Sandbox mode | Path seen by the agent |
|---|---|
| `"docker"` (or `"auto"` with Docker) | `/workspace/<filename>` (e.g. `/workspace/sales_q3.csv`) |
| `"local"` | Original host path (e.g. `/data/sales_q3.csv`) |

The exact paths are injected into the code-generation prompt automatically — the LLM knows which files are available and uses the correct path for the active sandbox mode.

Files can be opened with standard Python I/O or through the built-in `files` tool:

```python
# Both work inside generated agent code:
import csv
with open("/workspace/sales_q3.csv") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# Or via the files tool:
data = await files.read("sales_q3.csv")   # → List[Dict] for CSV/Excel
```

> **Important:** Files passed via `files=` are **read-only**. The agent cannot modify them. To produce new files, use `add_to_output_files()` (see the next guide).

---

## How to extract output files from a task result

When the agent needs to return a file (a CSV export, a generated report, a transformed dataset), it calls `add_to_output_files(name, content)` inside the generated code. After the task completes, the files are available on `result.files` as a `{label: host_path}` mapping.

```python
from delfhos import Agent, SQL

agent = Agent(
    tools=[SQL(url="postgresql://...")],
    llm="gemini-2.0-flash",
)

result = agent.run(
    "Query the top 100 customers by revenue last month "
    "and export the data as a CSV file."
)

# Access the generated files
if result.files:
    for label, path in result.files.items():
        print(f"{label}: {path}")
        # → top_customers: /tmp/delfhos_out_abc123/top_customers.csv

agent.stop()
```

**Instructing the agent to produce a file**

Mention the desired output format in your task description. The LLM is pre-instructed to use `add_to_output_files` when it needs to return data too large to print or when a file format is requested:

```python
agent.run("Generate a monthly sales report as an Excel file.")
agent.run("Export all user records to a CSV.")
agent.run("Produce a JSON summary of the API response.")
```

You can also ask for multiple files in one task:

```python
result = agent.run(
    "Export the raw orders to orders.csv and the summary stats to summary.json."
)
for label, path in result.files.items():
    print(f"{label} → {path}")
# → orders → /tmp/.../orders.csv
# → summary → /tmp/.../summary.json
```

**Auto-conversion rules**

The `add_to_output_files` function applies these conversions automatically when the agent code calls it:

| Content type | Output format |
|---|---|
| `str` | Written as-is; extension inferred from the label |
| `bytes` | Written as binary |
| `dict` | Serialized as JSON |
| `list` | JSON, unless the label ends in `.csv`/`.xlsx` and items are dicts — then CSV or Excel |
| pandas `DataFrame` | CSV (`.csv`) or Excel (`.xlsx`) based on the label extension |

**`response.files` structure**

```python
result.files   # Dict[str, str] — {label: absolute_host_path}
```

Keys are the logical labels the agent chose (e.g. `"report"`, `"orders.csv"`). Values are absolute paths to the files on the host machine. Files persist for the lifetime of the process; copy them to a permanent location if you need to keep them.

---

## How to retry on failure

```python
agent = Agent(
    tools=[...],
    llm="gemini-2.0-flash",
    retry_count=3,   # Retry up to 3 times on non-fatal errors
)
```

On each failure, the error message is fed back to the LLM so it can generate corrected code.

---

---

# Reference

*Reference material is information-oriented. It is precise, complete, and structured for lookup rather than learning.*

---

## `Agent`

**Import:** `from delfhos import Agent`

### Constructor

```python
Agent(
    tools:            Optional[List[Union[Connection, Callable, Any]]] = None,
    chat:             Optional[Chat] = None,
    memory:           Optional[Memory] = None,
    llm:              Optional[str] = None,
    light_llm:        Optional[str] = None,
    heavy_llm:        Optional[str] = None,
    code_llm:         Optional[str] = None,
    vision_llm:       Optional[str] = None,
    system_prompt:    Optional[str] = None,
    on_confirm:       Optional[Callable] = None,
    providers:        Optional[Dict[str, str]] = None,
    verbose:          bool = False,
    enable_prefilter: bool = False,
    retry_count:      int = 1,
    sandbox:          str = "auto",
    sandbox_config:   Optional[Dict[str, Any]] = None,
    files:            Optional[List[str]] = None,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tools` | `list` | `None` | Service connections, `@tool` functions, or both |
| `chat` | `Chat` | `None` | Session memory; enables conversation context |
| `memory` | `Memory` | `None` | Persistent semantic memory across runs |
| `llm` | `str` | `None` | Single model for all operations |
| `light_llm` | `str` | `None` | Fast model for prefiltering; requires `heavy_llm` |
| `heavy_llm` | `str` | `None` | Strong model for code generation; requires `light_llm` |
| `code_llm` | `str` | `None` | Override model for code generation specifically |
| `vision_llm` | `str` | `None` | Override model for image/multimodal tasks |
| `system_prompt` | `str` | `None` | Instructions injected into every LLM call |
| `on_confirm` | `callable` | `None` | Custom approval callback `fn(request) → bool \| None` |
| `providers` | `dict` | `None` | API key overrides `{"google": "...", "openai": "..."}` |
| `verbose` | `bool` | `False` | Print full execution traces |
| `enable_prefilter` | `bool` | `False` | Use `light_llm` to pre-select tools |
| `retry_count` | `int` | `1` | Max retries on non-fatal execution errors |
| `sandbox` | `str` | `"auto"` | Execution isolation mode: `"auto"` \| `"docker"` \| `"local"` |
| `sandbox_config` | `dict` | `None` | Resource limit overrides for Docker mode (see [sandbox guide](#how-to-configure-the-execution-sandbox)) |
| `files` | `list[str]` | `None` | Absolute host paths to inject as read-only workspace files. In Docker mode each file is bind-mounted at `/workspace/<filename>`; in local mode the original paths are used. See [input file guide](#how-to-pass-input-files-to-the-agent-workspace). |

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `start` | `() → self` | Initialize and start the agent |
| `stop` | `()` | Shut down and free resources |
| `run` | `(task: str, timeout: float = 60.0) → Response` | Execute task (blocking) |
| `run_async` | `(task: str) → None` | Submit task (background, non-blocking) |
| `arun` | `async (task: str, timeout: float = 60.0) → Response` | Execute task (async/await) |
| `run_chat` | `(timeout: float = 120.0)` | Launch interactive terminal chat |
| `get_pending_approvals` | `() → list[dict]` | List requests awaiting approval |
| `approve` | `(request_id: str, response: str = "Approved") → bool` | Approve a pending request |
| `reject` | `(request_id: str, reason: str = "Rejected") → bool` | Reject a pending request |
| `info` | `() → dict` | Current agent state |
| `get_llm_config_string` | `() → str` | Human-readable LLM configuration |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `agent_id` | `str` | Unique agent identifier |
| `usage` | `TokenUsage` | Cumulative token and cost statistics |
| `chat` | `Chat \| None` | Attached Chat instance |
| `memory` | `Memory \| None` | Attached Memory instance |
| `retry_count` | `int` | Current retry setting |

### Context manager

```python
with Agent(tools=[...], llm="...") as agent:
    agent.run("...")
# agent.stop() called automatically
```

---

## `Response`

Returned by `agent.run()` and `agent.arun()`.

```python
@dataclass
class Response:
    text:       str                    # Final answer text
    status:     bool                   # True = success, False = failure
    error:      Optional[str]          # Error message if status is False
    cost_usd:   Optional[float]        # Estimated USD cost
    duration_ms: int                   # Wall-clock time in milliseconds
    trace:      Any                    # Full execution trace object
    files:      Dict[str, str]         # Output files: {label: absolute_host_path}
```

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str` | Final answer text produced by the agent |
| `status` | `bool` | `True` if the task succeeded, `False` otherwise |
| `error` | `str \| None` | Error message when `status` is `False` |
| `cost_usd` | `float \| None` | Estimated USD cost for this task |
| `duration_ms` | `int` | Wall-clock execution time in milliseconds |
| `trace` | `Any` | Full execution trace object |
| `files` | `Dict[str, str]` | Output files saved during execution. Keys are logical labels (e.g. `"report"`, `"orders.csv"`); values are absolute host paths. Empty dict if no files were produced. See [output file guide](#how-to-extract-output-files-from-a-task-result). |

---

## `@tool` decorator

**Import:** `from delfhos import tool`

### Signature

```python
@tool(
    name:          Optional[str] = None,
    description:   Optional[str] = None,
    handle_error:  Union[bool, str, Callable, None] = True,
    confirm:       bool = True,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | function name | Override the tool name shown to the LLM |
| `description` | `str` | docstring | Override the description |
| `handle_error` | `bool \| str \| callable` | `True` | How to handle `ToolException`: `True` returns the message; a string returns that string; a callable receives the exception and returns a string |
| `confirm` | `bool` | `True` | Require human approval before execution |

### Auto-detected from the function

- **Tool name:** function name (snake_case preserved)
- **Description:** first docstring paragraph
- **Parameters:** Python type annotations including `TypedDict`
- **Return type:** return annotation

### `ToolException`

Raise inside a `@tool` function to send a recoverable error back to the LLM:

```python
from delfhos import ToolException

@tool
def find_order(order_id: str) -> dict:
    """Look up an order by ID."""
    if not order_id.startswith("ORD-"):
        raise ToolException("Order IDs must start with 'ORD-'. Please check the format.")
    ...
```

---

## `Gmail`

**Import:** `from delfhos import Gmail`

```python
Gmail(
    oauth_credentials: Optional[str] = None,    # Path to OAuth JSON file
    service_account:   Optional[str] = None,    # Path to Service Account JSON
    delegated_user:    Optional[str] = None,    # Email to impersonate (SA only)
    allow:             Optional[Union[str, List[str]]] = None,
    confirm:           Union[bool, List[str], None] = True,
    name:              str = "gmail",
    metadata:          Optional[Dict[str, Any]] = None,
)
```

| Action | Description |
|--------|-------------|
| `read` | List and read emails, threads, labels |
| `send` | Compose and send emails with optional attachments |

---

## `SQL`

**Import:** `from delfhos import SQL`

```python
SQL(
    url:      Optional[str] = None,             # Full connection string
    host:     Optional[str] = None,
    port:     Optional[int] = None,
    database: Optional[str] = None,
    user:     Optional[str] = None,
    password: Optional[str] = None,
    db_type:  str = "postgresql",               # "postgresql" | "mysql" | "mariadb"
    allow:    Optional[Union[str, List[str]]] = None,
    confirm:  Union[bool, List[str], None] = True,
    name:     str = "sql",
    metadata: Optional[Dict[str, Any]] = None,
)
```

| Action | Description |
|--------|-------------|
| `schema` | Inspect table schemas and column definitions |
| `query` | Execute SELECT queries |
| `write` | Execute INSERT, UPDATE, DELETE statements |

---

## `Sheets`

**Import:** `from delfhos import Sheets`

```python
Sheets(
    oauth_credentials: Optional[str] = None,
    service_account:   Optional[str] = None,
    delegated_user:    Optional[str] = None,
    allow:    Optional[Union[str, List[str]]] = None,
    confirm:  Union[bool, List[str], None] = True,
    name:     str = "sheets",
    metadata: Optional[Dict[str, Any]] = None,
)
```

| Action | Description |
|--------|-------------|
| `read` | Read cell values and ranges |
| `write` | Write or update cell values |
| `create` | Create new spreadsheets or sheets |
| `format` | Apply formatting (colors, fonts, borders) |
| `chart` | Create charts from data ranges |
| `batch` | Execute multiple operations in one request |

---

## `Drive`

**Import:** `from delfhos import Drive`

```python
Drive(
    oauth_credentials: Optional[str] = None,
    service_account:   Optional[str] = None,
    delegated_user:    Optional[str] = None,
    allow:    Optional[Union[str, List[str]]] = None,
    confirm:  Union[bool, List[str], None] = True,
    name:     str = "drive",
    metadata: Optional[Dict[str, Any]] = None,
)
```

| Action | Description |
|--------|-------------|
| `search` | Search files and folders by name, type, or metadata |
| `get` | Download or read file content |
| `create` | Upload or create files and folders |
| `update` | Update file content or metadata |
| `delete` | Permanently delete files or folders |
| `list_permissions` | List sharing permissions |
| `share` | Add sharing permissions |
| `unshare` | Remove sharing permissions |

---

## `Docs`

**Import:** `from delfhos import Docs`

```python
Docs(
    oauth_credentials: Optional[str] = None,
    service_account:   Optional[str] = None,
    delegated_user:    Optional[str] = None,
    allow:    Optional[Union[str, List[str]]] = None,
    confirm:  Union[bool, List[str], None] = True,
    name:     str = "docs",
    metadata: Optional[Dict[str, Any]] = None,
)
```

| Action | Description |
|--------|-------------|
| `read` | Read document content |
| `create` | Create a new document |
| `update` | Update document text or insert content |
| `format` | Apply formatting (headings, bold, lists) |
| `delete` | Delete a document |

---

## `Calendar`

**Import:** `from delfhos import Calendar`

```python
Calendar(
    oauth_credentials: Optional[str] = None,
    service_account:   Optional[str] = None,
    delegated_user:    Optional[str] = None,
    allow:    Optional[Union[str, List[str]]] = None,
    confirm:  Union[bool, List[str], None] = True,
    name:     str = "calendar",
    metadata: Optional[Dict[str, Any]] = None,
)
```

| Action | Description |
|--------|-------------|
| `list` | List events in a date range |
| `get` | Get details of a specific event |
| `create` | Create a new event with attendees |
| `update` | Update an existing event |
| `delete` | Delete an event |
| `respond` | Accept, decline, or tentatively accept an event |

---

## `WebSearch`

**Import:** `from delfhos import WebSearch`

```python
WebSearch(
    llm:      str,                              # REQUIRED — Gemini or OpenAI model
    api_key:  Optional[str] = None,            # Falls back to env var
    allow:    Optional[Union[str, List[str]]] = None,
    confirm:  Union[bool, List[str], None] = True,
    name:     str = "websearch",
    metadata: Optional[Dict[str, Any]] = None,
)
```

> **Important:** `llm` is required. Only Gemini and OpenAI models are supported. Claude/Anthropic models are not supported for WebSearch.

| Action | Description |
|--------|-------------|
| `search` | Search the web and return summarized results |

---

## `APITool`

**Import:** `from delfhos import APITool`

```python
APITool(
    spec:        str,                              # URL or file path to OpenAPI 3.x spec
    base_url:    Optional[str] = None,            # Override spec's servers[0].url
    headers:     Optional[Dict[str, str]] = None, # HTTP headers injected into every request
    params:      Optional[Dict[str, str]] = None, # Query params injected into every request
    path_params: Optional[Dict[str, str]] = None, # Path params injected into every request URL
    name:        Optional[str] = None,            # Override auto-derived tool name
    allow:       Optional[Union[str, List[str]]] = None,
    confirm:     Union[bool, List[str], None] = True,
    cache:       bool = False,                    # Cache compiled manifest to ~/delfhos/api_cache/
    enrich:      bool = False,                    # Use LLM to improve descriptions/schemas
    llm:         Optional[str] = None,            # Model for enrichment (required if enrich=True)
    sample:      bool = True,                     # Capture real response schemas in background
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `spec` | `str` | — | URL or file path to an OpenAPI 3.x JSON or YAML spec |
| `base_url` | `str` | `None` | Override for the API base URL; auto-extracted from spec if absent |
| `headers` | `dict` | `None` | HTTP headers injected into every request (e.g. `{"Authorization": "Bearer ..."}`, `{"X-API-Key": "..."}`) |
| `params` | `dict` | `None` | Query params appended to every request URL (e.g. `{"api_key": "..."}`) |
| `path_params` | `dict` | `None` | URL path variables injected into every request. Values are substituted into path templates like `/api/{globalCompanyId}/...` and stripped from the agent-visible function signature so the LLM never sees or passes them. |
| `name` | `str` | `None` | Custom label for this connection; auto-derived from spec title/hostname |
| `allow` | `list` | `None` | Restrict which endpoints the agent can use (function names from `inspect()`) |
| `confirm` | `bool \| list` | `True` | Require approval before listed endpoints execute |
| `cache` | `bool` | `False` | Reuse compiled manifest from disk; useful for large specs |
| `enrich` | `bool` | `False` | Run an LLM pass to improve endpoint descriptions and infer response schemas. Cached after first run — zero cost on subsequent runs. Requires `llm=`. |
| `llm` | `str` | `None` | Model used for enrichment (e.g. `"gemini-2.5-flash"`). Only used when `enrich=True`. |
| `sample` | `bool` | `True` | After each successful API call, infer the response schema from real data and persist it to the cache. No LLM, no cost, zero latency impact. |

### Class methods

```python
APITool.inspect(spec: str, verbose: bool = False, base_url: str = None, cache: bool = False) → dict
```

Returns a dict with `tool`, `api`, `methods` (list of function names), and `total`. Pass `verbose=True` for method + path + description.

### Spec limits

By default, up to 100 endpoints are compiled from a spec. Use `allow=` to pick a subset from larger specs (e.g. Stripe, GitHub). The limit is bypassed automatically when `allow=` is set.

### Cache location

| File | Contents |
|------|----------|
| `~/delfhos/api_cache/{tool}_{hash}/manifest.json` | Compiled (and enriched) endpoint manifest |
| `~/delfhos/api_cache/{tool}_{hash}/sampled_schemas.json` | Real response schemas captured from live API calls |

---

## `Chat`

**Import:** `from delfhos import Chat`

```python
Chat(
    keep:           int = 10,
    summarize:      bool = True,
    persist:        bool = False,
    path:           Optional[str] = None,
    namespace:      str = "default",
    summarizer_llm: Optional[str] = None,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `keep` | `int` | `10` | Max messages before auto-summarization; `0` = always summarize |
| `summarize` | `bool` | `True` | Enable automatic message compression |
| `persist` | `bool` | `False` | Save to SQLite (True) or keep in RAM (False) |
| `path` | `str` | `None` | Custom SQLite path; defaults to `~/delfhos/chat/{namespace}.db` |
| `namespace` | `str` | `"default"` | Isolates multiple chat histories |
| `summarizer_llm` | `str` | `None` | LLM for summarization; required when `summarize=True` |

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `append` | `(role: str, content: str)` | Add a message |
| `clear` | `()` | Remove all messages |
| `by_role` | `(role: str) → List[Message]` | Filter messages by role |
| `needs_compression` | `() → bool` | True if message count exceeds `keep` |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `messages` | `List[dict]` | All messages as `{"role": ..., "content": ...}` |
| `summary` | `str \| None` | The current auto-generated summary |

### Iteration and indexing

```python
len(chat)          # Message count
chat[0]            # First message
chat[0:5]          # Slice
for msg in chat:   # Iterate
    ...
```

---

## `LLMConfig`

**Import:** `from delfhos import LLMConfig`

Use `LLMConfig` to configure native providers (Google/OpenAI/Anthropic) and any OpenAI-compatible custom endpoint — local models (Ollama, LM Studio, vLLM), open-source providers (Groq, Together AI, Anyscale), or private enterprise servers. Pass a `LLMConfig` wherever a model string is accepted.

```python
LLMConfig(
    model:    str,                           # Model name as the endpoint expects it
    base_url: Optional[str] = None,          # Base URL of the OpenAI-compatible API
    api_key:  Optional[str] = None,          # API key; falls back to OPENAI_API_KEY env var
    headers:  Optional[Dict[str, str]] = None, # Extra HTTP headers for every request
    settings: Optional[Dict[str, Any]] = None, # Per-model generation params
    provider: str = "auto",                  # auto|google|openai|anthropic
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | `str` | — | Model identifier (e.g. `"llama3.2"`, `"mistral-7b-instruct"`) |
| `base_url` | `str` | `None` | API base URL; defaults to `OPENAI_BASE_URL` env var, then `https://api.openai.com/v1` |
| `api_key` | `str` | `None` | Bearer token; defaults to `OPENAI_API_KEY`. Pass `"local"` for auth-free local servers |
| `headers` | `Dict[str, str]` | `None` | Extra HTTP headers sent with every request. Use for enterprise servers that require tenant IDs, session tokens, or multiple auth values |
| `settings` | `Dict[str, Any]` | `None` | Per-model generation settings applied everywhere this config is used. Supported keys: `temperature`, `top_p`, `top_k`, `max_tokens`, `presence_penalty`, `frequency_penalty`, `stop` |
| `provider` | `str` | `"auto"` | Provider routing mode: `"auto"`, `"google"`, `"openai"`, `"anthropic"` |

### `settings` examples

```python
# Dict style
LLMConfig(
    model="gemini-2.5-flash",
    settings={
        "temperature": 0.8,
        "top_k": 40,
        "max_tokens": 1200,
    },
)

# Custom endpoint style (OpenAI-compatible)
LLMConfig(
    model="llama3.2",
    base_url="http://localhost:11434/v1",
    settings={"temperature": 0.2},
)

# Fluent style
cfg = LLMConfig(model="gemini-2.5-flash")
cfg.with_settings(temperature=0.8, top_k=40, max_tokens=1200)
```

Aliases like `"top-k"` and `"max-tokens"` are normalized automatically.

You can use native model strings directly, or use `LLMConfig` when you want per-model `settings` while still using native providers.

---

## `Memory`

**Import:** `from delfhos import Memory`

```python
Memory(
    guidelines:      Optional[str] = None,
    path:            Optional[str] = None,
    namespace:       str = "default",
    embedding_model: str = "all-MiniLM-L6-v2",
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `guidelines` | `str` | `None` | Preamble prepended to retrieved context |
| `path` | `str` | `None` | Custom SQLite path; defaults to `~/delfhos/memory/{namespace}.db` |
| `namespace` | `str` | `"default"` | Isolates memory across agents or users |
| `embedding_model` | `str` | `"all-MiniLM-L6-v2"` | Any sentence-transformers model for semantic search |

Any model from [sbert.net/docs/pretrained_models.html](https://www.sbert.net/docs/pretrained_models.html) or HuggingFace is accepted. Popular choices:

| Model | Size | Notes |
|-------|------|-------|
| `all-MiniLM-L6-v2` | ~90 MB | Default — good balance of speed and quality |
| `all-mpnet-base-v2` | ~420 MB | Higher quality |
| `nomic-embed-text` | ~270 MB | Instruction-based, auto-detected prefixes |
| `bge-small-en-v1.5` | ~130 MB | BGE family, compact |
| `sentence-transformers/all-MiniLM-L6-v2` | ~90 MB | Full HuggingFace ID also accepted |

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `save` | `(content: str)` | Store one or more facts (split by newline) |
| `add` | `(content: str)` | Store text or read from a `.txt` / `.md` file path |
| `search` | `(query: str, top_k: int = 5, threshold: float = 0.3) → List[Fact]` | Semantic similarity search |
| `retrieve` | `(query: str, top_k: int = 5, threshold: float = 0.3) → str` | Same as `search`, returns a string |
| `context` | `() → str` | All facts for this namespace as a string |
| `clear` | `()` | Delete all facts in this namespace |
| `backfill_embeddings` | `()` | Generate embeddings for any facts missing them |

### `Fact` dataclass

```python
@dataclass
class Fact:
    content:  str        # The fact text
    saved_at: datetime   # When it was stored
    namespace: str       # Memory namespace
```

### Iteration and indexing

```python
len(memory)          # Fact count
memory[0]            # First fact
memory[0:5]          # Slice
for fact in memory:  # Iterate
    ...
```

---

## Error classes

**Import:** `from delfhos import <ErrorClass>` or `from delfhos.errors import <ErrorClass>`

All errors extend `DelfhosConfigError` and display a structured message with an error code and resolution hint.

| Error class | Code prefix | When raised |
|-------------|-------------|-------------|
| `ModelConfigurationError` | `ERR-MODEL-*` | Invalid or missing LLM configuration |
| `AgentConfirmationError` | `ERR-AGENT-*` | Invalid `confirm` or `on_confirm` value |
| `MemorySetupError` | `ERR-MEM-001` | Memory database initialization failure |
| `MemoryRetrievalError` | `ERR-MEM-002` | Embedding-based memory retrieval failed at runtime |
| `ToolExecutionError` | `ERR-TOOL-001` | Unhandled error during tool execution |
| `ToolDefinitionError` | `ERR-TOOL-002` | `@tool` function has an invalid schema |
| `SQLSchemaError` | `ERR-TOOL-003` | SQL schema introspection failed for a connection |
| `EnvironmentKeyError` | `ERR-ENV-*` | Required environment variable missing |
| `ConnectionConfigurationError` | `ERR-CONN-001` | Invalid connection parameters (also raised by `APITool`) |
| `ConnectionFileNotFoundError` | `ERR-CONN-002` | Required credentials file not found |
| `LLMExecutionError` | `ERR-LLM-001` | LLM API call failed |
| `CodeGenerationError` | `ERR-LLM-002` | LLM returned no executable code for the task |
| `PrefilterError` | `ERR-LLM-003` | Prefilter LLM call failed; tool selection unavailable |
| `ConversationCompressionError` | `ERR-LLM-004` | Chat-history summarization/compression failed |
| `SandboxExecutionError` | `ERR-SANDBOX-001` | Generated Python code failed inside the execution sandbox |
| `OptionalDependencyError` | `ERR-REQ-*` | Optional package not installed |
| `ApprovalRejectedError` | `ERR-APPROVAL-*` | Human rejected the approval request |

---

## Supported LLM models

Pass a model name string for native providers, or a `LLMConfig` for any OpenAI-compatible endpoint.

| Family | Examples | Notes |
|--------|---------|-------|
| Google Gemini | `gemini-2.0-flash`, `gemini-2.5-flash`, `gemini-2.0-pro` | Recommended; requires `GOOGLE_API_KEY` |
| OpenAI | `gpt-4o`, `gpt-4o-mini`, `o1`, `o3`, `o4-mini` | Requires `OPENAI_API_KEY` |
| Anthropic Claude | `claude-3-5-sonnet`, `claude-3-haiku` | Requires `ANTHROPIC_API_KEY` |
| Any OpenAI-compatible | `LLMConfig(model=..., base_url=...)` | Ollama, vLLM, Groq, Together AI, LM Studio, etc. |

> Claude models are not supported as the `llm` for `WebSearch`.

> `LLMConfig` requires `pip install openai`.

---

## Environment variables

| Variable | Used by | Description |
|----------|---------|-------------|
| `GOOGLE_API_KEY` | Agent, WebSearch | Google Gemini API key |
| `OPENAI_API_KEY` | Agent, LLMConfig | OpenAI API key (also default for LLMConfig custom endpoints) |
| `ANTHROPIC_API_KEY` | Agent | Anthropic Claude API key |
| `OPENAI_BASE_URL` | LLMConfig | Default base URL for OpenAI-compatible endpoints |

Delfhos loads `.env` files automatically via `python-dotenv`.

---

## File locations

| Path | Purpose |
|------|---------|
| `~/delfhos/pricing.json` | Token pricing configuration (auto-created) |
| `~/delfhos/memory/{namespace}.db` | Persistent Memory SQLite database |
| `~/delfhos/chat/{namespace}.db` | Persistent Chat SQLite database |
| `~/.config/oauth_gmail.json` | Gmail OAuth token cache |
| `~/.config/oauth_sheets.json` | Sheets OAuth token cache |
| `~/.config/oauth_drive.json` | Drive OAuth token cache |
| `~/.config/oauth_docs.json` | Docs OAuth token cache |
| `~/.config/oauth_calendar.json` | Calendar OAuth token cache |

---

## Public API surface

Everything exported from `delfhos`:

```python
from delfhos import (
    # Core
    Agent,
    LLMConfig,

    # Service connections
    Gmail,
    SQL,
    Sheets,
    Drive,
    Docs,
    Calendar,
    WebSearch,
    APITool,

    # Custom tools
    tool,
    ToolException,
    DelfhosToolWarning,

    # Memory
    Chat,
    Memory,
)
```

---

---

# Explanation

*Explanations are understanding-oriented. They discuss the "why" and "how" behind Delfhos's design, helping you build a mental model.*

---

## The two-package architecture

Delfhos is split into two Python packages in the same repository:

- **`delfhos/`** — The public API. Everything a user imports comes from here. It is intentionally thin: it validates inputs, sets up types, and delegates to `cortex`. This separation keeps the public API stable while internal implementation details can evolve.

- **`cortex/`** — The internal engine. It contains the orchestrator, LLM integration, tool execution sandbox, approval manager, connection implementations, and the OpenAPI compiler for REST API tools. Users never import from `cortex` directly.

This design means the internal engine can be improved, refactored, or even replaced without changing how users write their code.

---

## How the orchestration loop works

When you call `agent.run("task")`, the following pipeline executes:

```
1. Memory retrieval
   └── If a Memory is attached, run semantic search against stored facts.
       Top-k facts are injected into the system prompt.

2. Tool prefiltering (optional)
   └── If enable_prefilter=True, the light_llm reads the task and the list
       of available tools, then selects the relevant subset. This reduces
       the number of tool API docs included in the next step.

3. Schema loading (SQL only)
   └── If a SQL connection is in the selected tools, the actual table schemas
       are fetched from the database and included in the code generation prompt.

4. Code generation
   └── The heavy_llm (or code_llm if set) receives:
         - The system prompt
         - Known facts from memory
         - The chat history (if Chat is attached)
         - The task description
         - API documentation for the selected tools
         - The actions allowed by each connection's `allow` list
         - Workspace file paths (if files= was provided)
       It responds with a Python code block.

5. Approval gate (optional)
   └── If any tool has confirm=True (or confirm=[action list]) and the
       generated code calls that action, execution pauses and an approval
       request is created. The agent waits until a human approves or rejects.

6. Sandboxed execution
   └── The generated code runs inside an isolated execution environment.
       If Docker is available (sandbox="auto" or sandbox="docker"), the code
       runs in a disposable container with no network, read-only filesystem,
       memory/CPU caps, and zero Linux capabilities.
       All tool calls (gmail.send, sql.query, etc.) are proxied back to the
       host process via a Unix socket, so API credentials never enter the container.
       Workspace files (from files=) are bind-mounted at /workspace/<filename>:ro.
       Output files written via add_to_output_files() are collected from /output/.
       If Docker is unavailable, the local sandbox is used: restricted builtins,
       import whitelist, and a timeout are enforced in-process.
       A timeout is always enforced regardless of sandbox mode.

7. Retry loop
   └── If execution raises an exception, the error is fed back to the LLM
       for a corrected code generation. This repeats up to retry_count times.

8. Result composition and return
   └── The final output (stdout, return value, or error) is collected.
       Any output files registered via add_to_output_files() are resolved to
       host paths and stored in Response.files.
       Token counts and cost are calculated.
       The result is added to Chat history (if enabled).
       A Response object is returned.
```

---

## How memory retrieval works

Delfhos uses **semantic search** (not keyword search) for memory retrieval:

1. When you call `memory.save("some fact")`, the text is embedded using a Sentence Transformers model and stored in SQLite alongside the original text.
2. When the agent starts a task, the task string is embedded using the same model.
3. Cosine similarity is computed between the task embedding and every stored fact embedding.
4. The top-K facts above a similarity threshold (default 0.3) are returned.
5. These facts are injected into the LLM's system prompt.

This means facts are retrieved based on *meaning*, not exact wording. A task that says "email the VP of Sales" will retrieve facts about "Alice Chen, VP Sales, alice@acme.com" even though neither string appears in the task.

The embedding model runs locally (no API call required). The default model (`all-MiniLM-L6-v2`, ~90 MB) is downloaded from Hugging Face on first use.

---

## How the `allow` and `confirm` permission model works

Delfhos has a two-layer permission system on every tool. The layers run at different points in the execution pipeline and serve fundamentally different purposes.

**Layer 1 — `allow` (compile time, before code generation)**

When `allow` is set, the restricted actions are stripped from the tool's API documentation before it is sent to the LLM. The model never learns those actions exist. It cannot plan them, cannot generate code that calls them, and will not attempt them even if instructed to. This is not a guardrail — it is an information boundary.

This happens at step 4 of the orchestration loop ("Schema loading" → "Code generation"). The LLM only ever sees the actions you have permitted.

**Layer 2 — `confirm` (runtime, before execution)**

When `confirm` is set, the generated code is inspected after the LLM produces it but before it runs. If any call matches a confirmed action, execution is suspended and an approval request is created. The sandboxed execution only begins once a human approves.

This happens at step 5 of the orchestration loop ("Approval gate"). The agent has already decided *what* to do; you are deciding whether it is allowed to *do it now*.

**Why both?**

- Use `allow` to shrink the attack surface permanently: the agent is structurally incapable of calling actions outside the list, regardless of how the task is phrased.
- Use `confirm` for actions that are legitimate but high-stakes: the agent needs the capability (e.g., `send`, `delete`) but a human should review before it fires.
- They compose: `allow=["read", "send"], confirm=["send"]` means the agent can only read and send, and all sends require approval.

## How the approval system works

The approval system is designed to be both developer-friendly and production-ready.

**Granularity:** Approval is configured per-connection (`Gmail(confirm=["send"])`), meaning you can require approval only for destructive or sensitive actions while allowing safe actions to run automatically.

**Three modes:**

1. **Interactive (default):** When the agent pauses, a terminal prompt appears showing the tool name, the action, and a preview of the parameters. The developer selects Approve or Reject.

2. **Custom callback:** `on_confirm=fn` lets you integrate with external systems — Slack, email, a web dashboard — by writing a function that returns `True` (approve), `False` (reject), or `None` (fall back to default UI).

3. **Programmatic:** When using `run_async()`, you poll `agent.get_pending_approvals()` and call `agent.approve()` or `agent.reject()` from your own code (e.g., a web API handler).

**What the LLM sees:** When a request is rejected, the rejection reason is fed back to the LLM as context so it can revise its approach.

---

## How tool code generation works

Delfhos does not call tools through function-calling APIs. Instead, it uses **code generation**: the LLM writes a short Python script that calls the tool library, and Delfhos executes that script in a sandbox.

This approach has several advantages:

- **Composability:** The LLM can write loops, conditionals, list comprehensions, and multi-step logic combining multiple tools in a single generated script.
- **Transparency:** The generated code is human-readable and can be inspected or logged.
- **Retry with context:** When code fails, the error traceback is fed back to the LLM, which often generates a correct fix on the next attempt.
- **Flexibility:** The LLM is not constrained to predefined call patterns; it can use any Python construct to accomplish the task.

The sandbox restricts the execution environment: only the tool library objects are in scope, dangerous builtins are removed, and a timeout is enforced. When Docker is available, the sandbox runs as a disposable container with full OS-level isolation (see [sandbox configuration](#how-to-configure-the-execution-sandbox)).

---

## How the dual-LLM architecture reduces costs

Many tasks involve two distinct cognitive loads:

1. **Routing** — which tools are relevant to this task?
2. **Generation** — what code should those tools execute?

Routing is simple (fast, cheap model is fine). Generation requires deep reasoning and knowledge of the tool APIs (expensive model needed).

By splitting these across a `light_llm` and `heavy_llm`:
- Simple routing is handled cheaply
- The heavy model only sees a small, focused context (thanks to prefiltering)
- Total cost is significantly lower than using a powerful model for everything

The `code_llm` and `vision_llm` overrides let you use specialized models for specific subtasks without changing the main model.

---

## How Chat auto-summarization works

Without summarization, conversation history grows linearly. With it:

1. After each message, Delfhos checks if the message count exceeds `keep`.
2. If it does, the oldest `(count - keep)` messages are extracted.
3. A separate LLM call (using `summarizer_llm`) produces a concise summary.
4. The original messages are discarded; the summary is stored as a special system message.
5. Future LLM calls receive: the summary + the most recent `keep` messages.

This keeps context size bounded at `~keep` messages regardless of conversation length, dramatically reducing token costs in long sessions.

---

## How APITool works

`APITool` connects any REST API to a Delfhos agent through a pipeline with two optional quality layers on top:

1. **Compilation** *(always, no LLM):* The `OpenAPICompiler` reads the OpenAPI 3.x spec (JSON or YAML, local file or URL), resolves all `$ref` pointers, and transforms every operation into a Delfhos-native tool entry. Each entry contains a Python function signature, parameter descriptions, and a compressed API doc for code generation. Large specs are compiled in parallel using a thread pool.

2. **LLM Enrichment** *(optional, `enrich=True`):* After compilation, the `OpenAPICompiler.enrich()` method sends all endpoint descriptions to an LLM in a single call. The LLM rewrites descriptions to be more actionable for an AI agent and infers response schemas for endpoints where the spec left them undocumented. The enriched manifest is written back to the cache — on all subsequent runs the manifest loads from disk and the LLM is never called again, so enrichment cost is incurred exactly once per spec version.

3. **Registration:** Compiled (and optionally enriched) entries are registered into three internal stores — `TOOL_REGISTRY` (for the prefilter LLM), `TOOL_ACTION_SUMMARIES` (for prefilter ranking), and `COMPRESSED_API_DOCS` (for code generation prompts).

4. **Execution:** The `APIExecutor` receives calls from the agent's generated code and maps every argument to the correct HTTP location based on the spec (`path`, `query`, `header`, or `body`). Before sending, it injects the three categories of auth/config values supplied at construction time:
   - `headers` → merged into the request headers
   - `params` → merged into the query string
   - `path_params` → substituted into `{placeholder}` segments in the URL template (URL-encoded automatically)

   The `desc` keyword argument used internally by the approval system is stripped before the request is built. The HTTP call is made via `httpx` with a 30-second timeout and redirect following enabled.

5. **Background Schema Sampling** *(optional, `sample=True`, default):* After each successful API call that returns JSON, a daemon thread infers the exact response schema from the real data using `_infer_schema()` and saves it to `sampled_schemas.json` in the cache directory. On the next compile or cache load, sampled schemas are merged back into the manifest's `response_hint` fields — the agent's knowledge of each endpoint's output improves automatically with use, at zero token cost and zero latency.

### Token tracking and cost attribution

When `enrich=True` is set on any `APITool`, the execution trace separates setup cost from task cost:

- **Setup cost** — tokens spent on LLM enrichment during `Agent` startup. Shown as `$0.000000 (cached)` on subsequent runs.
- **Task cost** — tokens spent on code generation and execution for the actual user task.

Both are visible in the `Trace.summary()` output and accessible on `trace.api_enrichment` (`EnrichmentTrace`) and `trace.total_cost_usd`.

The result: any API with an OpenAPI spec is fully usable as an agent tool with zero hand-written adapter code, progressively better response-schema knowledge, and transparent cost attribution.

---

## How the execution sandbox works

Delfhos uses a layered sandbox with a pluggable backend system. The `SandboxExecutor` selects the strongest isolation available at runtime.

### Two backends

**Local backend (process-level)**

Used when Docker is not available (or `sandbox="local"`). The generated code is compiled and `exec()`'d inside the host Python process with:

- Restricted `__builtins__` — only a safe subset of built-in functions is exposed; `eval`, `exec`, `compile`, `open`, `__import__`, and other dangerous functions are removed or replaced
- Import whitelist — only `asyncio`, `datetime`, `json`, `math`, `pathlib`, `re`, `statistics`, and `time` may be imported; any other `import` raises an error
- Tool library injection — `gmail`, `sql`, `sheets`, etc. are pre-injected as async objects; the LLM code calls them directly
- Timeout enforcement via `asyncio.wait_for()`

**Docker backend (container-level)**

Used when Docker is available (or `sandbox="docker"`). The generated code runs in a disposable container:

```
┌─────────────────── Host Process ────────────────────────┐
│                                                          │
│  Orchestrator ──▶ SandboxExecutor ──▶ DockerSandbox     │
│       ↑                                      │          │
│       │                          Unix Socket │          │
│       │                          (RPC bridge)│          │
│       │                                      ▼          │
│       │                  ┌── Docker Container ──────┐   │
│       │                  │  agent_runner.py          │   │
│       │                  │    exec(agent_code)       │   │
│       │◄─── tool result  │    proxy.gmail.send() ───┼───┘
│       │                  │                           │
│       │                  │  Resource limits:         │
│       │                  │  • No network             │
│       │                  │  • Read-only filesystem   │
│       │                  │  • 512 MB RAM cap         │
│       │                  │  • 1 CPU core             │
│       │                  │  • PID limit 64           │
│       │                  └───────────────────────────┘
└──────────────────────────────────────────────────────────┘
```

The key architectural point: **API credentials never enter the container**. When agent code calls `await gmail.send(...)`, the call travels over a Unix socket to the host process, where the real Gmail library executes it (including any human approval step). The container receives only the serialized result.

This means:
- A container escape cannot exfiltrate OAuth tokens or database credentials
- All existing approval flows work unchanged — the host pauses mid-execution as usual
- The container can be fully network-isolated even though the agent makes API calls

### Backend selection

```python
# At runtime: picks best available
SandboxExecutor(mode="auto")   # Docker → local fallback
SandboxExecutor(mode="docker") # Docker required
SandboxExecutor(mode="local")  # Always in-process
```

The selection is logged: when Docker is unavailable in `"auto"` mode, a warning is emitted (`Docker unavailable — falling back to local backend`) so you can see which isolation level is active.

---

## Permission model philosophy

Every connection has two independent controls:

- **`allow`** — what the agent *can* do. Actions not in this list are invisible to the LLM; it cannot generate code that calls them. This is an absolute restriction.

- **`confirm`** — what the agent must *ask before* doing. Actions in this list are available to the LLM but require human approval before execution. This is a guardrail for sensitive operations.

The typical pattern for a safe deployment:

```python
# Can read anything without asking; must ask before sending
Gmail(oauth_credentials="...", allow=["read", "send"], confirm=["send"])

# Can read and query without asking; cannot write or modify anything
SQL(url="...", allow=["schema", "query"])

# Can do everything except delete; must ask before sharing
Drive(oauth_credentials="...", allow=["search","get","create","update","share"], confirm=["share"])
```

This two-layer model gives you both capability control (what can it do at all?) and safety control (what does it need to ask about?).
