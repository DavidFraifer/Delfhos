import asyncio
from delfhos import Agent, Chat, tool


@tool(kind="read")
def word_counter(text: str) -> str:
    """A simple tool to count words in a given text string."""
    return f"The text has {len(text.split())} words."


async def main() -> None:
    # 1. Chat Setup
    # Notice we use keep=5 to hold the last 5 interactions in memory.
    # We do NOT use Memory (persistent storage database), just Chat.
    chat = Chat(keep=5, summarize=False)

    with Agent(
        tools=[word_counter],
        system_prompt="You are a helpful assistant. You keep track of the user's name and previous messages.",
        chat=chat
    ) as agent:
        print("=== Chat Memory Agent Starting ===")

        print("\nTurn 1:")
        agent.run("Hi there! My name is David and my favorite fruit is the Mango. How many words are in this exact sentence?")

        print("\nTurn 2:")
        # The agent should remember the user's name and favorite fruit from Turn 1 context
        agent.run("Do you remember my name and my favorite fruit? Please count the words of your answer before responding.")


if __name__ == "__main__":
    asyncio.run(main())
