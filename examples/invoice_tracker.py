

from delfhos import Agent, Gmail, Sheets

agent = Agent(
    tools=[
        Gmail(oauth_credentials="client_secrets.json", allow=["read", "send"], confirm=["send"]),
        Sheets(oauth_credentials="client_secrets.json", allow=["create", "write"]),
    ],
    llm="gemini-3.1-flash-lite",
    verbose=True,
)

agent.run(
"""
    Cuentame cuantos correos tiene "Factura" en el asunto en la ultima semana
"""
)

agent.stop()



