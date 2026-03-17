from delfhos import Agent, Chat, MCP, WebSearch, tool, Memory

mcp_tool = MCP("server-filesystem", args=["."], allow=["read_file", "read_text_file", "write_file", "read_media_file"])


@tool
async def calculate_mortgage(principal: float, annual_rate: float, years: int) -> float:
    """Calcula el pago mensual de una hipoteca."""
    monthly_rate = annual_rate / 12 / 100
    payments = years * 12
    if monthly_rate == 0:
        return principal / payments
    return principal * (monthly_rate * (1 + monthly_rate) ** payments) / ((1 + monthly_rate) ** payments - 1)


agent = Agent(
    tools=[WebSearch(), mcp_tool, calculate_mortgage],
    chat=Chat(keep=5, summarize=True, namespace="agent_chat"),
    confirm="write_file",
    memory=Memory(guidelines="Only save the final mortgage payment amount (do not save pii information like names)", namespace="agent_memory"),
    llm="gemini-flash-latest"
)
agent.run("Search for the current interest rates for mortgages and then calculate the monthly payment for a $300,000 loan with the found annual rate over 30 years.")
agent.last_trace.to_json("agent_trace.json")  # Guarda el rastro de la conversación y las acciones en un archivo JSON
agent.stop()
