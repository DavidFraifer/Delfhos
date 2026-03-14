"""
cortex._engine — Internal execution engine (private).

This package contains the core AI orchestration logic.
Users should not import from here directly — use `cortex` instead.

    from cortex import Cortex                      ✅
    from cortex._engine.agent import Agent         ❌ (internal)
"""

from .agent import Agent
from .connection import Connection, ConnectionManager, AuthType, ConnectionStatus, get_connection_manager

__all__ = ["Agent", "Connection", "ConnectionManager", "AuthType", "ConnectionStatus", "get_connection_manager"]
