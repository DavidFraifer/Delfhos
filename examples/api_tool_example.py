"""
Financial Market Analyst — Delfhos APITool example
===================================================
What this example shows
  • APITool      — turn any Swagger/OpenAPI spec into agent-callable tools
  • budget_usd   — hard spending cap; new tasks are blocked once the limit is hit
  • output files — the agent saves results to CSV and JSON on disk
  • cost tracking — inspect result.cost_usd per task and agent.total_cost_usd overall

Requirements
  pip install delfhos python-dotenv
  FINNHUB_API_KEY=<your key>  (free tier at https://finnhub.io)
"""

import os
from dotenv import load_dotenv
from delfhos import Agent, APITool

load_dotenv()
FINNHUB_API_KEY = os.environ["FINNHUB_API_KEY"]

# ── 1. Wrap the Finnhub REST API as a tool ─────────────────────────────────────
#
#  APITool reads the OpenAPI spec, exposes only the listed endpoints,
#  and injects the auth header automatically.
#
finnhub = APITool(
    spec="https://finnhub.io/static/swagger.json",
    base_url="https://finnhub.io/api/v1",
    headers={"X-Finnhub-Token": FINNHUB_API_KEY},
    allow=[
        "quote",                    # real-time price, change %, volume
        "company_basic_financials",  # P/E, EPS, 52-week range, market cap
    ],
    cache=True,  # re-use the parsed spec on disk so startup is instant next run
)

# ── 2. Create the agent with a hard $0.10 spending cap ────────────────────────
#
#  budget_usd accumulates across every run() call on this agent instance.
#  Once the limit is hit, further run() calls raise AGT-006 until reset_budget()
#  is called.  agent.total_cost_usd shows how much has been spent so far.
#
agent = Agent(
    llm="gemini-3.1-flash-lite-preview",
    tools=[finnhub],
    system_prompt=(
        "You are a concise financial analyst. "
        "Always export data as structured files when the task asks for it."
    ),
    budget_usd=0.10,  # hard cap: block new tasks once $0.10 is spent
    verbose=True,
)

TICKERS = ["AAPL", "MSFT", "NVDA"]

print(f"\n{'─' * 58}")
print("  Financial Market Analyst  |  budget cap: $0.10 USD")
print(f"{'─' * 58}\n")

# ── 3. Task A: live quotes → quotes.csv ───────────────────────────────────────
#
#  The agent calls the Finnhub `quote` endpoint for each ticker and saves the
#  result as a CSV.  The file path is returned in result.files.
#
result_quotes = agent.run(
    f"Fetch the current stock quote for {', '.join(TICKERS)}. "
    "For each ticker collect: current price, percentage change today, "
    "daily high, daily low, and trading volume. "
    "Save everything to a CSV file named quotes.csv with columns: "
    "ticker, price, change_pct, high, low, volume.",
    timeout=90,
)

if result_quotes.status:
    print(f"\n✓  Quotes complete  |  cost this task: ${result_quotes.cost_usd:.5f}")
    for label, path in result_quotes.files.items():
        print(f"   [{label}] saved → {path}")
else:
    print(f"\n✗  Quotes failed: {result_quotes.error}")

# ── 4. Task B: fundamentals → fundamentals.json ───────────────────────────────
#
#  A second task hits the `company_basic_financials` endpoint and exports
#  the key metrics as JSON.
#
result_fund = agent.run(
    f"Fetch basic financial metrics for {', '.join(TICKERS)}: "
    "P/E ratio, EPS (TTM), 52-week high, 52-week low, and market cap. "
    "Export a JSON file named fundamentals.json where each key is the ticker "
    "symbol and the value is a dict of those metrics.",
    timeout=90,
)

if result_fund.status:
    print(f"\n✓  Fundamentals complete  |  cost this task: ${result_fund.cost_usd:.5f}")
    for label, path in result_fund.files.items():
        print(f"   [{label}] saved → {path}")
else:
    print(f"\n✗  Fundamentals failed: {result_fund.error}")

# ── 5. Cost & budget dashboard ────────────────────────────────────────────────
#
#  agent.info()["budget"] gives a live snapshot of spend vs. limit.
#  agent.total_cost_usd is a shortcut for the same number.
#
budget = agent.info()["budget"]

print(f"\n{'─' * 58}")
print(f"  Spent:     ${budget['spent_usd']:.5f}")
print(f"  Limit:     ${budget['limit_usd']:.5f}")
print(f"  Remaining: ${budget['remaining_usd']:.5f}")
print(f"  Exceeded:  {budget['exceeded']}")
print(f"{'─' * 58}\n")

# If the budget was exhausted you can reset it and continue:
#
#   agent.reset_budget()             # zero the counter, keep the same $0.10 cap
#   agent.reset_budget(budget_usd=0.25)  # zero the counter and raise the cap

agent.stop()
