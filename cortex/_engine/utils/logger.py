import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from ..config.pricing import calculate_cost_usd, get_user_pricing_path, has_pricing_for_model
from .console import console

class CORTEXLogger:

    def __init__(self, log_file: Optional[str] = None):
        # Legacy task-file logging is opt-in only.
        self.log_file = Path(log_file) if log_file else None
        if self.log_file and self.log_file.parent and str(self.log_file.parent) != ".":
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.active_tasks: Dict[str, Dict[str, Any]] = {}
        self._warned_unpriced_models = set()
        # Optional callback fired each time an LLM call accrues cost (USD).
        # Used by Agent to enforce budget guardrails across tasks.
        self.on_cost_accrued: Optional[Callable[[float], None]] = None
        
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
            "total_cost_usd": None,
            "pricing_path": get_user_pricing_path(),
            "llm_breakdown": [],
            "status": "running",
        }
    
    def add_tokens(self, task_id: str, token_info: dict, model=None, function_name: str = None, duration: float = None):
        if task_id in self.active_tasks:
            input_tokens = token_info.get("input_tokens", 0)
            output_tokens = token_info.get("output_tokens", 0)
            total_tokens = token_info.get("total_tokens", 0)
            image_count = token_info.get("image_count", 0)
            # Normalize model to string — handles LLMConfig objects and other non-string values
            if model is not None and not isinstance(model, str):
                model = getattr(model, "model", str(model))
            model_key = (model or "").strip().lower()
            pricing_available = bool(model_key) and has_pricing_for_model(model)
            if model_key and not pricing_available and model_key not in self._warned_unpriced_models:
                console.warning(
                    "Pricing missing",
                    f"No USD pricing configured for model '{model}'. Cost will not be calculated for this model. Add it to {get_user_pricing_path()}.",
                    task_id=task_id,
                )
                self._warned_unpriced_models.add(model_key)

            call_cost_usd = calculate_cost_usd(model, input_tokens, output_tokens) if pricing_available else None
            
            # Update token and image counts
            self.active_tasks[task_id]["tokens_used"] += total_tokens
            self.active_tasks[task_id]["input_tokens"] += input_tokens
            self.active_tasks[task_id]["output_tokens"] += output_tokens
            self.active_tasks[task_id]["llm_calls"] += 1
            if call_cost_usd is not None:
                if self.active_tasks[task_id]["total_cost_usd"] is None:
                    self.active_tasks[task_id]["total_cost_usd"] = 0.0
                self.active_tasks[task_id]["total_cost_usd"] += call_cost_usd
                if self.on_cost_accrued is not None:
                    try:
                        self.on_cost_accrued(call_cost_usd)
                    except Exception:
                        pass
            if image_count:
                self.active_tasks[task_id].setdefault("image_calls", 0)
                self.active_tasks[task_id].setdefault("images_used", 0)
                self.active_tasks[task_id]["image_calls"] += 1
                self.active_tasks[task_id]["images_used"] += image_count
            
            # Track per-call usage metadata if model is provided
            if model:
                llm_entry = {
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "image_count": image_count,
                    "duration": duration,
                    "cost_usd": call_cost_usd,
                    "function_name": function_name or "unknown",
                    "timestamp": datetime.now().isoformat()
                }
                self.active_tasks[task_id]["llm_breakdown"].append(llm_entry)
    
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
        if not self.log_file:
            return

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
                "total_cost_usd": round(task_data.get("total_cost_usd"), 8) if task_data.get("total_cost_usd") is not None else None,
                "pricing_path": task_data.get("pricing_path"),
                "llm_breakdown": task_data.get("llm_breakdown", []),
                "status": task_data["status"],
            }
            
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
                
        except Exception as e:
            print(f"⚠️ [Logger] Failed to write log entry: {e}")
    
    def get_log_stats(self) -> Dict[str, Any]:
        if not self.log_file:
            return self._empty_stats()

        if not self.log_file.exists():
            return self._empty_stats()
        
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
            
            if not lines:
                return self._empty_stats()
            
                stats = {"total_tasks": 0, "total_duration": 0, "total_tokens": 0, "total_input_tokens": 0,
                    "total_output_tokens": 0, "total_llm_calls": 0, "total_iterations": 0, 
                    "completed_tasks": 0, "total_cost_usd": None}
            
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
                    cost = entry.get("total_cost_usd")
                    if cost is not None:
                        if stats["total_cost_usd"] is None:
                            stats["total_cost_usd"] = 0.0
                        stats["total_cost_usd"] += float(cost)
                    
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
                "avg_cost_usd": round(stats["total_cost_usd"] / stats["total_tasks"], 6) if stats["total_cost_usd"] is not None else None,
                "avg_iterations": round(stats["total_iterations"] / stats["total_tasks"], 1),
                "total_duration": round(stats["total_duration"], 2),
                "total_cost_usd": round(stats["total_cost_usd"], 6) if stats["total_cost_usd"] is not None else None,
                "log_file": str(self.log_file)
            })
            
            return stats
            
        except Exception as e:
            print(f"⚠️ [Logger] Error reading log stats: {e}")
            return {"error": str(e), "total_tasks": 0, "total_tokens": 0, "log_file": str(self.log_file)}
    
    def _empty_stats(self) -> Dict[str, Any]:
        return {
            "total_tasks": 0,
            "total_tokens": 0,
            "total_iterations": 0,
            "log_file": str(self.log_file) if self.log_file else None,
        }
