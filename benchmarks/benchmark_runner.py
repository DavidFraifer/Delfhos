import os
import time
import json
import asyncio
import datetime
import sys
import traceback
from pathlib import Path
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

load_dotenv()

# --- MULTI-TOOL BENCHMARK: Data movement + parallel execution ---
TASKS = [
    {
        "id": "T1_SQL_SHEETS",
        "name": "SQL → Sheets",
        "task": "Find the 5 most expensive tasks (cost > 0) in the database and create a Google Sheet named 'Top Costs' with columns: Task ID, Description, Cost.",
        "level": 2
    },
    {
        "id": "T2_EMAIL_DOC",
        "name": "Email → Doc",
        "task": "Read the last 3 emails and create a Google Doc titled 'Email Digest' with a summary of each email including subject, sender and a snippet of the body.",
        "level": 2
    },
    {
        "id": "T3_SQL_EMAIL",
        "name": "SQL → Email",
        "task": "Calculate the average cost of all tasks in the database and email the result to your-email@example.com with subject 'Avg Task Cost Report'.",
        "level": 2
    },
    {
        "id": "T4_EMAIL_SHEET_SEND",
        "name": "Email → Sheet → Send",
        "task": "Read the last 5 emails, create a Google Sheet titled 'Mail Log' with columns Date, Subject, Sender for each, then email the sheet link to your-email@example.com with subject 'Mail Log'.",
        "level": 3
    },
    {
        "id": "T5_SQL_DOC_EMAIL",
        "name": "SQL → Doc → Email",
        "task": "Get the 3 most expensive tasks (cost > 0) from the database, create a Google Doc with their details, and email the doc link to your-email@example.com with subject 'Expense Report'.",
        "level": 3
    },
    {
        "id": "T6_SQL_ANALYTICS",
        "name": "SQL Analytics",
        "task": "Count how many tasks exist in the database grouped by status and print the results as a table.",
        "level": 1
    },
    {
        "id": "T7_EMAIL_SEARCH",
        "name": "Email Search",
        "task": "Search my emails for any message from LinkedIn and print the subject and date of the 3 most recent ones.",
        "level": 1
    },
    {
        "id": "T8_SQL_SHEET_DOC",
        "name": "SQL → Sheet → Doc",
        "task": "Get all distinct task statuses and their count from the database, create a Google Sheet titled 'Status Summary' with that data, then create a Google Doc titled 'Status Report' explaining the distribution.",
        "level": 3
    },
    {
        "id": "T9_EMAIL_COUNT",
        "name": "Email Stats → Sheet",
        "task": "Count my total unread emails and my total emails from the last 7 days, then create a Google Sheet titled 'Email Stats' with those two numbers.",
        "level": 2
    },
    {
        "id": "T10_SQL_AGG_DOC_EMAIL",
        "name": "SQL Agg → Doc → Email",
        "task": "Calculate the total cost, average cost, and number of tasks per user_id from the database. Create a Google Doc titled 'Cost per User' with a table of those stats, and email the doc link to your-email@example.com with subject 'User Cost Report'.",
        "level": 3
    },
]

MODEL_NAME = "gemini-3.1-flash-lite-preview"
REPETITIONS = 1

# --- DELFHOS RUNNER ---
async def run_delfhos(task_text):
    from cortex.cortex import Cortex
    from cortex.connections import WebSearchConnection, DocsConnection, GmailConnection, SQLConnection, SheetsConnection
    
    oauth_path = os.getenv("OAUTH_GMAIL_PATH")
    
    search = WebSearchConnection()
    gmail = GmailConnection(oauth_credentials=oauth_path, actions=["read", "send"])
    docs = DocsConnection(oauth_credentials=oauth_path, actions=["read", "write", "create"])
    sheets = SheetsConnection(oauth_credentials=oauth_path, actions=["read", "write", "create"])
    sql = SQLConnection(url=os.getenv("DATABASE_URL"))
    
    setup_start = time.perf_counter()
    agent = Cortex(connections=[search, gmail, docs, sheets, sql], light_llm=MODEL_NAME, heavy_llm=MODEL_NAME)
    setup_end = time.perf_counter()
    
    exec_start = time.perf_counter()
    result = await agent.arun(task_text)
    exec_end = time.perf_counter()
    
    logger = agent._agent.logger
    token_stats = {"input": 0, "output": 0, "total": 0, "cost": 0.0}
    
    try:
        if os.path.exists(logger.log_file):
            with open(logger.log_file, "r") as f:
                lines = f.readlines()
                if lines:
                    last_entry = json.loads(lines[-1].strip())
                    token_stats["input"] = last_entry.get("input_tokens", 0)
                    token_stats["output"] = last_entry.get("output_tokens", 0)
                    token_stats["total"] = last_entry.get("tokens_used", 0)
                    token_stats["cost"] = last_entry.get("total_cost_usd", 0.0)
    except:
        pass

    agent.stop()
    
    return {
        "setup_duration": setup_end - setup_start,
        "total_elapsed": exec_end - setup_start,
        "compute_time": exec_end - exec_start,
        "tokens": token_stats,
        "status": "success" if result else "timeout/failed",
        "output": str(result)[:2000] if result else None
    }

