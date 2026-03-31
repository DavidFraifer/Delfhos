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
    llm="gemini-2.0-flash-lite",
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

agent = Agent(tools=[calculate_discount], llm="gemini-2.0-flash-lite")
agent.run("What is the price of a $120 item with a 15% discount?")
agent.stop()
```

---

## Built-in tools

```python
from delfhos import Gmail, SQL, Sheets, Drive, Calendar, Docs, WebSearch, MCP
```

```python
gmail = Gmail(oauth_credentials="client_secrets.json", allow=["read", "send"], confirm=["send"])
db    = SQL(url="postgresql://user:pass@host/db",       allow=["schema", "query"])
drive = Drive(oauth_credentials="client_secrets.json",  confirm=True)

agent = Agent(tools=[gmail, db, drive], llm="gemini-2.0-flash-lite")
agent.run("Check unread emails and log any order mentions to the database.")
agent.stop()
```

**`allow`** — restrict which actions are available on the tool (`["read", "send"]`, `["schema", "query"]`, …).  
**`confirm`** — when human approval is required: `True` (all), `False` (none), or a list of specific actions.

---

## Interactive chat

```python
from delfhos import Agent, Chat, Gmail

agent = Agent(
    tools=[Gmail(oauth_credentials="client_secrets.json")],
    llm="gemini-2.0-flash-lite",
    chat=Chat(summarizer_llm="gemini-2.0-flash-lite"),
)

agent.run_chat()  # starts a terminal session — type /help for commands
```

---

## Memory

```python
from delfhos import Agent, Chat, Memory

agent = Agent(
    tools=[...],
    llm="gemini-2.0-flash-lite",
    chat=Chat(keep=8, summarize=True, namespace="my_agent"),    # short-term
    memory=Memory(namespace="my_agent"),                         # long-term semantic
)
```

---

## MCP servers

```python
from delfhos import Agent, MCP

fs = MCP("server-filesystem", args=["."], allow=["read_file", "write_file"])
agent = Agent(tools=[fs], llm="gemini-2.0-flash-lite")
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

Pass any model string from Gemini, OpenAI, or Anthropic:

```python
# Gemini
agent = Agent(tools=[...], llm="gemini-2.0-flash-lite")
agent = Agent(tools=[...], llm="gemini-2.0-flash")

# OpenAI
agent = Agent(tools=[...], llm="gpt-4o-mini")
agent = Agent(tools=[...], llm="gpt-4o")

# Anthropic
agent = Agent(tools=[...], llm="claude-3-5-haiku-latest")
agent = Agent(tools=[...], llm="claude-3-5-sonnet-latest")
```

Use `light_llm` + `heavy_llm` to split fast prefiltering from heavier code generation:

```python
agent = Agent(
    tools=[...],
    light_llm="gemini-2.0-flash-lite",   # fast, cheap — for tool selection
    heavy_llm="gemini-2.0-flash",         # stronger — for code generation
)
```

---

## Context manager

The agent cleans up automatically when used as a context manager:

```python
with Agent(tools=[...], llm="gemini-2.0-flash-lite") as agent:
    agent.run("Summarise last week's sales and email it to the team.")
```

---

For the full API reference and advanced guides see [DOCS.md](DOCS.md) or **[delfhos.com/docs](https://delfhos.com/docs)**.

## License

Apache-2.0
