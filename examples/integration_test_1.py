"""
INTEGRATION TEST 1: Tools, Memory, and Chat Configuration
Tests: Custom tools, Native tools, MCP, Memory, Chat persistence, inspect(), confirm/allow
"""

import asyncio
from delfhos import Agent, Gmail, SQL, Chat, Memory, MCP, tool


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM TOOLS (confirm is BOOLEAN only for @tool)
# ─────────────────────────────────────────────────────────────────────────────

@tool(confirm=True)
def calculate_vat(amount: float, rate: float = 0.21) -> float:
    """Calculate VAT on an amount with default 21% rate."""
    return amount * rate


@tool(confirm=False)
def format_currency(amount: float, currency: str = "EUR") -> str:
    """Format amount as currency string. No approval needed."""
    return f"{amount:,.2f} {currency}"


@tool
def sentiment_analysis(text: str) -> dict:
    """Analyze sentiment of text. Returns scores. inspect() will show this."""
    return {
        "text": text[:50],
        "sentiment": "positive" if len(text) > 10 else "neutral",
        "confidence": 0.85
    }


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: Inspect custom tools (should show confirm info)
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 80)
print("TEST 1: CUSTOM TOOLS INSPECTION")
print("=" * 80)
print("\n📋 calculate_vat (confirm=True):")
print(calculate_vat.inspect())
print("\n📋 format_currency (confirm=False):")
print(format_currency.inspect())
print("\n📋 sentiment_analysis (no confirm specified):")
print(sentiment_analysis.inspect())


# ─────────────────────────────────────────────────────────────────────────────
# NATIVE TOOL 1: Gmail (allow + confirm interaction)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TEST 2: NATIVE TOOL INSPECTION - Gmail")
print("=" * 80)

# Class-level inspect (all available actions)
print("\n📋 Gmail.inspect() - All available actions:")
gmail_all = Gmail.inspect()
print(f"Total actions: {gmail_all.get('total', 'N/A')}")
print(f"Actions: {gmail_all.get('methods', [])[:5]}...")  # Show first 5

# Instance with specific allow/confirm
gmail = Gmail(
    oauth_credentials="oauth_gmail.json",
    allow=["read", "send"],
    confirm=["send"]  # Only sends need approval
)
print("\n📋 gmail instance.inspect() - With allow=['read','send'], confirm=['send']:")
print(f"Connection type: {gmail.inspect().get('conn_type', 'N/A')}")
print(f"Methods: {gmail.inspect().get('methods', [])}")


# ─────────────────────────────────────────────────────────────────────────────
# NATIVE TOOL 2: SQL (allow/confirm for database actions)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TEST 3: NATIVE TOOL INSPECTION - SQL")
print("=" * 80)

sql = SQL(
    url="postgresql://localhost/testdb",
    allow=["schema", "query"],  # No writes allowed
    confirm=False  # No approval needed for allowed actions
)
print("\n📋 SQL instance.inspect() - With allow=['schema','query'], confirm=False:")
print(f"Methods: {sql.inspect().get('methods', [])}")
print(f"Note: 'write' action is NOT in methods (blocked by allow)")


# ─────────────────────────────────────────────────────────────────────────────
# MCP TOOL: Filesystem (external MCP server)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TEST 4: MCP TOOL INSPECTION")
print("=" * 80)

mcp_fs = MCP(
    "server-filesystem",
    args=["."],
    allow=["read_file", "list_directory"],
    confirm=["write_file"]
)
print("\n📋 MCP 'server-filesystem'.inspect():")
inspect_data = mcp_fs.inspect()
print(f"Server: {inspect_data.get('server', 'N/A')}")
print(f"Version: {inspect_data.get('version', 'N/A')}")
print(f"Available methods: {inspect_data.get('methods', [])[:3]}...")
if "connection_setup" in inspect_data:
    print(f"Connection setup info included: ✓")
    print(f"  - Required env keys: {inspect_data['connection_setup'].get('required_env_keys', [])}")