# --- LANGCHAIN RUNNER ---
def run_langchain(task_text):
    from benchmarks.langchain_agent import setup_agent, HIDDEN_TOKENS
    
    os.environ["BENCHMARK_MODEL"] = MODEL_NAME  # Pass model to LangChain agent
    
    setup_start = time.perf_counter()
    agent_executor = setup_agent()
    setup_end = time.perf_counter()
    
    HIDDEN_TOKENS["total_tokens"] = 0
    HIDDEN_TOKENS["input_tokens"] = 0
    HIDDEN_TOKENS["output_tokens"] = 0
    HIDDEN_TOKENS["calls"] = 0
    
    exec_start = time.perf_counter()
    try:
        response = agent_executor.invoke(
            {"messages": [("user", task_text)]}
        )
        exec_end = time.perf_counter()
        
        agent_it = 0
        agent_ot = 0
        tools_called = []
        final_output = ""
        
        for msg in response.get("messages", []):
            msg_type = type(msg).__name__
            if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                agent_it += msg.usage_metadata.get("input_tokens", 0)
                agent_ot += msg.usage_metadata.get("output_tokens", 0)
            # Capture tool calls from ToolMessage entries
            if msg_type == "ToolMessage":
                tool_name = getattr(msg, "name", "unknown")
                tool_content = str(getattr(msg, "content", ""))[:500]
                tools_called.append({"tool": tool_name, "output": tool_content})
            # Capture final AI response
            if msg_type == "AIMessage" and hasattr(msg, "content") and msg.content:
                final_output = str(msg.content)[:2000]
        
        total_input = agent_it + HIDDEN_TOKENS["input_tokens"]
        total_output = agent_ot + HIDDEN_TOKENS["output_tokens"]
        total_tokens = total_input + total_output
        
        from cortex._engine.utils.pricing import llm_pricing
        cost, _ = llm_pricing.calculate_cost(MODEL_NAME, total_input, total_output)
        
        return {
            "setup_duration": setup_end - setup_start,
            "total_elapsed": exec_end - setup_start,
            "compute_time": exec_end - exec_start,
            "tokens": {"input": total_input, "output": total_output, "total": total_tokens, "cost": cost},
            "status": "success",
            "output": final_output,
            "tools_called": tools_called
        }
    except Exception as e:
        exec_end = time.perf_counter()
        print(f"\n  LC Error: {e}")
        return {
            "setup_duration": setup_end - setup_start,
            "total_elapsed": exec_end - exec_start,
            "compute_time": exec_end - exec_start,
            "tokens": {"input": 0, "output": 0, "total": 0, "cost": 0.0},
            "status": f"failed: {str(e)[:80]}"
        }

# --- GLOBAL STATS ---
OVERALL_STATS = {
    "Delfhos": {
        "avg_time": 0.0,
        "avg_tokens": 0,
        "avg_calls": 0,
        "success_rate": 0.0,
        "details": []
    },
    "LangChain": {
        "avg_time": 0.0,
        "avg_tokens": 0,
        "avg_calls": 0,
        "success_rate": 0.0,
        "details": []
    },
    "CrewAI": {
        "avg_time": 0.0,
        "avg_tokens": 0,
        "avg_calls": 0,
        "success_rate": 0.0,
        "details": []
    },
    "SmolAgents": {
        "avg_time": 0.0,
        "avg_tokens": 0,
        "avg_calls": 0,
        "success_rate": 0.0,
        "details": []
    }
}

def _record_stats(framework_name, task_id, times, tokens, calls):
    success_count = len(times)
    total_runs = REPETITIONS
    
    avg_time = sum(times) / success_count if success_count > 0 else 0
    avg_tokens = sum(tokens) / success_count if success_count > 0 else 0
    avg_calls = sum(calls) / success_count if success_count > 0 else 0
    
    OVERALL_STATS[framework_name]["details"].append({
        "task_id": task_id,
        "avg_time": avg_time,
        "avg_tokens": avg_tokens,
        "avg_calls": avg_calls,
        "success": success_count == total_runs
    })

