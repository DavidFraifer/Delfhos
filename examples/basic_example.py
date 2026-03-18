
from delfhos import Agent, Chat, MCP, WebSearch, tool, Gmail

mcp_tool = MCP("server-filesystem", args=["."], allow=["read_file", "read_text_file", "write_file", "read_media_file"])
gmail = Gmail(oauth_credentials="oauth_gmail.json")
@tool
async def calculate_mortgage(principal: float, annual_rate: float, years: int) -> float:
    """Calcula el pago mensual de una hipoteca."""
    monthly_rate = annual_rate / 12 / 100
    payments = years * 12
    if monthly_rate == 0:
        return principal / payments
    return principal * (monthly_rate * (1 + monthly_rate) ** payments) / ((1 + monthly_rate) ** payments - 1)

agent = Agent(
    tools=[WebSearch(llm="gpt-5.4-mini"), mcp_tool, calculate_mortgage,gmail],
    confirm="write_file",
    llm="gemini-3.1-flash-lite-preview",
    chat=Chat(),
    verbose=True
)
Resp = agent.run("Tell me the subject and sender of the last mail I received")
#Resp = agent.run("Search in web the current average interest rates for mortgages in the national average in the US, calculate the monthly payment for a 300k mortgage over 30 years fixed, and save the results in mortgage_results.json is just for calculating a bit aproximate, dont ask me more and do it")
#Resp = agent.run("Can you estimate the monthly cost of a mortgage for 300k with 30 years, do this calculations based on multiple interest rates starting from 3% to 7% with increments of 0.5% and save the results in a file named mortgage_results.json")
agent.stop()

if Resp.trace:
    Resp.trace.to_json("agent_trace.json")
