# Delfhos

Delfhos is a Python SDK for building AI agents that use real tools (Gmail, SQL, Drive, MCP, custom functions) with clean orchestration and safe execution.

## Install

```bash
pip install delfhos
```

From source:

```bash
git clone https://github.com/DavidFraifer/delfhos
cd delfhos
pip install -e .
```

## Quick Start

```python
from delfhos import Agent, WebSearch

agent = Agent(
    tools=[WebSearch(llm="gpt-5.4-mini")],
    llm="gemini-3.1-flash-lite-preview",
)

agent.run("What are the top 3 AI trends this week? Keep it short.")
agent.stop()
```

## Core Concepts

- `Agent`: public entry point (`from delfhos import Agent`)
- `tools`: built-in tools (Gmail, SQL, etc), MCP tools, and `@tool` custom functions
- `Chat`: short-term conversation memory (SQLite persisted, requires `chat=Chat(...)` for `run_chat()`)
- `Memory`: long-term semantic memory (SQLite + embeddings)
- `allow`: Action whitelist (`allow=["read", "send"]` restricts to specific actions)
- `confirm`: Approval requirement (`True` = all need approval, `False` = none, `["action"]` = selective)

## Built-in Tools

```python
from delfhos import Gmail, SQL, Sheets, Drive, Calendar, Docs, WebSearch, MCP
```

Examples:

```python
# allow: restrict which actions are available
# confirm: when approval is required (True/False/list of actions)
gmail = Gmail(oauth_credentials="client_secrets.json", allow=["read", "send"], confirm=["send"])
db = SQL(url="postgresql://user:pass@host/mydb", allow=["schema", "query"], confirm=["write"])
drive = Drive(oauth_credentials="client_secrets.json", confirm=True)

agent = Agent(tools=[gmail, db, drive], llm="gemini-3.1-flash-lite-preview")
```

**`allow` parameter:**
- Restricts which actions are available on the tool
- Default: allow all actions
- Examples:
  - Gmail: `allow=["read", "send"]` (prevents other actions)
  - SQL: `allow=["schema", "query"]` (blocks write operations)
  - Sheets: `allow=["read"]` (read-only)

**`confirm` parameter:**
- Controls when human approval is required
- Default: `True` (approve all actions for safety)
- Values:
  - `True`: All actions require approval
  - `False`: No approval needed
  - List: Only specific actions require approval, e.g., `confirm=["send", "delete"]` or `confirm=["write"]`

**Inspect tool capabilities:**
- Class method: `Gmail.inspect()` (all available actions)
- Instance method: `gmail.inspect()` (per-instance connection info)
- Verbose: `gmail.inspect(verbose=True)` (detailed descriptions)

**WebSearch special note:**
- Requires an explicit LLM model: `WebSearch(llm="gemini-3.1-flash-lite-preview")` or `WebSearch(llm="gpt-...")`
- Can be a different model from the main agent LLM
- For parseable outputs, request format in the query (e.g., "Return ONLY JSON: {\"rate\": number}").

## Custom Tools

```python
from delfhos import Agent, tool

@tool
async def calculate_total(price: float, tax: float) -> float:
    return price * (1 + tax)

agent = Agent(
    tools=[calculate_total],
    llm="gemini-3.1-flash-lite-preview",
)
```

## Interactive Chat Session

For synchronous, interactive terminal chat with full conversation history:

```python
from delfhos import Agent, Chat, Gmail

agent = Agent(
    tools=[Gmail(oauth_credentials="client_secrets.json")],
    llm="gemini-3.1-flash-lite-preview",
    chat=Chat(summarizer_llm="gemini-3.1-flash-lite-preview")  # Required for run_chat()
)

agent.run_chat()  # Start interactive terminal session
```

Features:
- Type each message at the `You >` prompt.
- Agent responds with full context from conversation history.
- Commands: `/help`, `/clear`, `/stop`, `/exit`.
- Requires: `chat=Chat(...)` parameter at agent creation.

## Memory (Chat + Long-Term)

```python
from delfhos import Agent, Chat, Memory, WebSearch

agent = Agent(
    tools=[WebSearch(llm="gpt-5.4-mini")],
    chat=Chat(keep=8, summarize=True, namespace="support_agent"),
    memory=Memory(namespace="support_agent"),
    llm="gemini-3.1-flash-lite-preview",
)
```

Default storage paths:
- Chat: `~/delfhos/chat/<namespace>.db`
- Memory: `~/delfhos/memory/<namespace>.db`

Generated task code can persist durable facts with:

```python
await memory.save("User prefers monthly billing", desc="final preference")
```

## Approval and Safety

