# Tool System Architecture (v0.6+)

Delfhos provides a unified tool system supporting four tool types: **Native Tools**, **REST APIs (APITool)**, **MCP Servers**, and **Custom Functions**.

## Overview

| Tool Type | Source | Compilation | Runtime | Use Cases |
|-----------|--------|-------------|---------|-----------|
| **Native** | Hand-coded | Manual (Python) | Direct client calls | Gmail, Drive, Sheets, SQL |
| **APITool** | OpenAPI spec | Deterministic (no LLM) | HTTP requests | Any REST API (Stripe, custom endpoints) |
| **MCP** | MCP server | Deterministic (no LLM) | JSON-RPC calls | Filesystem, GitHub, Slack, etc. |
| **Custom (@tool)** | Python function | Manual (function signature) | Direct call | Domain-specific logic |

## Tool Registration & Compilation Pipeline

### 1. **Native Tools** (Gmail, SQL, Drive, etc.)

**Implementation:** Hand-written Python clients + tool_docs

```python
from delfhos import Agent, Gmail, Drive

gmail = Gmail(oauth_credentials="client_secrets.json", allow=["read", "send"])
agent = Agent(tools=[gmail], llm="gemini-2.5-flash")
```

**Key files:**
- `cortex/connections/{gmail,sql,sheets,drive}.py` — connection classes
- `cortex/_engine/tools/{gmail,sql,sheets}/` — client implementations
- `cortex/tool_docs/{gmail,sql,sheets}.py` — API documentation for code generation

---

### 2. **REST APIs (APITool)** — NEW in v0.6

**Implementation:** Deterministic OpenAPI spec → Python namespace compilation

```python
from delfhos import Agent, APITool

petstore = APITool(
    spec="https://petstore3.swagger.io/api/v3/openapi.json",
    allow=["list_pets", "get_pet_by_id"],
)
agent = Agent(tools=[petstore], llm="gemini-2.5-flash")
agent.run("List all pets")
```

**Architecture:**

```
OpenAPI Spec (JSON/YAML)
    ↓
OpenAPICompiler._compile_operation() [deterministic]
    ↓ (for each operation)
ToolActionSpec + Python signature
    ↓
TOOL_REGISTRY (for prefilter)
COMPRESSED_API_DOCS (for code gen)
internal_tools (for sandbox execution)
    ↓
APIExecutor.call()
    ↓
HTTP request (httpx)
    ↓
JSON/text response
```

**Key files:**
- `cortex/_engine/api/compiler.py` — `OpenAPICompiler`: parses spec, resolves `$ref`, builds manifest
- `cortex/_engine/api/executor.py` — `APIExecutor`: maps Python calls → HTTP requests
- `cortex/connections/api.py` — `APITool`: user-facing API with `.inspect()`

**Why no LLM?**
OpenAPI specs are machine-readable, fully structured descriptions of every endpoint. Compilation is **deterministic** — each operation becomes exactly one action with its exact parameters. This is identical to how MCP works.

**Features:**
- **Path parameters:** `/pets/{petId}` → `petId: string` parameter
- **Query parameters:** Detected and typed from schema
- **Request body:** Flattened into function parameters or `body: dict`
- **Auth headers/params:** Injected into every request
- **$ref resolution:** Handles nested schemas and component references
- **Enum support:** Converts `"enum": ["val1", "val2"]` into type hints
- **Caching:** Compiled manifests cached to `~/delfhos/api_cache/{hash}/`

**Example: Petstore**

```python
api = APITool(spec="https://petstore3.swagger.io/api/v3/openapi.json")
api.inspect()  # Shows: list_pets, create_pet, show_pet_by_id, delete_pet, ...

# In agent-generated code:
pets = await petstore.list_pets(limit=10)
new_pet = await petstore.create_pet(name="Fluffy", tag="cat")
```

---

### 3. **MCP Servers**

**Implementation:** Deterministic JSON-RPC tool listing → Python namespace compilation

```python
from delfhos import Agent, MCP

github = MCP("server-github", env={"GITHUB_TOKEN": "ghp_..."})
agent = Agent(tools=[github], llm="gemini-2.5-flash")
```

**Key files:**
- `cortex/_engine/mcp/compiler.py` — `MCPCompiler`: introspects server, builds manifest
- `cortex/_engine/mcp/executor.py` — `MCPExecutor`: maps Python calls → JSON-RPC tools/call
- `cortex/connections/mcp.py` — `MCP`: user-facing API with `.inspect()`

---

### 4. **Custom Functions (@tool)**

**Implementation:** Python function signature → manual tool definition

