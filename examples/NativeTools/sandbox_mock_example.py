import asyncio
from delfhos import Agent
from delfhos.sandbox import MockEmail, MockDatabase


async def main() -> None:
    # 1. Native Sandbox Tools (Mock Connections)
    # These mimic the behavior of Gmail and SQL tools without needing API keys or a real database!
    mock_email = MockEmail()
    mock_db = MockDatabase()

    tools = [
        mock_db,
        mock_email,
    ]

    # 2. Agent initialized entirely with Sandbox mock capabilities
    with Agent(
        tools=tools,
        system_prompt="You are a helpful assistant with access to a mock database and mock email. Keep answers short.",
    ) as agent:
        print("=== Sandbox Native Tools Agent Starting ===")

        # First turn: Have it query the mock SQL DB
        print("\nTurn 1: Checking the Database")
        agent.run("Can you check the database to see if we have any pending tickets or orders?")

        # Second turn: Have it query the mock Email
        print("\nTurn 2: Checking Emails")
        agent.run("Now check my email inbox. What is the latest message you see?")


if __name__ == "__main__":
    asyncio.run(main())
