import os
import datetime
import json
import asyncio
from pathlib import Path
from typing import List, Optional, Any, Dict
from dotenv import load_dotenv
import sys

# Ensure parent directory is in python path to allow importing 'cortex'
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# --- Step 1: Securely handle imports to avoid NameErrors ---
try:
    # Google Auth & Discovery
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.tools import tool
    from langchain.agents import create_agent
    from langchain_google_genai import ChatGoogleGenerativeAI
    
except ImportError as e:
    print(f"Error: Missing core dependencies. Please install them:")
    print(f"pip install google-api-python-client google-auth-oauthlib langchain-google-genai python-dotenv")
    print(f"Specific missing module: {e}")
    exit(1)


load_dotenv()

# --- Helper: Get Google Credentials from Cortex Cache ---
def get_google_creds(tool_name: str) -> Credentials:
    """Read the same cached OAuth token that Delfhos uses."""
    token_dir = Path.home() / ".cortex" / "tokens"
    token_files = list(token_dir.glob(f"{tool_name}_*.json"))
    if not token_files:
        raise FileNotFoundError(f"No cached token found for {tool_name} in {token_dir}. Run Delfhos quickstart first.")
    
    token_path = token_files[0]
    with open(token_path, 'r') as f:
        data = json.load(f)
        
    creds = Credentials(
        token=data.get("token") or data.get("access_token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=data.get("client_id") or os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=data.get("client_secret") or os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=data.get("scopes", [])
    )
    
    if not creds.valid:
        creds.refresh(Request())
    return creds

# --- Global Token Tracking for Tools ---
HIDDEN_TOKENS = {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0, "calls": 0}

import time
from langchain_core.callbacks import BaseCallbackHandler

class ComputeTimeTracker(BaseCallbackHandler):
    """Tracks time specifically spent waiting for LLMs and executing Tools, ignoring agent loop overhead."""
    def __init__(self):
        super().__init__()
        self.compute_time = 0.0
        self.llm_starts = {}
        self.tool_starts = {}

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        self.llm_starts[run_id] = time.perf_counter()

    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        if run_id in self.llm_starts:
            self.compute_time += time.perf_counter() - self.llm_starts.pop(run_id)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        self.tool_starts[run_id] = time.perf_counter()

    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs):
        if run_id in self.tool_starts:
            self.compute_time += time.perf_counter() - self.tool_starts.pop(run_id)

# --- Improved Tools: No extra credentials required ---

@tool
def google_search(query: str) -> str:
    """Perform a web search for the latest information using the Delfhos connection logic."""
    # Instead of Tavily, we'll use Delfhos's internal search tool logic 
    # to avoid needing a new API Key. we'll call Gemini with web search capabilities.
    from cortex._engine.tools.websearch import web_search
    
    # Run the async search in a sync wrapper for LangChain
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    result, token_info = loop.run_until_complete(web_search(query))
    
    # Track the nested LLM call tokens
    HIDDEN_TOKENS["total_tokens"] += token_info.get("total_tokens", 0)
    HIDDEN_TOKENS["input_tokens"] += token_info.get("input_tokens", 0)
    HIDDEN_TOKENS["output_tokens"] += token_info.get("output_tokens", 0)
    HIDDEN_TOKENS["calls"] += 1
    
    return result

@tool
def create_google_doc(title: str, content: str) -> str:
    """Create a new Google Doc with the given title and content. Returns the doc ID."""
    creds = get_google_creds("docs")
    service = build("docs", "v1", credentials=creds)
    
    doc = service.documents().create(body={"title": title}).execute()
    doc_id = doc.get("documentId")
    
    # Insert content at the beginning
    requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
    service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    return doc_id

@tool
def list_emails(query: str = "is:unread", max_results: int = 10) -> str:
    """List recent emails from Gmail. Returns a list of dicts with id, threadId, and snippet."""
    creds = get_google_creds("gmail")
    service = build("gmail", "v1", credentials=creds)
    results = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    messages = results.get("messages", [])
    if not messages:
        return "No emails found."
    
    # Get details for each message
    details = []
    for msg in messages:
        m = service.users().messages().get(userId="me", id=msg['id'], format='minimal').execute()
        details.append({
            "id": msg['id'],
            "snippet": m.get('snippet', ''),
            "subject": next((h['value'] for h in m.get('payload', {}).get('headers', []) if h['name'].lower() == 'subject'), 'No Subject')
        })
    return str(details)

@tool
def get_email_body(message_id: str) -> str:
    """Get the full body content of a specific email by its message ID."""
    creds = get_google_creds("gmail")
    service = build("gmail", "v1", credentials=creds)
    message = service.users().messages().get(userId="me", id=message_id).execute()
    return message.get('snippet', '') # For simplicity in benchmark, snippet is fine, or we could extract parts

@tool
def create_google_sheet_with_data(title: str, rows: list[list[str]]) -> str:
    """Create a new Google Sheet with provided data.
    
    Args:
        title (str): The title of the new Google Sheet.
        rows (list[list[str]]): The data to insert, represented as a list of lists containing strings.
    """
    processed_rows = []
    for row in rows:
        if isinstance(row, (list, tuple)):
            processed_rows.append([str(v) for v in list(row)])
        else:
            processed_rows.append([str(row)])

    creds = get_google_creds("sheets")
    service = build("sheets", "v4", credentials=creds)
    
    spreadsheet = {'properties': {'title': title}}
    spreadsheet = service.spreadsheets().create(body=spreadsheet, fields='spreadsheetId,sheets').execute()
    sheet_id = spreadsheet.get('spreadsheetId')
    
    # Get the actual sheet name (varies by locale — "Sheet1", "Hoja 1", etc.)
    sheet_name = spreadsheet['sheets'][0]['properties']['title']
    
    body = {'values': processed_rows}
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id, range=f"'{sheet_name}'!A1",
        valueInputOption="RAW", body=body).execute()
    
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"

