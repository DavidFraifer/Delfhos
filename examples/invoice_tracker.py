
from delfhos import Agent, Gmail, Sheets

agent = Agent(
    tools=[
        Gmail(oauth_credentials="client_secrets.json", allow=["read", "send"], confirm=["send"]),
        Sheets(oauth_credentials="client_secrets.json", allow=["create", "write"]),
    ],
    llm="gemini-3.1-flash-lite-preview",
    verbose=True,
)

agent.run(
"""
Search my Gmail for emails with "invoice" in the subject (only for this week).
For each email extract three fields: amount (the total money amount), date (the invoice date), and concept (what the invoice is for).
Create a new Google Sheet called 'Invoice Tracker' with columns: Amount, Date, Concept — one row per invoice.
"""
)   

agent.stop()



