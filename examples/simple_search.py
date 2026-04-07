

from delfhos import Agent, WebSearch

agent = Agent(
    tools=[
        WebSearch(confirm=False, llm="gemini-3.1-flash-lite-preview"),
    ],
    llm="gemini-3.1-flash-lite-preview",
    verbose=True,
)

agent.run(
    "Search the web for recent news about AI. Summarize the top 3 results in a markdown table with columns: Title, Source, Summary."
) 

agent.stop()
