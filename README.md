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
- `tools`: built-in tools, MCP tools, and `@tool` custom functions
- `Chat`: short-term conversation memory (SQLite persisted)
- `Memory`: long-term semantic memory (SQLite + embeddings)
- `confirm`: action approval policy (`True`, `False`, or list like `["write", "delete"]`)

## Built-in Tools

```python
from delfhos import Gmail, SQL, Sheets, Drive, Calendar, Docs, WebSearch, MCP
```

Examples:

```python
gmail = Gmail(oauth_credentials="client_secrets.json", allow=["read", "send"])
db = SQL(url="postgresql://user:pass@host/mydb", allow=["schema", "query"])
drive = Drive(oauth_credentials="client_secrets.json", allow=["search", "get"])

agent = Agent(tools=[gmail, db, drive], llm="gemini-3.1-flash-lite-preview")
```

Notes:
- Use `allow=[...]` to restrict actions.
- Inspect available methods with `tool.inspect()` or detailed output with `tool.inspect(verbose=True)`.
- `WebSearch` requires an explicit search model: `WebSearch(llm="gemini-..." )` or `WebSearch(llm="gpt-...")`.
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

```python
agent = Agent(
    tools=[...],
    confirm=["write", "delete"],
    llm="gemini-3.1-flash-lite-preview",
)
```

- `confirm` controls which actions require approval.
- `@tool(confirm=True)` enforces approval for that tool.

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

## License

Apache-2.0
