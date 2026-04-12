import os
from dotenv import load_dotenv
from delfhos import Agent, APITool, Chat

load_dotenv()

FINNHUB_API_KEY = os.environ["FINNHUB_API_KEY"]

finnhub = APITool(
    spec="https://finnhub.io/static/swagger.json",
    base_url="https://finnhub.io/api/v1",
    auth={"X-Finnhub-Token": FINNHUB_API_KEY},
    allow=[
        "quote",
        "company_basic_financials",
    ],
    confirm=False,
    enrich=True,
    cache=True,
    llm="gemini-3.1-flash-lite-preview",
    sample=True,
)

print(finnhub.inspect(verbose=True))

agent = Agent(
    llm="gemini-3.1-flash-lite-preview",
    tools=[finnhub],
    system_prompt=(
        "Eres un analista financiero experto en el mercado de valores. "
        "Tu tarea es proporcionar información precisa y completa sobre empresas."
    ),
    chat=Chat(summarizer_llm="gemini-3.1-flash-lite-preview"),
    verbose=True,
)

agent.run("Tell me all the information you can about Apple Inc. (AAPL) using the finnhub API tool.")
