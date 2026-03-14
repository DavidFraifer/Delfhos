import os
import json
import datetime
from smolagents import CodeAgent, tool

# 1. Provide the exact same base tools used in LangChain
@tool
def sql_query(query: str) -> str:
    """Execute a SQL query against the database and return the results as a string.
    
    Args:
        query: The SQL query to execute (e.g., 'SELECT * FROM users').
    """
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

@tool
def get_database_schema() -> str:
    """Get the schema of all tables in the database. Use this before writing SQL queries to understand the structure.
    
    Args:
    """
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

@tool
def list_emails(query: str) -> str:
    """List recent emails matching a query.
    
    Args:
        query: The search query string (e.g., 'is:unread', 'subject:important').
    """
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

@tool
def get_email_body(message_id: str) -> str:
    """Get the full body content of a specific email by ID.
    
    Args:
        message_id: The unique string ID of the email to retrieve.
    """
    from benchmarks.langchain_agent import get_google_creds
    from googleapiclient.discovery import build
    creds = get_google_creds("gmail")
    service = build("gmail", "v1", credentials=creds)
    message = service.users().messages().get(userId="me", id=message_id).execute()
    return message.get('snippet', '')

@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to a recipient.
    
    Args:
        to: Email address of the recipient.
        subject: The subject line.
        body: The plain text body of the email.
    """
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

@tool
def create_google_doc(title: str, content: str) -> str:
    """Create a new Google Document with the title and content.
    
    Args:
        title: Title of the document.
        content: The text content to write inside the document.
    """
    from benchmarks.langchain_agent import get_google_creds
    from googleapiclient.discovery import build
    creds = get_google_creds("docs")
    service = build("docs", "v1", credentials=creds)
    
    doc = service.documents().create(body={"title": title}).execute()
    doc_id = doc.get("documentId")
    
    requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
    service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    return f"Doc created successfully. ID: {doc_id} URL: https://docs.google.com/document/d/{doc_id}/edit"

@tool
def create_google_sheet(title: str, json_data: str) -> str:
    """Create a new Google Sheet passing data as a JSON encoded list of lists.
    
    Args:
        title: Title of the spreadsheet.
        json_data: The data to insert, represented as a JSON encoded list of lists (e.g., '[["Row 1"], ["Row 2"]]').
    """
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

@tool
def google_search(query: str) -> str:
    """Search google for current information.
    
    Args:
        query: The search keywords or question.
    """
    from cortex.connections import WebSearchConnection
    search = WebSearchConnection()
    results = search.search(query, max_results=3)
    
    formatted = []
    for r in results:
        formatted.append(f"Title: {r.get('title')}\\nURL: {r.get('link')}\\nSnippet: {r.get('snippet')}\\n---")
    return "\\n".join(formatted) if formatted else "No results found."

def run_smolagents_task(benchmark_task: str):
    # Setup LLM based on benchmark config
    model_name = os.getenv("BENCHMARK_MODEL", "mercury-2")
    
    from smolagents import LiteLLMModel
    
    if model_name.startswith("mercury"):
        model = LiteLLMModel(
            model_id=f"openai/{model_name}",
            api_base="https://api.inceptionlabs.ai/v1",
            api_key=os.getenv("INCEPTION_AI"),
            temperature=0.0
        )
    else:
        model = LiteLLMModel(
            model_id=f"gemini/{model_name}",
            api_key=os.getenv("GEMINI_API_KEY"),
            temperature=0.0
        )
        
    tools = [sql_query, get_database_schema, list_emails, get_email_body, send_email, create_google_doc, create_google_sheet, google_search]

    agent = CodeAgent(
        tools=tools, 
        model=model, 
        add_base_tools=False, 
        additional_authorized_imports=["json", "sqlalchemy", "datetime", "requests", "bs4", "math", "os", "pandas"]
    )

    start_time = datetime.datetime.now()
    
    # Aggregate token usage manually from step logs
    total_input = 0
    total_output = 0
    llm_calls = 0
    
    # Run CodeAgent
    # smolagents accumulates steps in agent.logs
    try:
        output_str = str(agent.run(benchmark_task))
    except Exception as e:
        output_str = f"SmolAgents failed to run: {str(e)}"
        
    if hasattr(agent, "monitor"):
        total_input = getattr(agent.monitor, "total_input_token_count", 0)
        total_output = getattr(agent.monitor, "total_output_token_count", 0)
        # but we can count ActionStep logs that have llm_output or token_usage
        for step_log in getattr(agent.memory, "steps", []):
            if hasattr(step_log, "token_usage") and getattr(step_log, "token_usage", None) is not None:
                llm_calls += 1
                
    duration = (datetime.datetime.now() - start_time).total_seconds()
    
    return {
        "output": output_str,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_calls": llm_calls,
        "duration": duration,
    }
