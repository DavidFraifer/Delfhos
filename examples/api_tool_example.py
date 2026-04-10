import os
from dotenv import load_dotenv
from delfhos import Agent, APITool

load_dotenv()

# Uncomment to discover available endpoint names before filtering with allow=:
# print(APITool.inspect(spec="https://api.fiscal.ai/openapi.json"))

fiscal = APITool(
    spec="https://api.fiscal.ai/openapi.json",
    base_url="https://api.fiscal.ai",
    auth={"X-Api-Key": os.environ.get("FISCAL_API_KEY")},
    cache=True
)

agent = Agent(
    tools=[fiscal],
    llm="gemini-3.1-flash-lite-preview",
    verbose=True,
    system_prompt=(
        "You are an expert financial analyst. Use the fiscal.ai tools to retrieve "
        "real financial data and provide clear, structured analysis."
    ),
)

agent.run(
    "Give me a brief financial overview of Microsoft (MSFT): "
    "company profile, latest annual revenue and net income from the income statement, "
    "and key ratios (P/E and ROE). Summarize in a clean markdown report."
)

agent.stop()
