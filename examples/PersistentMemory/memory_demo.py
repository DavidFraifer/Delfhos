"""
Memory demo — shows embedding-based retrieval in action.

Session 1: agent learns facts about you.
Session 2: agent recalls only the relevant ones for each task.

Run twice to see memory persist across sessions:
    python3 examples/memory_demo.py
"""

from delfhos import Agent, Chat, Memory, tool

@tool
def get_invoice_status(client: str) -> str:
    """Return the payment status for a client's invoice."""
    statuses = {
        "acme": "Invoice #1042 — $4,200 — OVERDUE (30 days)",
        "globex": "Invoice #1043 — $1,800 — PAID",
        "initech": "Invoice #1044 — $6,500 — PENDING",
    }
    return statuses.get(client.lower(), f"No invoice found for '{client}'.")


memory = Memory(
    path="~/.delfhos/memory_demo.db",
    namespace="memory_demo",
)

# ── Session ──────────────────────────────────────────────────────────────────
# First run: tell the agent facts about you. They get stored on context exit.
# Second run: the agent retrieves only the relevant ones automatically.
# ---------------------------------------------------------------------------

with Agent(
    tools=[get_invoice_status],
    memory=memory,
) as agent:
    agent.run("My name is David and I work at Delfhos. My main client is Acme Corp.")
    agent.run("Check the invoice status for Acme and let me know if I need to follow up.")

# ── Verify what's stored ─────────────────────────────────────────────────────
print("\n--- Stored memories ---")
print(memory.context() or "(none yet — run again to see persisted facts)")

# ── Manual retrieval test ────────────────────────────────────────────────────
print("\n--- Retrieval test ---")
queries = [
    "who is my main client?",
    "check invoice for Acme",
    "what is my name?",
]
for q in queries:
    result = memory.retrieve(q)
    print(f"Q: {q}")
    print(f"A: {result or '(no match)'}")
    print()
