"""
Connection System for CORTEX Agent
Manages authenticated connections to external services with fine-grained permissions
"""

import uuid
import time
from typing import List, Optional, Dict, Any, Set, Union
from datetime import datetime
from enum import Enum


class AuthType(Enum):
    """Supported authentication types"""
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    BASIC_AUTH = "basic_auth"
    SERVICE_ACCOUNT = "service_account"
    NONE = "none"  # For tools that don't require auth


class ConnectionStatus(Enum):
    """Connection status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    EXPIRED = "expired"
    ERROR = "error"


class Connection:
    """
    Represents an authenticated connection to an external service
    
    A Connection encapsulates:
    - Authentication credentials
    - Allowed actions/permissions
    - Service-specific configuration
    - Agent linking and access control
    
    Example:
        # Create a Gmail connection with limited permissions
        gmail_conn = Connection(
            tool_name="gmail",
            connection_name="work_gmail",
            auth_type=AuthType.OAUTH2,
            credentials={
                "access_token": "...",
                "refresh_token": "...",
                "email": "user@company.com"
            },
            actions_allowed=["read", "send"]  # Can't delete
        )
        
        # Use in agent
        agent = Agent(
            tools=[gmail_conn, drive_conn],
            ...
        )
    """
    
    def __init__(
        self,
        tool_name: str,
        connection_name: str,
        auth_type: AuthType,
        credentials: Dict[str, Any],
        actions_allowed: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        connection_id: Optional[str] = None,
        confirm: Union[bool, List[str], str] = False
    ):
        """
        Initialize a Connection
        
        Args:
            tool_name: Name of the tool/service (e.g., "gmail", "drive", "sheets")
            connection_name: User-defined name for this connection (e.g., "work_email", "finance_drive")
            auth_type: Authentication type (OAuth2, API Key, etc.)
            credentials: Authentication credentials
            actions_allowed: List of allowed actions (e.g., ["read", "send"]). None = all allowed
            metadata: Additional connection metadata (service URL, region, etc.)
            connection_id: Optional custom ID, auto-generated if not provided
            confirm: Mode for user confirmation ('write', 'all', 'delete', entirely boolean)
        """
        # Core identifiers - use full UUID for consistency with database
        self.connection_id = connection_id or str(uuid.uuid4())
        self.tool_name = tool_name.lower()
        self.connection_name = connection_name
        
        # Authentication
        self.auth_type = auth_type
        self._credentials = credentials
        
        # Permissions
        self.actions_allowed = set(actions_allowed) if actions_allowed else None  # None = all allowed
        self.confirm = confirm
        
        # Metadata
        self.metadata = metadata or {}
        self.created_at = datetime.now()
        self.status = ConnectionStatus.ACTIVE
        
        # Agent linking
        self.linked_agents: Set[str] = set()
        
        # Usage tracking
        self.last_used_at: Optional[datetime] = None
        self.usage_count = 0
    
    def link_to_agent(self, agent_id: str):
        """Link this connection to an agent"""
        self.linked_agents.add(agent_id)
    
    def unlink_from_agent(self, agent_id: str):
        """Unlink this connection from an agent"""
        self.linked_agents.discard(agent_id)
    
    def is_action_allowed(self, action: str) -> bool:
        """Check if an action is allowed for this connection"""
        if self.actions_allowed is None:
            return True  # All actions allowed
        return action.lower() in {a.lower() for a in self.actions_allowed}
    
    def get_credentials(self) -> Dict[str, Any]:
        """
        Get credentials.
        
        Returns:
            Dictionary of credentials
        """
        return self._credentials.copy()
    
    def update_credentials(self, credentials: Dict[str, Any]):
        """Update connection credentials"""
        self._credentials = credentials
    
    def mark_used(self):
        """Mark connection as used (for tracking)"""
        self.last_used_at = datetime.now()
        self.usage_count += 1
    
    def is_active(self) -> bool:
        """Check if connection is active"""
        return self.status == ConnectionStatus.ACTIVE
    
    def deactivate(self):
        """Deactivate this connection"""
        self.status = ConnectionStatus.INACTIVE
    
    def activate(self):
        """Activate this connection"""
        self.status = ConnectionStatus.ACTIVE
    
    def get_info(self) -> Dict[str, Any]:
        """Get connection information (safe for display - no credentials)"""
        return {
            "connection_id": self.connection_id,
            "tool_name": self.tool_name,
            "connection_name": self.connection_name,
            "auth_type": self.auth_type.value,
            "status": self.status.value,
            "actions_allowed": list(self.actions_allowed) if self.actions_allowed else "all",
            "linked_agents": list(self.linked_agents),
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "usage_count": self.usage_count,
            "metadata": self.metadata
        }
    
    def __str__(self) -> str:
        return f"Connection(id='{self.connection_id}', tool='{self.tool_name}', name='{self.connection_name}')"
    
    def __repr__(self) -> str:
        return self.__str__()


class ConnectionManager:
    """
    Manages all connections across the system
    
    Features:
    - Connection registry
    - Permission validation
    - Agent-connection linking
    - Connection lifecycle management
    """
    
    def __init__(self):
        self.connections: Dict[str, Connection] = {}
    
    def add_connection(self, connection: Connection) -> str:
        """
        Add a connection to the manager
        
        Args:
            connection: Connection instance
            
        Returns:
            connection_id
        """
        self.connections[connection.connection_id] = connection
        return connection.connection_id
    
    def remove_connection(self, connection_id: str) -> bool:
        """Remove a connection"""
        if connection_id in self.connections:
            del self.connections[connection_id]
            return True
        return False
    
    def get_connection(self, connection_id: str) -> Optional[Connection]:
        """Get a connection by ID"""
        return self.connections.get(connection_id)
    
    def get_connections_by_tool(self, tool_name: str) -> List[Connection]:
        """Get all connections for a specific tool"""
        return [
            conn for conn in self.connections.values()
            if conn.tool_name == tool_name.lower()
        ]
    
    def get_connections_by_agent(self, agent_id: str) -> List[Connection]:
        """Get all connections linked to an agent"""
        return [
            conn for conn in self.connections.values()
            if agent_id in conn.linked_agents
        ]
    
    def validate_action(self, connection_id: str, action: str) -> bool:
        """Validate if an action is allowed for a connection"""
        connection = self.get_connection(connection_id)
        if not connection:
            return False
        return connection.is_active() and connection.is_action_allowed(action)
    
    def get_all_connections(self) -> List[Connection]:
        """Get all connections"""
        return list(self.connections.values())
    
    def get_connections_info(self) -> List[Dict[str, Any]]:
        """Get info for all connections (safe for display)"""
        return [conn.get_info() for conn in self.connections.values()]


# Global connection manager instance
_global_connection_manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager instance"""
    return _global_connection_manager