@tool
def send_email(to_email: str, subject: str, body: str) -> str:
    """Send an email via Gmail. Returns 'Success' or error message."""
    import base64
    from email.message import EmailMessage
    
    try:
        creds = get_google_creds("gmail")
        service = build("gmail", "v1", credentials=creds)
        
        message = EmailMessage()
        message.set_content(body)
        message["To"] = to_email
        message["From"] = os.getenv("GMAIL_SENDER_EMAIL")
        message["Subject"] = subject
        
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {"raw": encoded_message}
        
        service.users().messages().send(userId="me", body=create_message).execute()
        return "Email sent successfully"
    except Exception as e:
        return f"Failed to send email: {e}"

@tool
def sql_query(query: str) -> str:
    """Execute a SQL query against the database and return the results as a string."""
    import sqlite3
    import sqlalchemy
    from sqlalchemy import create_engine, text
    import decimal
    import datetime
    
    engine = create_engine(os.getenv("DATABASE_URL"))
    with engine.connect() as connection:
        result = connection.execute(text(query))
        rows = result.fetchall()
        
        # Safely serialize types like Decimal, datetime, or JSON to string before passing to LLM
        safe_rows = []
        for row in rows:
            safe_row = tuple(
                str(val) if isinstance(val, (decimal.Decimal, dict, list, datetime.datetime, datetime.date)) else val 
                for val in row
            )
            safe_rows.append(safe_row)
            
        return str(safe_rows)

@tool
def get_database_schema() -> str:
    """Get the schema of all tables in the database. Use this before writing SQL queries to understand the structure."""
    import os
    import sqlalchemy
    from sqlalchemy import create_engine, inspect
    
    engine = create_engine(os.getenv("DATABASE_URL"))
    inspector = inspect(engine)
    
    schema_info = []
    for table_name in inspector.get_table_names():
        columns = []
        for col in inspector.get_columns(table_name):
            pk = "[PK]" if col.get("primary_key") else ""
            columns.append(f"{col['name']}({col['type']}){pk}")
        schema_info.append(f"{table_name}: {', '.join(columns)}")
        
    return "\\n".join(schema_info)

# --- Agent Setup ---

def setup_agent():
    model_name = os.getenv("BENCHMARK_MODEL", "mercury-2")
    
    if model_name.startswith("mercury"):
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model_name,
            base_url="https://api.inceptionlabs.ai/v1",
            api_key=os.getenv("INCEPTION_AI"),
            temperature=0
        )
    else:
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=os.getenv("GEMINI_API_KEY"),
            temperature=0
        )

    # 2. Setup Toolbelt
    tools = [google_search, create_google_doc, send_email, sql_query, get_database_schema, list_emails, get_email_body, create_google_sheet_with_data]
    
    # 3. Setup Agent using LangChain built-in create_agent (which wraps LangGraph internally)
    agent_graph = create_agent(
        model=llm,
        tools=tools,
        system_prompt="You are a helpful research agent. Use the tools provided to complete the task."
    )
    return agent_graph

# --- Benchmark Execution ---

def run_benchmark():
    try:
        agent_executor = setup_agent()
    except Exception as e:
        print(f"\nFailed to initialize LangChain agent: {e}")
        return
    
    task = """
    1. Search the web for the top 3 major AI news announcements this week.
    2. Create a new Google Doc summarizing the news.
    3. Send an email to your-email@example.com with the link to the document.
    """
    
    print("\n" + "="*50)
    print("STARTING LANGCHAIN BENCHMARK EXECUTION")
    print("="*50)
    
    start_time = datetime.datetime.now()
    try:
        # LangChain create_agent requires this specific format
        response = agent_graph.invoke({"messages": [("user", task)]})
        final_message = response["messages"][-1]
        
        # Calculate tokens
        agent_it = 0
        agent_ot = 0
        agent_calls = 0
        
        for msg in response.get("messages", []):
            if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                agent_it += msg.usage_metadata.get("input_tokens", 0)
                agent_ot += msg.usage_metadata.get("output_tokens", 0)
                agent_calls += 1
        
        # Grand Total (Agent Calls + Nested Tool Calls)
        total_input = agent_it + HIDDEN_TOKENS["input_tokens"]
        total_output = agent_ot + HIDDEN_TOKENS["output_tokens"]
        total_tokens = total_input + total_output
        total_calls = agent_calls + HIDDEN_TOKENS["calls"]
                
        print(f"\\nFinal Response: {final_message.content}")
    except Exception as e:
        print(f"\nExecution Failed: {e}")
        total_tokens = total_input = total_output = total_calls = 0
        
    end_time = datetime.datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    print("\n" + "="*50)
    print(f"BENCHMARK COMPLETE")
    print(f"Total Execution Time: {duration:.2f}s")
    if total_tokens > 0:
        print(f"Total Tokens: {total_tokens} (Input: {total_input}, Output: {total_output})")
        print(f"Total LLM Calls: {total_calls} (Agent: {agent_calls}, Nested Tools: {HIDDEN_TOKENS['calls']})")
    print("="*50)

if __name__ == "__main__":
    run_benchmark()
