

from delfhos import Agent, Chat, Gmail, Sheets, Drive

agent = Agent(
    tools=[
        Gmail(oauth_credentials="client_secrets.json"),
        Sheets(oauth_credentials="client_secrets.json"),
        Drive(oauth_credentials="client_secrets.json"),
    ],
    llm="gemini-3.1-flash-lite",
    chat=Chat(),
    verbose=True,
)

agent.run_chat() #Ask anything related to search

