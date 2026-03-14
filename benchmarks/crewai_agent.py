import os
import json
import datetime
from crewai.tools import tool
from crewai import Agent, Task, Crew, Process

# Global dictionary to track tokens & latency explicitly without depending strictly on CrewAI internals
CREW_METRICS = {
    "total_duration": 0.0,
    "input_tokens": 0,
    "output_tokens": 0,
    "llm_calls": 0
}

# 1. Provide the exact same base tools used in LangChain
@tool("SQL Query Tool")
def sql_query(query: str) -> str:
    """Execute a SQL query against the database and return the results as a string."""
    import sqlalchemy
    from sqlalchemy import create_engine, text
    import decimal
    
    engine = create_engine(os.getenv("DATABASE_URL"))
    with engine.connect() as connection:
        result = connection.execute(text(query))
        rows = result.fetchall()
        
        safe_rows = []
        for row in rows:
            safe_row = tuple(
                str(val) if isinstance(val, (decimal.Decimal, dict, list, datetime.datetime, datetime.date)) else val 
                for val in row
            )
            safe_rows.append(safe_row)
            
        return str(safe_rows)

@tool("Get Database Schema Tool")
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

@tool("List Emails Tool")
def list_emails(query: str) -> str:
    """List recent emails matching a query."""
    from benchmarks.langchain_agent import get_google_creds
    from googleapiclient.discovery import build
    creds = get_google_creds("gmail")
    service = build("gmail", "v1", credentials=creds)
    results = service.users().messages().list(userId="me", q=query, maxResults=5).execute()
    messages = results.get("messages", [])
    if not messages:
        return "No emails found."
    lines = []
    for msg in messages:
        m = service.users().messages().get(userId="me", id=msg['id'], format='minimal').execute()
        subject = next((h['value'] for h in m.get('payload', {}).get('headers', []) if h['name'].lower() == 'subject'), 'No Subject')
        lines.append(f"ID: {msg['id']} | Subject: {subject} | Snippet: {m.get('snippet', '')[:50]}...")
    return "\\n".join(lines)

@tool("Get Email Body Tool")
def get_email_body(message_id: str) -> str:
    """Get the full body content of a specific email by ID."""
    from benchmarks.langchain_agent import get_google_creds
    from googleapiclient.discovery import build
    creds = get_google_creds("gmail")
    service = build("gmail", "v1", credentials=creds)
    message = service.users().messages().get(userId="me", id=message_id).execute()
    return message.get('snippet', '')

