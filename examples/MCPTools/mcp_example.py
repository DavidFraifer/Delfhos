import asyncio
from delfhos import Agent, Chat, MCP, WebSearch

   
async def main() -> None:
    mcp_tool = MCP("server-filesystem", args=["."])
    print(mcp_tool.inspect(verbose="regular"))
    
    mcp_tool = MCP("server-filesystem", args=["."], allowed=["read_file", "read_text_file", "write_file", "read_media_file"])
    
    with Agent(
        tools=[WebSearch(), mcp_tool],
        chat=Chat(keep=5),
        confirm=["read_media_file", "write_file"],
        verbose="regular",
        llm="gemini-3.1-flash-lite-preview"
    ) as agent:
        agent.run("Lee el archivo llamado 'ejemplo.png'. Puedes analizarlo y describir lo que ves?")

if __name__ == "__main__":
    asyncio.run(main())
