"""Type stubs for delfhos.memory.types."""

from dataclasses import dataclass
from datetime import datetime

@dataclass
class Message:
    role: str
    content: str
    timestamp: datetime
    namespace: str
    is_summary: bool = ...

@dataclass
class Fact:
    content: str
    saved_at: datetime
    namespace: str
