import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any
from .pricing import llm_pricing

class CORTEXLogger:

    def __init__(self, log_file: str = ".delfhos/tasks.jsonl"):
        self.log_file = Path(log_file)
        if self.log_file.parent and str(self.log_file.parent) != ".":
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.active_tasks: Dict[str, Dict[str, Any]] = {}
        
    def start_task(self, task_id: str, message: str, agent_id: str = "unknown"):
        if task_id in self.active_tasks:
            # If task already exists (e.g. started by summarizer), just update the message/agent if needed
            if self.active_tasks[task_id].get("message") == "Conversation Summarization":
                self.active_tasks[task_id]["message"] = message
            return

        self.active_tasks[task_id] = {
            "task_id": task_id,
            "agent_id": agent_id,
            "message": message,
            "start_time": time.time(),
            "start_datetime": datetime.now(timezone.utc).isoformat(),
            "iterations": 0,
            "tokens_used": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "llm_calls": 0,
            "total_cost": 0.0,
            "cost_breakdown": [],
            "status": "running",
        }
    
    def add_tokens(self, task_id: str, token_info: dict, model: str = None, function_name: str = None, duration: float = None):
        if task_id in self.active_tasks:
            input_tokens = token_info.get("input_tokens", 0)
            output_tokens = token_info.get("output_tokens", 0)
            total_tokens = token_info.get("total_tokens", 0)
            image_count = token_info.get("image_count", 0)
            
            # Update token and image counts
            self.active_tasks[task_id]["tokens_used"] += total_tokens
            self.active_tasks[task_id]["input_tokens"] += input_tokens
            self.active_tasks[task_id]["output_tokens"] += output_tokens
            self.active_tasks[task_id]["llm_calls"] += 1
            if image_count:
                self.active_tasks[task_id].setdefault("image_calls", 0)
                self.active_tasks[task_id].setdefault("images_used", 0)
                self.active_tasks[task_id]["image_calls"] += 1
                self.active_tasks[task_id]["images_used"] += image_count
            
            # Calculate cost if model is provided
            if model:
                cost, cost_breakdown = llm_pricing.calculate_cost(model, input_tokens, output_tokens, image_count=image_count)
                self.active_tasks[task_id]["total_cost"] += cost
                
                # Add to cost breakdown for detailed tracking
                cost_entry = {
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "image_count": image_count,
                    "cost": cost,
                    "duration": duration,
                    "function_name": function_name or "unknown",
                    "timestamp": datetime.now().isoformat()
                }
                self.active_tasks[task_id]["cost_breakdown"].append(cost_entry)
    
    def complete_task(self, task_id: str, status: str = "completed", computational_time: float = None):
        if task_id not in self.active_tasks:
            return
        
        task_data = self.active_tasks[task_id]
        task_data["status"] = status
        task_data["end_time"] = time.time()
        task_data["end_datetime"] = datetime.now(timezone.utc).isoformat()
        task_data["duration_seconds"] = round(task_data["end_time"] - task_data["start_time"], 2)
        
        # Add computational time if provided
        if computational_time is not None:
            task_data["computation_seconds"] = round(computational_time, 2)
        
        # Write to log file
        self._write_log_entry(task_data)
        
        # Remove from active tasks
        del self.active_tasks[task_id]
        

    def _write_log_entry(self, task_data: Dict[str, Any]):
        try:
            log_entry = {
                "task_id": task_data["task_id"],
                "agent_id": task_data.get("agent_id", "unknown"),
                "message": task_data["message"],
                "start_time": task_data["start_datetime"],
                "end_time": task_data["end_datetime"],
                "duration_seconds": task_data["duration_seconds"],
                "computation_seconds": task_data.get("computation_seconds", task_data["duration_seconds"]),
                "iterations": task_data["iterations"],
                "tokens_used": task_data["tokens_used"],
                "input_tokens": task_data.get("input_tokens", 0),
                "output_tokens": task_data.get("output_tokens", 0),
                "llm_calls": task_data.get("llm_calls", 0),
                "total_cost_usd": round(task_data.get("total_cost", 0.0), 6),
                "cost_breakdown": task_data.get("cost_breakdown", []),
                "status": task_data["status"],
            }
            
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
                
        except Exception as e:
            print(f"⚠️ [Logger] Failed to write log entry: {e}")
    
    def get_log_stats(self) -> Dict[str, Any]:
        if not self.log_file.exists():
            return self._empty_stats()
        
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
            
            if not lines:
                return self._empty_stats()
            
            stats = {"total_tasks": 0, "total_duration": 0, "total_tokens": 0, "total_input_tokens": 0, 
                    "total_output_tokens": 0, "total_llm_calls": 0, "total_iterations": 0, 
                    "completed_tasks": 0}
            
            for line in lines:  
                try:
                    entry = json.loads(line)
                    stats["total_tasks"] += 1
                    stats["total_duration"] += entry.get("duration_seconds", 0)
                    stats["total_tokens"] += entry.get("tokens_used", 0)
                    stats["total_input_tokens"] += entry.get("input_tokens", 0)
                    stats["total_output_tokens"] += entry.get("output_tokens", 0)
                    stats["total_llm_calls"] += entry.get("llm_calls", 0)
                    stats["total_iterations"] += entry.get("iterations", 0)
                    
                    if entry.get("status") == "completed":
                        stats["completed_tasks"] += 1
                        
                except (json.JSONDecodeError, Exception) as e:
                    print(f"⚠️ [Logger] Skipping malformed log line: {e}")
                    continue
            
            if stats["total_tasks"] == 0:
                return self._empty_stats()
            
            # Add averages
            stats.update({
                "avg_duration": round(stats["total_duration"] / stats["total_tasks"], 2),
                "avg_tokens": round(stats["total_tokens"] / stats["total_tasks"], 1),
                "avg_iterations": round(stats["total_iterations"] / stats["total_tasks"], 1),
                "total_duration": round(stats["total_duration"], 2),
                "log_file": str(self.log_file)
            })
            
            return stats
            
        except Exception as e:
            print(f"⚠️ [Logger] Error reading log stats: {e}")
            return {"error": str(e), "total_tasks": 0, "total_tokens": 0, "log_file": str(self.log_file)}
    
    def _empty_stats(self) -> Dict[str, Any]:
        return {"total_tasks": 0, "total_tokens": 0, "total_iterations": 0, "log_file": str(self.log_file)}