```python
from delfhos import tool, Agent

@tool
def calculate_discount(price: float, pct: float) -> float:
    """Return price after applying a percentage discount."""
    return price * (1 - pct / 100)

agent = Agent(tools=[calculate_discount], llm="gemini-2.5-flash")
```

**Key files:**
- `delfhos/tool.py` — `@tool` decorator, parameter extraction via `inspect`

---

## Compilation at Agent Startup

When you call `agent.start()` or `agent.run()`, the Agent._configure_tools() method:

1. **Detect compilation-required tools** via `hasattr(tool, "compile")`
   - APITool instances
   - MCP instances
   - Any other Connection with compile()

2. **Run compilation** to introspect and register:
   ```python
   # cortex/_engine/agent.py, line ~357
   if hasattr(tool, "compile"):
       tool.compile()
   ```

3. **Register into engine registries:**
   - `TOOL_REGISTRY` — action names/descriptions for prefilter LLM
   - `COMPRESSED_API_DOCS` — parameter hints for code generation LLM
   - `internal_tools` — Python namespace for sandbox execution

4. **Add connection to orchestrator** for approval workflows

---

## Tool Inspection

All modern tools support `.inspect()` to see available actions **without credentials**.

```python
# Class-level (no instance needed)
print(APITool.inspect(spec="https://api.example.com/openapi.json"))
print(MCP.inspect(server="server-github", env={"GITHUB_TOKEN": "..."}))

# Instance-level
api = APITool(spec="...", auth={...})
print(api.inspect())          # compact: endpoint names
print(api.inspect(verbose=True))  # detailed: methods, paths, descriptions
```

**Output format:**

```
📋 Tool: petstore
======================================================================
🔐 Allowed: all

  1. list_pets
     List all pets available in the petstore.
     
  2. create_pet
     Create a new pet.
     
  3. show_pet_by_id
     Get details for a specific pet by ID.

======================================================================
Total: 3 actions | Auth: none
```

---

## Tool Registration Internals

### TOOL_REGISTRY

Maps tool names to `ToolCapability` objects (for prefilter LLM):

```python
TOOL_REGISTRY = {
    "gmail": ToolCapability(
        tool_name="gmail",
        actions=[
            ToolActionSpec("READ", "Search/read emails", {...}),
            ToolActionSpec("SEND", "Send emails", {...}),
        ]
    ),
    "petstore": ToolCapability(...),  # from APITool
    "github": ToolCapability(...),     # from MCP
}
```

### COMPRESSED_API_DOCS

Compact API documentation for code generation (injected into code-gen prompts):

```python
COMPRESSED_API_DOCS = {
    "gmail:READ": "await gmail.read(max_results=10, query='is:unread') -> List[email_obj]",
    "petstore:list_pets": "await petstore.list_pets(limit: int = None) -> List[Pet]",
    "github:create_issue": "await github.create_issue(repo: str, title: str, body: str) -> Issue",
}
```

### internal_tools

Python callables (functions or tool namespaces) imported in sandbox execution:

```python
internal_tools = {
    "gmail": gmail_tool,                    # async function
    "petstore": APIToolNamespace(...),      # namespace with attribute access
    "github": MCPToolNamespace(...),        # namespace with attribute access
}
```

---

## Allow & Confirm Policies

All tools support action filtering and approval workflows:

```python
# Native tool
gmail = Gmail(oauth_credentials="...", allow=["read"], confirm=["send"])

# APITool
api = APITool(
    spec="https://api.stripe.com/v1/openapi.json",
    allow=["list_customers", "create_charge"],
    confirm=["create_charge", "delete_customer"],
)

# MCP
github = MCP("server-github", allow=["search"], confirm=["create_issue"])
```

**Policy resolution:**
1. Tool-level `confirm` (if set) — hard override
2. Agent-level `confirm` (Agent(..., confirm=["send"])) — deployment policy
3. Per-connection `confirm` — connection default

---

## Summary

| Component | Purpose | Input | Output | Deterministic? |
|-----------|---------|-------|--------|---|
| **OpenAPICompiler** | Parse OpenAPI spec, extract operations | Spec URL/file | Manifest dict | ✓ Yes |
| **MCPCompiler** | Introspect MCP server | Running server | Manifest dict | ✓ Yes |
| **APIExecutor** | Map Python calls → HTTP | Function call + manifest | HTTP response | ✓ Yes |
| **MCPExecutor** | Map Python calls → JSON-RPC | Function call + manifest | RPC response | ✓ Yes |
| **@tool decorator** | Extract Python function signature | Function + docstring | Parameter schema | ✓ Yes |

All compilation paths are **deterministic** (no LLM involved). This ensures fast startup, predictable behavior, and no hallucination risk.