**How `allow` and `confirm` interact:**

`allow` = which actions are AVAILABLE  
`confirm` = which of those available actions need APPROVAL

Examples:

```python
# Example 1: Send requires approval, read is free
gmail = Gmail(oauth_credentials="oauth.json", allow=["read", "send"], confirm=["send"])
# Agent can: read (no approval), send (approval required)
# Agent cannot: delete, archive, etc.

# Example 2: Read-only, no approval needed
sheets = Sheets(oauth_credentials="oauth.json", allow=["read"], confirm=False)
# Agent can: read (no approval)
# Agent cannot: write, format, create, etc.

# Example 3: All writes need approval
db = SQL(url="postgresql://...", allow=["query", "write"], confirm=["write"])
# Agent can: query (no approval), write (approval required)
# Agent cannot: schema (if not in allow list)

# Example 4: Default—all available actions need approval
drive = Drive(oauth_credentials="oauth.json", confirm=True)  # no allow set = all actions available
# Agent can: all actions, but EACH action requires approval
```

**Agent-level approval handler:**
```python
def my_approval_handler(request):
    # request has: action, tool, brief, reason
    return True  # auto-approve all

agent = Agent(
    tools=[...],
    llm="gemini-3.1-flash-lite-preview",
    on_confirm=my_approval_handler  # Replaces default console selector
)
```

When `on_confirm` is provided:
- Uses your custom approval handler instead of console prompts
- Can return `True`/`False`, `(bool, reason)`, or dict with `{"approved": bool, "response": str}`
- Works with both tool-level `confirm` and agent-level approvals.

## Optional Prefilter

When dealing with many tools, enable tool prefiltering to reduce token costs by ~60%:

```python
agent = Agent(
    tools=[...],
    llm="gemini-3.1-flash-lite-preview",
    enable_prefilter=True  # Filter relevant tools before code generation
)
```

Default: `enable_prefilter=False` (all tools documented in prompts).

## Model Support

Supported model families:
- `gemini-*`
- `gpt-*` (including `o1/o3/o4` style IDs)
- `claude-*`

Example:

```python
agent = Agent(tools=[...], llm="gemini-3.1-flash-lite-preview")
```

## Pricing and Cost (USD)

Delfhos calculates LLM cost in USD from a user-editable pricing file:

- `~/delfhos/pricing.json`

Behavior:
- The file is auto-created on first run.
- Final execution summary always shows total USD cost.
- In verbose mode, each LLM call also shows its individual USD cost.
- Trace exports include total cost and pricing source path.
- If a model is missing in `pricing.json`, Delfhos does not calculate USD cost for that model and logs a warning.

You can edit prices or add new models at any time:

```json
{
    "_comment": "USD per 1M tokens. Edit rates or add models. Wildcards are supported, e.g. gpt-*.",
    "models": {
        "gemini-3.1-flash-lite-preview": {
            "input_per_million": 0.10,
            "output_per_million": 0.40
        },
        "gpt-4o-mini": {
            "input_per_million": 0.15,
            "output_per_million": 0.60
        },
        "claude-3-5-sonnet": {
            "input_per_million": 3.00,
            "output_per_million": 15.00
        },
        "gpt-*": {
            "input_per_million": 1.00,
            "output_per_million": 4.00
        }
    }
}
```

## Error System

Delfhos errors include:
- stable code
- readable message
- fix hint

Example shape:

```text
❌ [ERR-TOOL-001] Delfhos Error
----------------------------------------
Message: Tool 'web_search' failed during execution: network timeout
----------------------------------------
💡 Hint: Review the arguments sent to the tool...
```

Main families include:
- `ERR-TOOL-*`
- `ERR-CONN-*`
- `ERR-ENV-*`
- `ERR-LLM-*`
- `ERR-MCP-*`

## Minimal MCP Example

```python
from delfhos import Agent, MCP

fs = MCP(
    "server-filesystem",
    args=["."],
    allow=["read_file", "write_file"],
)

agent = Agent(tools=[fs], llm="gemini-3.1-flash-lite-preview")
agent.run("List python files and create a short summary file.")
agent.stop()
```

### Inspecting MCP Server Setup

View connection formats and required environment variables:

```python
from delfhos import MCP

github = MCP("server-github")
info = github.inspect()
# Returns:
# - server_name, short_name, version
# - connection_setup: args_format, env_format, headers_format, required_env_keys
# - example commands
print(info)
```

Common required env keys:
- `server-github` → `GITHUB_TOKEN`
- `server-slack` → `SLACK_BOT_TOKEN`
- `server-asana` → `ASANA_TOKEN`
- And 15+ others

## License

Apache-2.0
