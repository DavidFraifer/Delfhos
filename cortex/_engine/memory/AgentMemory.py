from typing import Dict, Optional, List
from .TaskMemory import TaskMemory

class AgentMemory:
    def __init__(self, agent_id: str, max_tasks: int = 100):
        self.agent_id = agent_id
        self.max_tasks = max_tasks
        self._task_memories: Dict[str, TaskMemory] = {}
        self._task_order: List[str] = []
    
    def create_task_memory(self, task_id: str, max_lines: int = 50) -> TaskMemory:
        task_memory = TaskMemory(task_id, max_lines)
        self.add_task_memory(task_memory)
        return task_memory
    
    def add_task_memory(self, task_memory: TaskMemory) -> None:
        task_id = task_memory.name
        
        if task_id not in self._task_memories:
            self._task_order.append(task_id)
            self._cleanup_if_needed()
        
        self._task_memories[task_id] = task_memory
    
    def get_task_memory(self, task_id: str) -> Optional[TaskMemory]:
        """Get a TaskMemory by its ID."""
        return self._task_memories.get(task_id)
    
    def _cleanup_if_needed(self) -> None:
        while len(self._task_memories) > self.max_tasks and self._task_order:
            oldest_task_id = self._task_order.pop(0)
            self._task_memories.pop(oldest_task_id, None)
