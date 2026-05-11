

from delfhos import Agent, WebSearch, Chat

agent = Agent(
    tools=[
        WebSearch(confirm=False, llm="gemini-3.1-flash-lite-preview"),
    ],
    llm="gemini-3.1-flash-lite-preview",
    chat=Chat(),
    verbose=True,
)

agent.run_chat() #Ask anything related to search

agent.stop()
