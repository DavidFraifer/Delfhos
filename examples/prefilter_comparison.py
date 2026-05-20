"""
Prefilter Mode Comparison — Delfhos example
============================================
Runs the same task three times, each with a different prefilter strategy,
and prints cost + latency so you can see the trade-off at a glance.

Prefilter modes
  "off"    — no routing; the heavy LLM sees every tool on every call
  "filter" — one fast LLM call selects the relevant tools (good for 10–49 actions)
  "search" — iterative search loop over tool summaries (best for ≥50 actions)

Requirements
  pip install delfhos python-dotenv
  FINNHUB_API_KEY=<your key>   (free tier at https://finnhub.io)
  GOOGLE_API_KEY=<your key>    (for Gemini models)
"""

import os
import time
from dotenv import load_dotenv
from delfhos import Agent, APITool

load_dotenv()
FINNHUB_API_KEY = os.environ["FINNHUB_API_KEY"]

# ── Shared tool: Finnhub REST API ─────────────────────────────────────────────
finnhub = APITool(
    spec="https://finnhub.io/static/swagger.json",
    base_url="https://finnhub.io/api/v1",
    headers={"X-Finnhub-Token": FINNHUB_API_KEY},
    cache=True,
    confirm=False,  
)
print(finnhub.inspect())

TASK = (
    "Fetch the current stock quote for AAPL and MSFT. "
    "Return the current price and daily percentage change for each."
)

MODES = ["off", "filter", "search"]

print(f"\n{'═' * 60}")
print("  Prefilter Mode Comparison  |  Finnhub · AAPL & MSFT quote")
print(f"{'═' * 60}\n")

results = {}

for mode in MODES:
    agent = Agent(
        llm="gemini-3.1-flash-lite",
        tools=[finnhub],
        prefilter_mode=mode,
        verbose=False,
    )

    t0 = time.perf_counter()
    result = agent.run(TASK, timeout=60)
    elapsed = time.perf_counter() - t0

    results[mode] = {"cost": result.cost_usd, "elapsed": elapsed, "ok": result.status}
    agent.stop()

    status = "✓" if result.status else "✗"
    print(f"  [{mode:6s}]  {status}  cost: ${result.cost_usd:.5f}   time: {elapsed:.1f}s")
    if not result.status:
        print(f"           error: {result.error}")

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'─' * 60}")
baseline = results["off"]["cost"] or 1e-9
for mode in MODES:
    r = results[mode]
    savings = (1 - r["cost"] / baseline) * 100 if mode != "off" else 0.0
    label = f"  [{mode:6s}]  ${r['cost']:.5f}"
    note = f"  ({savings:+.0f}% vs off)" if mode != "off" else ""
    print(label + note)
print(f"{'─' * 60}\n")
