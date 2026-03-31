# Architecture

This document explains how Delfhos works internally, which is useful if you want to contribute, debug unexpected behaviour, or understand why certain design decisions were made.

---

## Execution flow

Every call to `agent.run("...")` goes through four stages:

```
 Your code
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  1. PREFILTER  (optional)                                    │
│     A fast LLM scans the task and selects which tools are   │
│     relevant. Skipped when enable_prefilter=False (default). │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  2. CODE GENERATION                                          │
│     A code LLM receives the task, the selected tools'        │
│     schemas, and any chat history. It writes a self-         │
│     contained async Python script.                           │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  3. SANDBOXED EXECUTION                                      │
│     The generated script runs in an isolated namespace       │
│     (restricted builtins, no arbitrary imports).             │
│     Tool calls inside the script hit real services.          │
│     Approval gates block destructive actions until a human   │
│     approves or rejects them.                                │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  4. RESULT / RETRY                                           │
│     stdout + return value become the task result.            │
│     On failure the error is fed back to stage 2 for         │
│     auto-retry (controlled by retry_count, default 1).       │
└─────────────────────────────────────────────────────────────┘
```

---

## Package layout

Delfhos is split into two layers that are versioned and published together:

```
delfhos/        Public SDK — everything you import in your own code
cortex/         Internal engine — orchestration, LLM calls, tool clients
```

**Why two layers?**

- `delfhos` has minimal dependencies (stdlib + a few utils). You can import `tool`, `ToolException`, `Chat`, or `Memory` without pulling in the full AI stack.
- `cortex` carries the heavy dependencies (google-genai, rich, sentence-transformers, …). It is loaded lazily — only when `Agent` is first accessed.

### delfhos/ (public API)

| Path | What it does |
|---|---|
| `delfhos/__init__.py` | Re-exports `Agent`, `tool`, service tools, `Chat`, `Memory` |
| `delfhos/tool.py` | `@tool` decorator and `ToolException` |
| `delfhos/errors.py` | Standardised error classes with codes and resolution hints |
| `delfhos/memory/` | `Chat` (session) and `Memory` (persistent) |
| `delfhos/tools/` | Lazy-loading stubs for `Gmail`, `SQL`, `Drive`, … |
| `delfhos/sandbox/` | `MockEmail` and `MockDatabase` — zero-config test tools |

### cortex/ (internal engine)

| Path | What it does |
|---|---|
| `cortex/cortex.py` | `Cortex` class — the `Agent` alias developers use |
| `cortex/_engine/agent.py` | Lifecycle management, thread pool, approval manager |
| `cortex/_engine/core/orchestrator.py` | Coordinates the four execution stages |
| `cortex/_engine/core/python_executor.py` | Sandboxed Python runner |
| `cortex/_engine/internal/llm.py` | Unified LLM client (Gemini / OpenAI / Anthropic) |
| `cortex/_engine/tools/tool_libraries.py` | Python API wrappers exposed inside the sandbox |
| `cortex/_engine/tools/gmail/` | Gmail client and tool handler |
| `cortex/_engine/tools/sql/` | SQL client and tool handler |
| `cortex/connections/` | `BaseConnection` and per-service connection classes |
| `cortex/tool_docs/` | Markdown tool documentation injected into LLM prompts |

---

## Key concepts

### Connection vs Tool

A **Connection** is a configured, authenticated link to one service instance (e.g. "my work Gmail account"). A **Tool** is the abstract capability (Gmail read/send). Multiple connections of the same tool type can coexist.

```python
# One connection
gmail = Gmail(oauth_credentials="work.json", name="work_gmail")

# Two connections of the same type
personal = Gmail(oauth_credentials="personal.json", name="personal_gmail")
work     = Gmail(oauth_credentials="work.json",     name="work_gmail")

agent = Agent(tools=[personal, work], llm="...")
```

### Sandbox execution model

The generated Python script runs inside `PythonExecutor._execute_async`. The namespace it gets:

- Safe builtins: `print`, `int`, `str`, `list`, `dict`, `re`, `json`, `datetime`, `math`, `asyncio`, …
- Tool libraries: `gmail`, `sql`, `sheets`, `drive`, `calendar`, `docs`, `files`, `llm`, `websearch`
- No filesystem access, no arbitrary imports, no network (except through tool calls)

Allowed imports at runtime: `asyncio`, `datetime`, `json`, `math`, `pathlib`, `re`, `statistics`, `time`.

### Approval gates

When a tool or action is configured with `confirm=True` (or a list of action names), the executor pauses before that call and emits an approval request. The agent waits until `approve()` or `reject()` is called — either by your `on_confirm` callback or manually via `agent.approve(request_id)`.

### ToolException vs regular exceptions

- **`ToolException`** — raised inside a `@tool` function to signal a *recoverable* error. The message is sent back to the LLM, which can adjust its approach and retry.
- **Regular exception** — treated as a task failure. The error is reported and execution stops (unless `retry_count > 1`).

### light_llm / heavy_llm split

When you set both `light_llm` and `heavy_llm`:

| Role | Uses |
|---|---|
| `light_llm` | Tool prefiltering (fast, low cost) |
| `heavy_llm` | Code generation (stronger, higher quality) |
| `code_llm` | Code generation override (defaults to `heavy_llm`) |
| `vision_llm` | Image / multimodal analysis (defaults to `heavy_llm`) |

Setting `llm="..."` is shorthand for setting all four to the same model.

---

## Data flow through a tool call

```
Sandbox script
  │  await gmail.read(query="is:unread")
  ▼
GmailLibrary.read()          # cortex/_engine/tools/tool_libraries.py
  │  builds action dict
  ▼
ToolLibraryBase._execute_tool()
  │  checks allow list, triggers approval if needed
  ▼
gmail_tool_unified()         # cortex/_engine/tools/gmail/gmail_tool_unified.py
  │  (or sandbox interceptor for MockEmail)
  ▼
GmailClient                  # cortex/_engine/tools/gmail/gmail_client.py
  │  calls Google API
  ▼
structured result returned up the chain
```

---

## Adding a new built-in tool

1. Create `cortex/connections/mytool.py` — subclass `BaseConnection`, set `TOOL_NAME` and `ALLOWED_ACTIONS`.
2. Create `cortex/_engine/tools/mytool/` — implement the tool handler function.
3. Add a library class in `cortex/_engine/tools/tool_libraries.py` — async methods that the generated code can call.
4. Add tool docs in `cortex/tool_docs/mytool.py` — Markdown injected into LLM prompts so it knows how to use the tool.
5. Expose in `delfhos/tools/__init__.py` and `delfhos/__init__.py`.