@tool("Send Email Tool")
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to a recipient."""
    from benchmarks.langchain_agent import get_google_creds
    from googleapiclient.discovery import build
    from email.message import EmailMessage
    import base64
    
    creds = get_google_creds("gmail")
    service = build("gmail", "v1", credentials=creds)
    
    message = EmailMessage()
    message.set_content(body)
    message["To"] = to
    message["Subject"] = subject
    
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {"raw": encoded_message}
    service.users().messages().send(userId="me", body=create_message).execute()
    return f"Email sent successfully to {to}"

@tool("Create Google Doc Tool")
def create_google_doc(title: str, content: str) -> str:
    """Create a new Google Document with the title and content."""
    from benchmarks.langchain_agent import get_google_creds
    from googleapiclient.discovery import build
    creds = get_google_creds("docs")
    service = build("docs", "v1", credentials=creds)
    
    doc = service.documents().create(body={"title": title}).execute()
    doc_id = doc.get("documentId")
    
    requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
    service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    return f"Doc created successfully. ID: {doc_id} URL: https://docs.google.com/document/d/{doc_id}/edit"

@tool("Create Google Sheet Tool")
def create_google_sheet(title: str, json_data: str) -> str:
    """Create a new Google Sheet passing data as a JSON encoded list of lists."""
    from benchmarks.langchain_agent import get_google_creds
    from googleapiclient.discovery import build
    import json
    
    creds = get_google_creds("sheets")
    service = build("sheets", "v4", credentials=creds)
    
    sheet = service.spreadsheets().create(body={"properties": {"title": title}}).execute()
    sheet_id = sheet.get("spreadsheetId")
    
    data = json.loads(json_data)
    body = {"values": data}
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id, range="A1",
        valueInputOption="USER_ENTERED", body=body
    ).execute()
    
    return f"Sheet created successfully. ID: {sheet_id} URL: https://docs.google.com/spreadsheets/d/{sheet_id}/edit"

@tool("Google Search Tool")
def google_search(query: str) -> str:
    """Search google for current information."""
    from cortex.connections import WebSearchConnection
    search = WebSearchConnection()
    results = search.search(query, max_results=3)
    
    formatted = []
    for r in results:
        formatted.append(f"Title: {r.get('title')}\\nURL: {r.get('link')}\\nSnippet: {r.get('snippet')}\\n---")
    return "\\n".join(formatted) if formatted else "No results found."

def run_crewai_task(benchmark_task: str):
    # Setup LLM based on benchmark config
    model_name = os.getenv("BENCHMARK_MODEL", "mercury-2")
    
    if model_name.startswith("mercury"):
        # Explicit instantiation because CrewAI uses LiteLLM heavily
        from langchain_openai import ChatOpenAI
        # Set environment variables for LiteLLM under the hood
        os.environ["OPENAI_API_KEY"] = os.getenv("INCEPTION_AI")
        os.environ["OPENAI_API_BASE"] = "https://api.inceptionlabs.ai/v1"
        llm = ChatOpenAI(model=model_name, base_url="https://api.inceptionlabs.ai/v1", api_key=os.getenv("INCEPTION_AI"))
    else:
        # Assuming gemini
        os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY")
        # CrewAI supports Google models via standard string formatted ids if key is set
        llm = f"gemini/{model_name}"
        
    # We create a single versatile agent containing all tools, to mimic the setup of the others
    # which act as zero-shot general purpose agents.
    agent = Agent(
        role='General Purpose Task Agent',
        goal='Solve user tasks completely by using tools available to you.',
        backstory='You are an elite research agent built to orchestrate multiple integrations precisely. You prioritize answering exactly what is asked.',
        verbose=False,
        allow_delegation=False,
        tools=[sql_query, get_database_schema, list_emails, get_email_body, send_email, create_google_doc, create_google_sheet, google_search],
        llm=llm
    )

    task_obj = Task(
        description=f"Your objective: {benchmark_task}\\nThink step by step and execute.",
        expected_output="Final confirmation string regarding the accomplished task.",
        agent=agent
    )

    crew = Crew(
        agents=[agent],
        tasks=[task_obj],
        verbose=False,
        process=Process.sequential
    )

    start_time = datetime.datetime.now()
    
    # Run crew
    try:
        result = crew.kickoff()
        output_str = str(result)
        
    except Exception as e:
        output_str = f"CrewAI failed to run: {str(e)}"

    # Pull tokens out of the Crew usage metrics object if it exists (even if it failed half-way)
    if hasattr(crew, 'usage_metrics') and crew.usage_metrics:
        metrics = crew.usage_metrics
        CREW_METRICS["input_tokens"] = getattr(metrics, 'prompt_tokens', 0)
        CREW_METRICS["output_tokens"] = getattr(metrics, 'completion_tokens', 0)
        CREW_METRICS["llm_calls"] = getattr(metrics, 'successful_requests', 0)
    else:
        CREW_METRICS["input_tokens"] = 0
        CREW_METRICS["output_tokens"] = 0
        CREW_METRICS["llm_calls"] = 0
        
    CREW_METRICS["total_duration"] = (datetime.datetime.now() - start_time).total_seconds()
    
    return {
        "output": output_str,
        "input_tokens": CREW_METRICS["input_tokens"],
        "output_tokens": CREW_METRICS["output_tokens"],
        "total_calls": CREW_METRICS["llm_calls"],
        "duration": CREW_METRICS["total_duration"],
    }
