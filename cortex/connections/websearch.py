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
    
    The WebSearch tool requires a specific LLM model to perform web searches.
    Web search is supported for Gemini and OpenAI/GPT models.
    Claude models do not support web search.
    
    Example (Gemini):
        search = WebSearch(llm="gemini-3.1-flash-lite-preview")
        agent = Agent(tools=[search, Gmail()], llm="gemini-3.1-pro")
        agent.run("What are the latest AI trends and email a summary to alice@co.com")
    
    Example (OpenAI):
        search = WebSearch(llm="gpt-4")
        agent = Agent(tools=[search, Gmail()], llm="gpt-4")
        agent.run("What are the latest AI trends and email a summary to alice@co.com")
    
    Example (class-level inspection):
        print(WebSearch.inspect())  # See available WebSearch actions without credentials
    
    Args (for instance):
        llm: Required. LLM model to use for web search (e.g., "gemini-3.1-flash-lite-preview", "gpt-4").
             Supported: Gemini and OpenAI/GPT models.
        api_key: Optional API key. If not provided, uses env var or falls back to free mode.
        allow: Restrict actions to specific ones (e.g., ["search"]; default: allow all).
        name: Custom label (default: "websearch").
        metadata: Extra context dict (useful for logging/tracking).
    """

    TOOL_NAME = "websearch"
    ALLOWED_ACTIONS = ["search"]

    def __init__(
        self,
        llm: str,
        api_key: Optional[str] = None,
        allow: Optional[Union[str, List[str]]] = None,
        name: str = "websearch",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        if not llm or not isinstance(llm, str):
            raise ValueError("WebSearch requires an 'llm' parameter with a valid model name (e.g., 'gemini-3.1-flash-lite-preview' or 'gpt-4')")
        
        credentials = {"api_key": api_key} if api_key else {}
        # Store the llm as part of metadata to pass it through to WebSearchLibrary
        if metadata is None:
            metadata = {}
        metadata["llm"] = llm
        
        super().__init__(
            credentials=credentials,
            allow=allow,
            name=name,
            auth_type=AuthType.API_KEY if api_key else AuthType.NONE,
            metadata=metadata,
        )
