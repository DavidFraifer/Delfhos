"""
Mercury-2 vs Gemini 3.1 Lite — Delfhos Task Comparison
Runs the same tasks with both models and compares timing + results.
"""
import os, sys, time, asyncio
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from cortex.cortex import Cortex
from cortex.connections import WebSearchConnection as WebSearch, DocsConnection as Docs, GmailConnection as Gmail, SQLConnection as SQL, SheetsConnection as Sheets

TASKS = [
    {
        "name": "SQL → Sheets",
        "prompt": "Find the 5 most expensive tasks (cost > 0) in the database and create a Google Sheet named 'Top Costs' with columns: Task ID, Description, Cost."
    },
    {
        "name": "SQL → Email",
        "prompt": "Calculate the average cost of all tasks in the database and email the result to your-email@example.com with subject 'Avg Task Cost Report'."
    },
    {
        "name": "Email → Sheet → Send",
        "prompt": "Read the last 5 emails, create a Google Sheet titled 'Mail Log' with columns Date, Subject, Sender for each, then email the sheet link to your-email@example.com with subject 'Mail Log'."
    },
]

MODELS = [
    ("gemini-3.1-flash-lite-preview", "Gemini 3.1 Lite"),
    ("mercury-2", "Mercury-2"),
]

async def run_task(model_name, task_prompt):
    oauth_path = os.getenv("OAUTH_GMAIL_PATH")
    
    search = WebSearch()
    gmail = Gmail(oauth_credentials=oauth_path, allowed=["read", "send"])
    docs = Docs(oauth_credentials=oauth_path, allowed=["read", "write", "create"])
    sheets = Sheets(oauth_credentials=oauth_path, allowed=["read", "write", "create"])
    sql = SQL(url=os.getenv("DATABASE_URL"))
    
    agent = Cortex(
        tools=[search, gmail, docs, sheets, sql],
        light_llm=model_name,
        heavy_llm=model_name
    )
    
    start = time.perf_counter()
    result = await agent.arun(task_prompt)
    elapsed = time.perf_counter() - start
    
    # Get token stats from logger
    logger = agent._agent.logger
    tokens = 0
    cost = 0.0
    try:
        import json
        if os.path.exists(logger.log_file):
            with open(logger.log_file) as f:
                lines = f.readlines()
                if lines:
                    last = json.loads(lines[-1].strip())
                    tokens = last.get("tokens_used", 0)
                    cost = last.get("total_cost_usd", 0.0)
    except:
        pass
    
    agent.stop()
    return {"time": elapsed, "tokens": tokens, "cost": cost, "success": bool(result)}


async def main():
    print(f"\n{'='*70}")
    print(f"⚡ Mercury-2 vs Gemini 3.1 Lite — Delfhos Task Comparison")
    print(f"{'='*70}")
    
    results = {}
    
    for task in TASKS:
        print(f"\n{'─'*70}")
        print(f"📌 {task['name']}")
        print(f"   {task['prompt'][:70]}...")
        print(f"{'─'*70}")
        
        results[task['name']] = {}
        
        for model_id, model_label in MODELS:
            print(f"\n  {'🟢' if 'gemini' in model_id else '🔵'} {model_label}...", end="", flush=True)
            try:
                r = await run_task(model_id, task['prompt'])
                status = "✅" if r['success'] else "❌"
                print(f" {status} {r['time']:.2f}s | {r['tokens']} tok | ${r['cost']:.4f}")
                results[task['name']][model_id] = r
            except Exception as e:
                print(f" ❌ {e}")
                results[task['name']][model_id] = {"time": 0, "tokens": 0, "cost": 0, "success": False}
        
        await asyncio.sleep(1)
    
    # Summary
    print(f"\n\n{'='*70}")
    print(f"📊 COMPARISON SUMMARY")
    print(f"{'='*70}")
    print(f"{'Task':<22} | {'Gemini 3.1 Lite':>15} | {'Mercury-2':>15} | {'Winner':>10}")
    print(f"{'─'*70}")
    
    g_wins = m_wins = 0
    for task_name, models in results.items():
        g = models.get("gemini-3.1-flash-lite-preview", {})
        m = models.get("mercury-2", {})
        gt = g.get("time", 0) if g.get("success") else -1
        mt = m.get("time", 0) if m.get("success") else -1
        
        gs = f"{gt:.2f}s" if gt > 0 else "FAIL"
        ms = f"{mt:.2f}s" if mt > 0 else "FAIL"
        
        if gt > 0 and mt > 0:
            winner = "Gemini" if gt < mt else "Mercury"
            if gt < mt: g_wins += 1
            else: m_wins += 1
        elif gt > 0: winner = "Gemini"; g_wins += 1
        elif mt > 0: winner = "Mercury"; m_wins += 1
        else: winner = "N/A"
        
        print(f"{task_name:<22} | {gs:>15} | {ms:>15} | {winner:>10}")
    
    print(f"{'─'*70}")
    overall = "Gemini" if g_wins > m_wins else ("Mercury" if m_wins > g_wins else "Tie")
    print(f"{'OVERALL':<22} | {'':>15} | {'':>15} | {overall:>10} ({g_wins}-{m_wins})")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