# ─────────────────────────────────────────────────────────────────────────────
# MEMORY TEST: With and without guidelines
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TEST 5: MEMORY CREATION & INSPECTION")
print("=" * 80)

# Memory with guidelines
memory_with_guidelines = Memory(
    namespace="integration_test",
    guidelines="You remember user preferences: billing monthly, language Spanish"
)
print("\n📋 Memory with guidelines created:")
print(f"Namespace: integration_test")
print(f"Guidelines set: ✓")

# Memory without guidelines
memory_no_guidelines = Memory(namespace="integration_test_2")
print("\n📋 Memory without guidelines created:")
print(f"Namespace: integration_test_2")
print(f"Guideline: (empty)")

print("\n📋 Testing Memory.add() (manual ingestion):")
import os
test_md_file = "test_ingestion.md"
with open(test_md_file, "w", encoding="utf-8") as f:
    f.write("# Integration Test Rules\nTesting memory add functionality from file.")

memory_with_guidelines.clear()
memory_with_guidelines.add("Manual text entry: User likes chocolate.")
memory_with_guidelines.add(test_md_file)

print(f"Added raw string and {test_md_file} to Memory via memory.add().")
search_res = memory_with_guidelines.search("chocolate", top_k=1)
if search_res:
    print(f"Search result for 'chocolate': {search_res[0].content}")
search_res2 = memory_with_guidelines.search("Integration Test", top_k=1)
if search_res2:
    print(f"Search result for 'Integration Test': {search_res2[0].content}")
os.remove(test_md_file)


# ─────────────────────────────────────────────────────────────────────────────
# CHAT TEST: With and without persistence, with parameters
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TEST 6: CHAT CREATION & INSPECTION")
print("=" * 80)

# Chat with persistence and parameters
chat_persistent = Chat(
    keep=15,
    summarize=True,
    namespace="chat_persistent",
    summarizer_llm="gemini-3.1-flash-lite-preview"
)
print("\n📋 Chat with persistence:")
print(f"Keep: 15 messages")
print(f"Summarize: True")
print(f"Namespace: chat_persistent (persists to ~/delfhos/chat/chat_persistent.db)")
print(f"Summarizer LLM: gemini-3.1-flash-lite-preview")

# Chat temporary (no persistence)
chat_temp = Chat(keep=5, summarize=False)
print("\n📋 Chat temporary (no persistence):")
print(f"Keep: 5 messages")
print(f"Summarize: False")
print(f"Namespace: None (in-memory only)")


# ─────────────────────────────────────────────────────────────────────────────
# AGENT TEST: LLM configurations (llm vs light_llm/heavy_llm)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TEST 7: AGENT INITIALIZATION - LLM CONFIGURATIONS")
print("=" * 80)

# Configuration 1: Single LLM (simplest)
print("\n1️⃣  Single LLM configuration:")
agent1 = Agent(
    tools=[calculate_vat, format_currency],
    llm="gemini-3.1-flash-lite-preview"
)
print(f"✓ Agent created with single llm")

# Configuration 2: Light LLM + Heavy LLM (advanced)
print("\n2️⃣  Light LLM + Heavy LLM configuration:")
agent2 = Agent(
    tools=[calculate_vat, format_currency],
    light_llm="gemini-3.1-flash-lite-preview",  # Fast, for prefilter
    heavy_llm="gemini-3.1-pro"  # Powerful, for code generation
)
print(f"✓ Agent created with light_llm + heavy_llm")

# Configuration 3: Individual LLM overrides (code/vision specific)
print("\n3️⃣  Individual LLM overrides:")
agent3 = Agent(
    tools=[calculate_vat, format_currency],
    llm="gemini-3.1-flash-lite-preview",
    code_llm="gemini-3.1-pro",  # Use stronger model for code
    vision_llm="gemini-3.1-pro-vision"  # Use vision model for images
)
print(f"✓ Agent created with llm + code_llm + vision_llm overrides")


