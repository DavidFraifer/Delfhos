import os
from dotenv import load_dotenv
from delfhos import Agent, APITool, Chat

load_dotenv()
FINNHUB_API_KEY = os.environ["FINNHUB_API_KEY"]

finnhub = APITool(
    spec="https://finnhub.io/static/swagger.json",
    base_url="https://finnhub.io/api/v1",
    headers={"X-Finnhub-Token": FINNHUB_API_KEY},
    allow=[
        "quote",
        "company_basic_financials",
    ],
    cache=True,
    llm="gemini-3.1-flash-lite-preview",
)

print(finnhub.inspect(verbose=True))

agent = Agent(
    llm="gemini-3.1-flash-lite-preview",
    tools=[finnhub],
    system_prompt=(
        "Eres un analista financiero experto en el mercado de valores. "
        "Tu tarea es proporcionar información precisa y completa sobre empresas."
    ),
    verbose=True,
)

agent.run("Tell me all the information you can about Apple Inc. (AAPL) using the finnhub API tool. Take care of token consumption, just pass to the API the necessary information to get the answer.")
