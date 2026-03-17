from typing import Callable, Optional, Dict, Any, Union
from ..utils import report_error, raise_error
from ..connection import Connection
import asyncio


class ToolContainer:
    """Container for managing tools and connections in the simplified architecture"""
    
    def __init__(self, logger=None):
        self.tools: Dict[str, Callable] = {}
        self.connections: Dict[str, Connection] = {}  # connection_name -> Connection
        self.connection_to_tool: Dict[str, str] = {}  # connection_name -> tool_name
        self.logger = logger
    
    def set_logger(self, logger):
        """Set the logger for the container"""
        self.logger = logger
    
    def add_tool(self, name: str, func: Callable):
        """Add a tool to the container"""
        if not name or not callable(func):
            raise_error("TOL-002", context={"name": name, "func_type": type(func).__name__})
        self.tools[name.strip()] = func
    
    def add_connection(self, connection: Connection, agent_id: str = None):
        """
        Add a connection to the container
        
        Args:
            connection: Connection instance
            agent_id: Optional agent ID to link the connection to
        """
        self.connections[connection.connection_name] = connection
        self.connection_to_tool[connection.connection_name] = connection.tool_name
        
        if agent_id:
            connection.link_to_agent(agent_id)
    
    def get_connection(self, name: str) -> Optional[Connection]:
        """Get a connection by name"""
        return self.connections.get(name)
        
    async def execute_tool(self, name: str, context: str = "", task_id: str = None, light_llm: str = "gemini-2.5-flash", heavy_llm: str = "gemini-2.5-flash", agent_id: str = None, validation_mode: bool = False, action: str = None) -> str:
        """
        Execute a tool with the given context
        
        Args:
            name: Tool name OR connection name
            context: Context/parameters for the tool
            action: Optional action being performed (for permission checks)
            ... other parameters
        """
        # Check if name is a connection
        connection = None
        tool_name = name

        if name in self.connections:
            connection = self.connections[name]
            tool_name = connection.tool_name
        else:
            # Attempt to auto-resolve a connection for this tool name
            matching_connections = [
                conn for conn in self.connections.values()
                if conn.tool_name == name
            ]
            if matching_connections:
                connection = matching_connections[0]
                tool_name = connection.tool_name
                # If multiple connections, the first one linked to this agent remains default

        if connection:
            # Validate connection is active
            if not connection.is_active():
                raise_error("TOL-006", context={
                    "connection_name": connection.connection_name,
                    "status": connection.status.value
                })

            # Validate action permission if specified
            if action and not connection.is_action_allowed(action):
                effective_allowed = connection.effective_allowed_actions() if hasattr(connection, "effective_allowed_actions") else (list(connection.allow) if getattr(connection, "allow", None) else "all")
                raise_error("TOL-007", context={
                    "connection_name": connection.connection_name,
                    "action": action,
                    "allowed_actions": effective_allowed
                })

            # Mark connection as used
            connection.mark_used()
        
        # Get the tool function
        if tool_name not in self.tools:
            raise_error("TOL-003", context={
                "tool_name": tool_name,
                "available_tools": list(self.tools.keys()),
                "available_connections": list(self.connections.keys())
            })
        
        tool_func = self.tools[tool_name]
        
        try:
            # Prepare arguments based on function signature
            import inspect
            sig = inspect.signature(tool_func)
            params = sig.parameters
            has_kwargs = any(p.kind == p.VAR_KEYWORD for p in params.values())
            
            # Base arguments every internal tool should accept (either explicitly or via **kwargs)
            all_kwargs = {
                "task_id": task_id,
                "light_llm": light_llm,
                "heavy_llm": heavy_llm,
                "agent_id": agent_id,
                "validation_mode": validation_mode,
                "logger": self.logger
            }
            if connection is not None:
                all_kwargs["connection"] = connection
                # Try to get credentials if connection is present
                try:
                    credentials = connection.get_credentials()
                    if credentials:
                        all_kwargs["credentials"] = credentials
                except Exception:
                    pass

            # Filter kwargs to only what the function accepts (unless it has **kwargs)
            if has_kwargs:
                final_kwargs = all_kwargs
            else:
                final_kwargs = {k: v for k, v in all_kwargs.items() if k in params}

            if asyncio.iscoroutinefunction(tool_func):
                result = await tool_func(context, **final_kwargs)
            else:
                result = tool_func(context, **final_kwargs)
                
            return result if result is not None else "Tool completed successfully"
            
        except Exception as e:
            # If it's already one of our wrapped exceptions, re-raise it
            if hasattr(e, "error_code"):
                raise
            raise_error("TOL-004", context={"tool_name": tool_name, "connection_name": name if connection else None, "error": str(e), "error_type": type(e).__name__})
