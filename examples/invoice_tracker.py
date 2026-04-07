

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
Search my Gmail for emails with "invoice" in the subject (last 7 days only).
For each email extract three fields: amount (the total money amount), date (the invoice date), and concept (what the invoice is for).
Create a new Google Sheet called 'Invoice Tracker' with columns: Amount, Date, Concept — one row per invoice.
Give me the full url of the sheets at the end and print the table of invoices in markdown format.
"""
)   

agent.stop()