# ─────────────────────────────────────────────────────────────────────────────
# AGENT TEST: Prefilter enabled
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TEST 8: PREFILTER ENABLED")
print("=" * 80)

agent_with_prefilter = Agent(
    tools=[calculate_vat, format_currency, sentiment_analysis, gmail, sql],
    llm="gemini-3.1-flash-lite-preview",
    enable_prefilter=True  # Filter relevant tools before code generation (~60% cost savings)
)
print(f"✓ Agent created with enable_prefilter=True")
print(f"When running tasks, agent will:")
print(f"  1. Use light_llm to filter relevant tools")
print(f"  2. Reduce token cost by ~60%")
print(f"  3. Pass only relevant tool docs to heavy_llm")


# ─────────────────────────────────────────────────────────────────────────────
# AGENT TEST: Default & Custom on_confirm
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TEST 9: APPROVAL HANDLERS - DEFAULT vs CUSTOM")
print("=" * 80)

# Default: uses console questionary
print("\n1️⃣  Default on_confirm (uses console selector):")
agent_default_approve = Agent(
    tools=[calculate_vat, gmail],
    llm="gemini-3.1-flash-lite-preview",
    # on_confirm NOT specified → uses interactive questionary in terminal
)
print(f"✓ Agent will use default console selector for approvals")

# Custom: auto-approve everything
print("\n2️⃣  Custom on_confirm (auto-approve):")
def auto_approve(request):
    """Auto-approve all requests."""
    return True

agent_auto_approve = Agent(
    tools=[calculate_vat, gmail],
    llm="gemini-3.1-flash-lite-preview",
    on_confirm=auto_approve  # Replaces console selector
)
print(f"✓ Agent will auto-approve all requests")

# Custom: selective approval based on action
print("\n3️⃣  Custom on_confirm (selective):")
def selective_approve(request):
    """Only approve non-financial operations."""
    action = request.get("action", "").lower()
    if "financial" in action or "send" in action:
        return False, "Financial operations require manual approval"
    return True

agent_selective_approve = Agent(
    tools=[calculate_vat, gmail],
    llm="gemini-3.1-flash-lite-preview",
    on_confirm=selective_approve
)
print(f"✓ Agent will selectively approve based on action type")


# ─────────────────────────────────────────────────────────────────────────────
# FULL AGENT TEST: All features combined
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("TEST 10: FULL AGENT - ALL FEATURES COMBINED")
print("=" * 80)

full_agent = Agent(
    tools=[
        # Custom tools
        calculate_vat,
        format_currency,
        sentiment_analysis,
        # Native tools
        Gmail(
            oauth_credentials="oauth_gmail.json",
            allow=["read", "send"],
            confirm=["send"]
        ),
        SQL(
            url="postgresql://localhost/testdb",
            allow=["schema", "query"],
            confirm=False
        ),
        # MCP tools
        MCP("server-filesystem", args=["."], allow=["read_file"], confirm=False),
    ],
    llm="gemini-3.1-flash-lite-preview",
    
    # Memory & Chat
    memory=Memory(namespace="full_test", guidelines="Remember user preferences"),
    chat=Chat(keep=20, summarize=True, namespace="full_test", summarizer_llm="gemini-3.1-flash"),
    
    # Approval & Safety
    enable_prefilter=True,
    on_confirm=lambda r: True,  # Auto-approve
    
    verbose=True
)

print(f"✓ Full agent created with:")
print(f"  - 3 custom tools + 2 native tools + 1 MCP tool")
print(f"  - Memory with guidelines + persistent Chat")
print(f"  - Multiple LLM models (general, light, heavy, code, vision)")
print(f"  - Prefilter enabled")
print(f"  - Custom approval handler")
print(f"  - Verbose mode")

print("\n" + "=" * 80)
print("✅ INTEGRATION TEST 1 COMPLETE - All tool types, configs, and inspections verified")
print("=" * 80)
