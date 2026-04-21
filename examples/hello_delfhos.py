"""
hello_delfhos.py — Run your first Delfhos agent in seconds.

Uses built-in sandbox tools (MockEmail + MockDatabase) so no API keys,
no credentials, and no external services are needed.

The sandbox comes pre-loaded with:
  • 2 emails  (one from alice@example.com about her overdue invoice, ticket TCK8843)
  • 3 users   (Alice: alice@example.com, Bob, Charlie)
  • 3 orders  (Alice has Enterprise License + Support Add-on)
  • 3 tickets (TCK8843 is open for Alice)

Run:
    python examples/hello_delfhos.py
"""

from delfhos import Agent
from delfhos.sandbox import MockEmail, MockDatabase

agent = Agent(
    tools=[
        MockEmail(),
        MockDatabase(confirm=False),
    ],
    llm="gemini-3.1-flash-lite-preview",
    verbose=True
)

agent.run(
    "Read my unread emails. If any mention a support ticket, "
    "look it up in the database and reply with a short summary of "
    "the customer's name, their open tickets, and their total order value."
) # Just imagine how much code, time and tokens would take this in Langchain!

agent.stop()
