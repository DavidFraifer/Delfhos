import os
import datetime
import asyncio
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

# Trackers
HIDDEN_TOKENS = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

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
        
        safe_rows = []
        for row in rows:
            safe_row = tuple(
                str(val) if isinstance(val, (decimal.Decimal, dict, list, datetime.datetime, datetime.date)) else val 
                for val in row
            )
            safe_rows.append(safe_row)
            
        return str(safe_rows)

@tool
def write_file(filename: str, content: str) -> str:
    """Write text content to a local file."""
    with open(filename, 'w') as f:
        f.write(content)
    return f"Successfully wrote to {filename}"

def run_benchmark():
    # Load env vars manually since we might be in benchmarks folder
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
    
    model_name = os.getenv("BENCHMARK_MODEL", "mercury-2")
    
    llm = ChatOpenAI(
        model=model_name,
        base_url="https://api.inceptionlabs.ai/v1",
        api_key=os.getenv("INCEPTION_AI"),
        temperature=0
    )

    tools = [sql_query, write_file]
    
    agent_executor = create_agent(
        model=llm,
        tools=tools,
        system_prompt="You are a helpful research agent. Use the tools provided to complete the task."
    )
    
    task = """
Find the 5 most expensive tasks in the database and create a local file called 'expensive_tasks_lc.txt'.

Database schema:
tasks: id(uuid)[PK], agent_id(uuid), description(text), status(text), started_at(timestamp with time zone), completed_at(timestamp with time zone), result(text), compute_time(real), tools_used(jsonb), created_at(timestamp with time zone), tool_timings(jsonb), elapsed_time(real), is_periodic(boolean), next_execution_at(timestamp with time zone), execution_count(integer), tokens_used(integer), cost(double precision), user_id(uuid)[FK]
"""
    
    print("\n" + "="*50)
    print(f"STARTING LANGCHAIN (Model: {model_name})")
    print("Task:", task)
    print("="*50)
    
    start_time = datetime.datetime.now()
    try:
        response = agent_executor.invoke({"messages": [("user", task)]})
        final_message = response["messages"][-1]
        
        agent_it = 0
        agent_ot = 0
        agent_calls = 0
        
        for msg in response.get("messages", []):
            if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                agent_it += msg.usage_metadata.get("input_tokens", 0)
                agent_ot += msg.usage_metadata.get("output_tokens", 0)
                agent_calls += 1
        
        total_tokens = agent_it + agent_ot
        duration = (end_time := datetime.datetime.now() - start_time).total_seconds()
        
        print(f"\nFinal Response: {final_message.content}")
    except Exception as e:
        print(f"\nExecution Failed: {e}")
        duration = (datetime.datetime.now() - start_time).total_seconds()
        total_tokens = agent_it = agent_ot = agent_calls = 0
        
    print("\n" + "="*50)
    print(f"BENCHMARK COMPLETE")
    print(f"Total Execution Time: {duration:.2f}s")
    if total_tokens > 0:
        print(f"Total Tokens: {total_tokens} (Input: {agent_it}, Output: {agent_ot})")
        print(f"Total LLM Calls: {agent_calls}")
    print("="*50)

if __name__ == "__main__":
    run_benchmark()
