import time

class TaskMemory:
    def __init__(self, name: str, max_lines: int = 50):
        self.name = name
        self._lines = []
        self.max_lines = max_lines

    def set(self, value: str):
        # Add compact timestamp [HH:MM:SS] to save tokens
        timestamp = time.strftime("%H:%M:%S")
        timestamped_value = f"[{timestamp}] {str(value)}"
        self._lines.append(timestamped_value)
        
        if len(self._lines) > self.max_lines:
            excess = len(self._lines) - self.max_lines
            self._lines = self._lines[excess:]
            
            if not self._lines[0].startswith("[Memory truncated"):
                timestamp_trunc = time.strftime("%H:%M:%S")
                self._lines[0] = f"[{timestamp_trunc}] [Memory truncated - showing last {self.max_lines} entries]"

    def get(self) -> str:
        return "\n".join(f"{i+1}. {line}" for i, line in enumerate(self._lines)) if self._lines else ""