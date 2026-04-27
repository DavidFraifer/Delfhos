"""
rerun_example.py — Adaptive replanning with rerun()
====================================================
What this example shows
  • rerun()  — mid-execution replanning when the data shape is only known at runtime
  • @tool    — custom tool wrapping any Python function into an agent-callable API
  • verbose  — full execution timeline so you can see both planning passes

The problem rerun() solves
  When the task is "summarise the sales report", the agent cannot know at
  code-generation time which columns (metrics) the report will contain — they
  depend on what data exists in the database.  Normal control flow can't help:
  you can't write `row["revenue"]` if you don't know the column is called
  "revenue" until you actually fetch the data.

  rerun() breaks the task into two passes:
    Pass 1  — fetch the raw report, inspect its structure, call rerun() with
              the real schema as context and "format and print the report" as
              the remaining work.
    Pass 2  — the LLM now knows the exact columns and generates correct
              formatting code.

Run
  python examples/rerun_example.py
"""

from delfhos import Agent, tool


# ── Custom tool: simulates a sales-reporting API with dynamic columns ──────────
#
#  Real-world analogy: a data warehouse or BI API that exposes different metrics
#  depending on which dimensions are present in the requested period.
#  The caller (the agent) cannot know the column set without fetching first.
#
@tool
def sales_report(region: str = "all", quarter: str = "latest") -> dict:
    """
    Fetch the sales performance report for a region and quarter.

    Returns a dict with keys: region, quarter, columns (list of metric names),
    rows (list of values per column), and totals (dict of aggregate values).
    The exact column names are dynamic and vary by region — you must inspect
    the returned 'columns' key after fetching to know what fields are available.
    """
    data = {
        "all": {
            "quarter": "2024-Q4",
            "region": "Global",
            "columns": ["month", "revenue_usd", "units_sold", "avg_deal_size_usd", "churn_rate_pct", "nps_score"],
            "rows": [
                ["October",  1_840_200, 312, 5_898, 1.8, 72],
                ["November", 2_105_600, 358, 5_881, 1.5, 74],
                ["December", 2_490_100, 401, 6_210, 1.2, 78],
            ],
            "totals": {"revenue_usd": 6_435_900, "units_sold": 1071},
        },
        "EMEA": {
            "quarter": "2024-Q4",
            "region": "EMEA",
            "columns": ["month", "revenue_eur", "units_sold", "support_tickets_opened", "csat_score"],
            "rows": [
                ["October",  620_000, 98, 42, 4.1],
                ["November", 710_000, 115, 38, 4.3],
                ["December", 890_000, 140, 29, 4.5],
            ],
            "totals": {"revenue_eur": 2_220_000, "units_sold": 353},
        },
        "APAC": {
            "quarter": "2024-Q4",
            "region": "APAC",
            "columns": ["month", "revenue_usd", "units_sold", "new_logos", "expansion_arr_usd"],
            "rows": [
                ["October",  380_000, 61, 8, 95_000],
                ["November", 445_000, 74, 11, 112_000],
                ["December", 510_000, 88, 14, 140_000],
            ],
            "totals": {"revenue_usd": 1_335_000, "units_sold": 223},
        },
    }
    return data.get(region, data["all"])


# ── Agent ──────────────────────────────────────────────────────────────────────
agent = Agent(
    tools=[sales_report],
    llm="gemini-3.1-flash-lite-preview",
    verbose=True,
)

print("\n" + "─" * 60)
print("  rerun() demo — adaptive sales report formatting")
print("─" * 60 + "\n")

# ── Task: the region is passed at runtime; the agent cannot know the columns ──
#
#  Expected flow:
#    Pass 1: agent calls sales_report(region="EMEA"), sees the real column list,
#            calls rerun(context=<actual columns>, remaining="format and print the table")
#    Pass 2: fresh code-generation pass knows the exact columns and builds the table
#
result = agent.run(
    "Fetch the Q4 sales report for the EMEA region. "
    "The column names and row format are dynamic and unknown until you fetch — "
    "use rerun() after the initial fetch, passing the actual columns and a sample row "
    "as context, then generate a clean markdown table with all metrics per month "
    "and a totals row.",
    timeout=120,
)

print("\n" + "─" * 60)
if result.status:
    print(f"  Done  |  cost: ${result.cost_usd:.5f}")
else:
    print(f"  Failed: {result.error}")
print("─" * 60 + "\n")

# ── Show the trace so rerun iterations are visible ────────────────────────────
if result.trace and result.trace.reruns:
    print(f"Rerun iterations: {len(result.trace.reruns)}")
    for r in result.trace.reruns:
        print(f"  #{r.attempt}  {r.duration_ms}ms  remaining: {r.remaining_task[:60]}")
else:
    print("No rerun was triggered (model handled it in a single pass).")

agent.stop()
