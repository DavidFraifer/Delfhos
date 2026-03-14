import asyncio
from delfhos import Agent, Chat, MCP, WebSearch, Gmail


async def main() -> None:
    chat = Chat(keep=5, summarize=False)

    search_tool = WebSearch()
    gmail_tool = Gmail(credentials={"oauth_credentials": "client_secrets.json"})
    mcp_tool = MCP("server-filesystem", args=["."], cache=True)

    # Combine our tools
    tools = [
        search_tool,
        gmail_tool,
        mcp_tool
    ]

    # 4. Canonical Context Manager pattern with lowest friction setup
    with Agent(
        tools=tools,
        system_prompt="You are a helpful assistant with access to search the web, read emails, and check local files.",
        chat=chat,
        # No memory= parameter here
    ) as agent:
        print("=== Simple Agent Starting ===")

        # First turn: Calling a native web search tool
        print("\nTurn 1:")
        agent.run("Can you do a quick web search to find out the current weather in Madrid? Keep your answer short.")

        # Second turn: Tests chat retention and MCP tool
        print("\nTurn 2:")
        agent.run("Based on that weather, suggest an outfit, and use the MCP tool to check what files are in the current working directory.")


if __name__ == "__main__":
    asyncio.run(main())
