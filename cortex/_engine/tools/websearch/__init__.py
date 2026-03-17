import time
from delfhos.errors import ToolDefinitionError
from ...internal.llm import llm_completion_async
from ...utils.console import console
from ...utils import report_error

# Always use Gemini for web search, defaulting to lite for maximum speed
WEBSEARCH_LLM = "gemini-3.1-flash-lite-preview"


async def _llm_web_search(query: str, task_id: str, model: str, agent_id: str = None) -> tuple[str, dict]:
    console.tool("Web Search", "LLM-integrated web search", task_id=task_id, agent_id=agent_id)

    # Simplified system message for faster and more direct responses
    system_message = """You are a fast and precise research assistant. When searching the web, provide concise, factual information including:
- Specific names, numbers, dates, and concrete facts
- Direct answers to the query
IMPORTANT: Always respond in the SAME language as the user's query. If the query is in Spanish, respond entirely in Spanish."""

    # Send query as-is to preserve the user's language
    enhanced_query = query

    try:
        summary, token_info = await llm_completion_async(
            model=model,
            prompt=enhanced_query,
            system_message=system_message,
            temperature=0.1,
            max_tokens=2000,  # Reverted back to 2000 for longer responses
            use_web_search=True,
        )
        return summary.strip(), token_info
    except Exception as e:
        report_error("WEB-005", context={"query": query, "task_id": task_id, "error": str(e)})
        return "Web search failed. Please try again later.", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


async def web_search(query: str, task_id=1, _fast_search=True, model: str = None, agent_id: str = None, validation_mode: bool = False):
    """
    Perform web search using LLM-integrated search.
    
    Args:
        query: The search query (must be provided directly, no extraction)
        task_id: Task identifier for logging
        fast_search: Unused (kept for compatibility)
        light_llm: Unused (always uses Gemini)
        agent_id: Agent identifier for logging
        validation_mode: Unused (kept for compatibility)
    
    Returns:
        Tuple of (search_results_summary, token_info_dict)
    """
    start_time = time.perf_counter()
    
    if not query or not query.strip():
        raise ToolDefinitionError(detail="Web search requires a query parameter")
    
    query = query.strip()
    console.info("Web Search", f"Searching for: '{query}'", task_id=task_id, agent_id=agent_id)
    
    console.tool("Web Search", "Initiating LLM web search", task_id=task_id, agent_id=agent_id)
    search_llm = model or WEBSEARCH_LLM
    summary, token_info = await _llm_web_search(query=query, task_id=task_id, model=search_llm, agent_id=agent_id)
    
    total_duration = time.perf_counter() - start_time
    console.info("Web Search", f"Total web_search execution time: {total_duration:.2f}s", task_id=task_id, agent_id=agent_id)

    input_tokens = token_info.get("input_tokens", 0)
    output_tokens = token_info.get("output_tokens", 0)
    total_tokens = token_info.get("total_tokens", input_tokens + output_tokens)
    image_count = token_info.get("image_count", 0)

    merged_tokens = {
        "tokens_used": total_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "image_count": image_count,
        "llm_calls": token_info.get("llm_calls", 1),
    }

    console.info(
        "Web Search",
        f"Search completed. Tokens: {merged_tokens['tokens_used']} | Calls: {merged_tokens['llm_calls']}",
        task_id=task_id,
        agent_id=agent_id,
    )

    return summary, merged_tokens

