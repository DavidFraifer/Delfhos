"""delfhos.sandbox — Mock/test implementations of third-party APIs.

Useful for testing and developing agents without live API calls or real credentials::

    from delfhos.sandbox import MockEmail, MockDatabase

    # In tests, swap real tools with mocks
    agent = Agent(tools=[MockEmail(), MockDatabase()], llm="gemini-3.1-flash-lite-preview")

Mocks:
  • MockEmail — simulates Gmail send/read
  • MockDatabase — simulates SQL queries
"""

from .sql import MockDatabase
from .gmail import MockEmail

__all__ = ["MockDatabase", "MockEmail"]
