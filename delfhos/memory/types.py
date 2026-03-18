from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Message:
    role: str
    content: str
    timestamp: datetime
    namespace: str
    is_summary: bool = False

@dataclass
class Fact:
    content: str
    saved_at: datetime
    namespace: str
