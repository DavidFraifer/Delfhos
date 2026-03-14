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
    Web search connection (no credentials required by default).

    Args:
        api_key:  Optional API key for the search provider.
        actions:  ["search"] — omit to allow all.
        name:     Label (default: "websearch").
        metadata: Extra info dict.
    """

    TOOL_NAME = "websearch"

    def __init__(
        self,
        api_key: Optional[str] = None,
        actions: Optional[List[str]] = None,
        name: str = "websearch",
        metadata: Optional[Dict[str, Any]] = None,
        confirm: Union[str, bool] = False,
    ):
        credentials = {"api_key": api_key} if api_key else {}
        super().__init__(
            credentials=credentials,
            actions=actions,
            name=name,
            auth_type=AuthType.API_KEY if api_key else AuthType.NONE,
            metadata=metadata,
            confirm=confirm,
        )
