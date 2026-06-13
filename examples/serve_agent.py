"""
Expose an agent over HTTP so other systems can run tasks against it.

Everything goes through the `Agent` object — no internal imports.

Run:
    export DELFHOS_API_KEY="sk-my-secret"
    python examples/serve_agent.py

Then, from anywhere:
    curl -H "Authorization: Bearer sk-my-secret" \
         -X POST localhost:8080/run -H 'content-type: application/json' \
         -d '{"task":"Busca las novedades de IA de esta semana"}'
    # -> {"task_id": "..."}

    curl -H "X-API-Key: sk-my-secret" localhost:8080/tasks/<task_id>  # poll until is_terminal
"""

from delfhos import Agent, WebSearch

agent = Agent(
    tools=[WebSearch(confirm=False, llm="gpt-5.4-mini")],
    llm="gpt-5.4-mini",
)

# Public + authenticated. The key is read from DELFHOS_API_KEY if not passed here.
# Binding to 0.0.0.0 without any key fails closed (raises) instead of serving openly.
agent.serve(host="0.0.0.0", port=8080)


# --- Alternative: mount inside your own FastAPI app -------------------------
# from fastapi import FastAPI
# app = FastAPI()
# app.mount("/agent", agent.asgi_app(api_key="sk-my-secret"))
# # uvicorn examples.serve_agent:app --host 0.0.0.0 --port 8080
