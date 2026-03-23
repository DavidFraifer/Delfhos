
from delfhos import Agent, Gmail, MCP, tool, Chat, WebSearch, Sheets

@tool
def car_insurance_quote(car_km: str, car_year: int, user_age: int) -> float:
    """Get a car insurance quote based on the km, model, age, and year of the car."""
    base_quote = 500
    return base_quote

gmail = Gmail(oauth_credentials="oauth_gmail.json",allow=["read", "send"], confirm=["send"])
mcp_filesystem = MCP("filesystem", args=["."], allow=["read_file", "read_text_file", "write_file", "read_media_file"], confirm=["write_file"])
Sheets_tool = Sheets(oauth_credentials="oauth_gmail.json")

agent = Agent(
    llm = "gemini-3.1-flash-lite-preview",
    tools = [gmail, WebSearch(llm="gemini-3.1-flash-lite-preview"), Sheets_tool],
    chat=Chat(summarizer_llm="gemini-3.1-flash-lite-preview")
    )

agent.run_chat()
#agent.run("Get a quote for a 2010 car with 150k km, and email it to example@gmail.com")
agent.stop()






