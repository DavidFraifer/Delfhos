import os

from delfhos import Agent, WebSearch, Gmail, Chat

with Agent(
    tools=[WebSearch(), Gmail(oauth_credentials=os.path.join("examples", "NativeTools", "oauth_gmail.json"))],
    chat=Chat(keep=5, summarize=True),
) as agent:
    agent.run("Check my Gmail for emails mentioning RAG or AI")



