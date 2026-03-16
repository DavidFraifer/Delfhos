"""
Full Delfhos showcase demo.

This example is intentionally simple to read, but broad in coverage.
It demonstrates:
- @tool decorator for sync + async tools
- ToolException + return_errors behavior
- Unified confirm policy + human approval callback
- Chat (short-term memory) + Memory (long-term retrieval)
- run + arun execution modes
- Agent inspection APIs (info, usage, agent_id)
- Trace export
- Optional external tools (WebSearch, MCP) if enabled via env vars

Run:
    python3 -m examples.agent_demo

Optional flags:
    USE_WEBSEARCH_DEMO=1   # include WebSearch tool
    USE_MCP_DEMO=1         # include local filesystem MCP tool (requires npx)
"""

import asyncio
import os
import shutil
import warnings
from typing import Dict, List

# Suppress specific warnings
warnings.filterwarnings("ignore", category=Warning, module="urllib3")
warnings.filterwarnings("ignore", message="You are using a non-supported Python version")

from delfhos import Agent, Chat, Memory, MCP, ToolException, WebSearch, tool


# ----------------------------
# Custom tools: @tool
# ----------------------------

@tool(kind="read")
def get_weather(location: str) -> str:
    """Return a deterministic weather snapshot for demo purposes."""
    mock = {
        "madrid": "Sunny, 25C",
        "london": "Rainy, 15C",
        "tokyo": "Cloudy, 22C",
    }
    return f"Weather in {location}: {mock.get(location.lower(), 'Unknown city')}"


@tool(kind="read")
async def get_forecast(location: str, days: int = 3) -> str:
    """Return a deterministic multi-day forecast for demo purposes."""
    await asyncio.sleep(0)
    return f"{days}-day forecast for {location}: sunny, cloudy, rainy."


@tool(kind="write")
def save_note(title: str, content: str) -> str:
    """Simulate a write operation that should trigger approval when enabled."""
    return f"Saved note '{title}' ({len(content)} chars)."


@tool(return_errors=True, kind="read")
def risky_division(a: int, b: int) -> str:
    """Demonstrate ToolException recovery with return_errors=True."""
    if b == 0:
        raise ToolException("Division by zero is invalid. Use a non-zero denominator.")
    return f"Result: {a / b}"


@tool(kind="read")
async def kpi_summary(metrics: Dict[str, float]) -> str:
    """Summarize key KPI values from a metrics dictionary."""
    if not metrics:
        return "No KPIs provided."
    ordered = sorted(metrics.items(), key=lambda item: item[1], reverse=True)
    top = ", ".join(f"{k}={v}" for k, v in ordered[:3])
    return f"Top KPIs: {top}"


@tool(kind="read")
async def team_priorities(team: str) -> str:
    """Return a mock set of priorities for a team."""
    data = {
        "product": ["Retention", "Activation", "NPS"],
        "sales": ["Pipeline", "Upsell", "Renewals"],
        "ops": ["SLA", "Automation", "Cost control"],
    }
    items = data.get(team.lower(), ["Backlog grooming", "Planning", "Execution"])
    return f"{team} priorities: {', '.join(items)}"


async def on_confirm(request) -> bool:
    """Auto-approve callback; bool return is the default/expected callback shape."""
    print(f"[approval] auto-approving request {request.request_id}")
    await asyncio.sleep(0)
    return True


def build_optional_external_tools() -> List[object]:
    """Add external tools only when explicitly requested via env vars."""
    tools: List[object] = []

    if os.getenv("USE_WEBSEARCH_DEMO") == "1":
        tools.append(WebSearch())

    if os.getenv("USE_MCP_DEMO") == "1" and shutil.which("npx"):
        tools.append(MCP("server-filesystem", args=["."], cache=True))

    return tools


async def main() -> None:
    memory = Memory(path="~/.delfhos/agent_demo_memory.db", namespace="agent_demo_showcase")
    chat = Chat(keep=6, summarize=True)

    tools = [
        get_weather,
        get_forecast,
        save_note,
        risky_division,
        kpi_summary,
        team_priorities,
    ] + build_optional_external_tools()

    with Agent(
        tools=tools,
        llm="gemini-3.1-flash-lite-preview",
        system_prompt="You are a concise operations assistant focused on clear action plans.",
        confirm="write",
        chat=chat,
        memory=memory,
        on_confirm=on_confirm,
        trace="minimal"
    ) as agent:

        # Sync run: combines multiple tool types in one task.
        agent.run(
            "I am David from Delfhos. My favorite city is Madrid. "
            "Give weather and 3-day forecast for Madrid, then list product team priorities.",
            timeout=120,
        )

        if agent.last_trace:
            agent.last_trace.to_json("agent_demo_trace.json")
            print("\\nTrace saved to agent_demo_trace.json")

    


if __name__ == "__main__":
    asyncio.run(main())