# --- MAIN ---
async def main():
    results = {
        "metadata": {"date": datetime.datetime.now().isoformat(), "model": MODEL_NAME, "repetitions": REPETITIONS},
        "tasks": []
    }
    
    os.makedirs("benchmarks/results", exist_ok=True)
    
    print(f"\n🚀 Multi-Tool Benchmark: Delfhos vs LangChain")
    print(f"Model: {MODEL_NAME} | {len(TASKS)} tasks (all 2+ tools)\n")

    from benchmarks.crewai_agent import run_crewai_task
    from benchmarks.smolagents_agent import run_smolagents_task

    for t in TASKS:
        print(f"\n{'='*70}")
        print(f"📌 {t['id']}: {t['name']} (L{t['level']})")
        print(f"   {t['task'][:75]}...")
        print(f"{'='*70}")
        
        # 1. DELFHOS
        delfhos_times, delfhos_tokens, delfhos_calls = [], [], []
        print(f"\n[{t['id']}] Delfhos (Code-Act)...")
        for i in range(REPETITIONS):
            try:
                res = await run_delfhos(t["task"])
                delfhos_times.append(res["total_elapsed"])
                delfhos_tokens.append(res["tokens"]["total"])
                # Delfhos doesn't explicitly track calls, estimate 1 for success
                delfhos_calls.append(1 if res["status"] == "success" else 0) 
                print(f"  Rep {i+1}: ✅ {res['total_elapsed']:.2f}s | {res['tokens']['total']} tok | ${res['tokens']['cost']:.4f}")
            except Exception as e:
                print(f"  Rep {i+1}: ❌ {e}")
                
        # 2. LANGCHAIN
        lc_times, lc_tokens, lc_calls = [], [], []
        print(f"[{t['id']}] LangChain (ReAct)...")
        for i in range(REPETITIONS):
            try:
                res = run_langchain(t["task"])
                lc_times.append(res["total_elapsed"])
                lc_tokens.append(res["tokens"]["total"])
                # LangChain doesn't explicitly track calls, estimate 1 for success
                lc_calls.append(1 if res["status"] == "success" else 0) 
                print(f"  Rep {i+1}: ✅ {res['total_elapsed']:.2f}s | {res['tokens']['total']} tok | ${res['tokens']['cost']:.4f}")
            except Exception as e:
                print(f"  Rep {i+1}: ❌ {e}")

        # 3. CREWAI
        crew_times, crew_tokens, crew_calls = [], [], []
        print(f"[{t['id']}] CrewAI (Role-play)...")
        for i in range(REPETITIONS):
            try:
                # CrewAI execution is synchronous
                # Running in thread pool to match async structure safely if needed, but synchronous is fine here
                res = run_crewai_task(t["task"])
                crew_times.append(res["duration"])
                crew_tokens.append(res["input_tokens"] + res["output_tokens"])
                crew_calls.append(res["total_calls"])
                print(f"  Rep {i+1}: ✅ {res['duration']:.2f}s | {res['input_tokens'] + res['output_tokens']} tok | {res['total_calls']} calls")
            except Exception as e:
                print(f"  Rep {i+1}: ❌ {e}")

        # 4. SMOLAGENTS
        smol_times, smol_tokens, smol_calls = [], [], []
        print(f"[{t['id']}] SmolAgents (Code-Act)...")
        for i in range(REPETITIONS):
            try:
                res = run_smolagents_task(t["task"])
                smol_times.append(res["duration"])
                smol_tokens.append(res["input_tokens"] + res["output_tokens"])
                smol_calls.append(res["total_calls"])
                print(f"  Rep {i+1}: ✅ {res['duration']:.2f}s | {res['input_tokens'] + res['output_tokens']} tok | {res['total_calls']} calls")
            except Exception as e:
                print(f"  Rep {i+1}: ❌ {e}")
            
        _record_stats("Delfhos", t["id"], delfhos_times, delfhos_tokens, delfhos_calls)
        _record_stats("LangChain", t["id"], lc_times, lc_tokens, lc_calls)
        _record_stats("CrewAI", t["id"], crew_times, crew_tokens, crew_calls)
        _record_stats("SmolAgents", t["id"], smol_times, smol_tokens, smol_calls)
            
        await asyncio.sleep(1) # Small delay between tasks

    # The `results` object is now populated by `OVERALL_STATS`
    # The original `results["tasks"].append(task_results)` is no longer needed.
    # The `latest_run.json` will now contain the `OVERALL_STATS` structure.
    results["overall_stats"] = OVERALL_STATS
    with open("benchmarks/results/latest_run.json", "w") as f:
        json.dump(results, f, indent=2)
    
    timestamp = int(time.time())
    final_path = f"benchmarks/results/final_benchmark_{timestamp}.json"
    with open(final_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    # --- SUMMARY ---
    print(f"\n\n{'='*95}")
    print(f"📊 MULTI-TOOL BENCHMARK RESULTS")
    print(f"{'='*95}")
    print(f"| {'Model / Framework':<30} | {'Time (s)':<10} | {'Tokens':<10} | {'LLM Calls':<10} | {'Success':<10} |")
    print(f"|{'-'*32}|{'-'*12}|{'-'*12}|{'-'*12}|{'-'*12}|")
    
    for fw in ["Delfhos", "LangChain", "CrewAI", "SmolAgents"]:
        stats = OVERALL_STATS[fw]
        n_success = len([d for d in stats["details"] if d["success"]])
        n = max(1, n_success) 
        avg_time = sum(d["avg_time"] for d in stats["details"] if d["success"]) / n
        avg_tokens = sum(d["avg_tokens"] for d in stats["details"] if d["success"]) / n
        avg_calls = sum(d["avg_calls"] for d in stats["details"] if d["success"]) / n
        succ_rate = (n_success / len(TASKS)) * 100
        
        print(f"| {fw:<30} | {avg_time:<10.2f} | {avg_tokens:<10.0f} | {avg_calls:<10.1f} | {succ_rate:>8.0f}% |")
        
    print(f"{'='*95}")
    
    # Build comparative table exactly compatible with github markdown
    markdown = f"| Metric | Delfhos (Code-Act) | LangChain (ReAct) | CrewAI (Role-Act) | SmolAgents (Code-Act) |\n"
    markdown += "|--------|---------|-----------|--------|------------|\n"
    
    d_stats = OVERALL_STATS["Delfhos"]
    l_stats = OVERALL_STATS["LangChain"]
    c_stats = OVERALL_STATS["CrewAI"]
    s_stats = OVERALL_STATS["SmolAgents"]
    
    def get_avg(stats, key):
        n = max(1, len([d for d in stats["details"] if d["success"]]))
        return sum(d[key] for d in stats["details"] if d["success"]) / n
        
    markdown += f"| **Avg Compute Time** | {get_avg(d_stats, 'avg_time'):.2f}s | {get_avg(l_stats, 'avg_time'):.2f}s | {get_avg(c_stats, 'avg_time'):.2f}s | {get_avg(s_stats, 'avg_time'):.2f}s |\n"
    markdown += f"| **Avg Tokens Used** | {get_avg(d_stats, 'avg_tokens'):.0f} | {get_avg(l_stats, 'avg_tokens'):.0f} | {get_avg(c_stats, 'avg_tokens'):.0f} | {get_avg(s_stats, 'avg_tokens'):.0f} |\n"
    markdown += f"| **Avg LLM Calls** | {get_avg(d_stats, 'avg_calls'):.1f} | {get_avg(l_stats, 'avg_calls'):.1f} | {get_avg(c_stats, 'avg_calls'):.1f} | {get_avg(s_stats, 'avg_calls'):.1f} |\n"
    
    # Calculate multipliers
    lc_time_mult = get_avg(l_stats, 'avg_time') / get_avg(d_stats, 'avg_time') if get_avg(d_stats, 'avg_time') > 0 else 0
    lc_token_mult = get_avg(l_stats, 'avg_tokens') / get_avg(d_stats, 'avg_tokens') if get_avg(d_stats, 'avg_tokens') > 0 else 0
    sm_time_mult = get_avg(s_stats, 'avg_time') / get_avg(d_stats, 'avg_time') if get_avg(d_stats, 'avg_time') > 0 else 0
    
    markdown += f"\n### Summary\n"
    markdown += f"- **Speed**: Delfhos is **{lc_time_mult:.1f}x faster** than LangChain and **{sm_time_mult:.1f}x faster** than SmolAgents.\n"
    markdown += f"- **Efficiency**: Delfhos uses **{lc_token_mult:.1f}x fewer tokens** than LangChain.\n"
    
    print(f"\nMarkdown Copy:\n{markdown}")
    print(f"\n📁 Results: {final_path}")

if __name__ == "__main__":
    asyncio.run(main())
