"""
WebSearchConnection — Web search capability (no credentials required).

This connection requires no authentication—it uses the public search API
configured in the environment (e.g. SERPER_API_KEY or similar).

Example:
    from cortex.connections import WebSearchConnection

    web = WebSearchConnection()        # simplest case
    web = WebSearchConnection(name="company_search")
"""

from typing import List, Optional, Dict, Any, Union
from cortex._engine.connection import AuthType
from .base import BaseConnection


class WebSearchConnection(BaseConnection):
    """
    Web search integration for retrieving real-time info during agent execution.
    
    Example:
        search = WebSearch()
        agent = Agent(tools=[search, Gmail()], llm="gemini-3.1-flash-lite-preview")
        agent.run("What are the latest AI trends and email a summary to alice@co.com")
    
    Args:
        api_key: Optional API key. If not provided, uses env var or falls back to free mode.
        allow: Restrict actions to specific ones (e.g., ["search"]; default: allow all).
        name: Custom label (default: "websearch").
        metadata: Extra context dict (useful for logging/tracking).
    """

    TOOL_NAME = "websearch"
    ALLOWED_ACTIONS = ["search"]

    def __init__(
        self,
        api_key: Optional[str] = None,
        allow: Optional[Union[str, List[str]]] = None,
        name: str = "websearch",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        credentials = {"api_key": api_key} if api_key else {}
        super().__init__(
            credentials=credentials,
            allow=allow,
            name=name,
            auth_type=AuthType.API_KEY if api_key else AuthType.NONE,
            metadata=metadata,
        )
