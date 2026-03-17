from typing import Any

from ..utils.console import console
from .websearch import web_search
from .sheets.gsheets_tool import gsheets_tool as sheets_tool
from .drive.gdrive_tool import gdrive_tool as drive_tool
from .calendar.calendar_tool import calendar_tool
from .docs.docs_tool import gdocs_tool as docs_tool
from .sql.sql_tool import sql_tool
from ..connection import Connection

from .gmail.gmail_tool_unified import gmail_tool_unified


def _safe_log_tokens(logger: Any, task_id: str, agent_id: str, token_info: dict, model: str = None):
    """Best-effort token logging helper for non-critical tool paths."""
    if logger and token_info and (task_id or agent_id):
        try:
            logger.add_tokens(task_id or agent_id, token_info, model or "gemini-3.1-flash-lite-preview", "web_search")
        except Exception:
            pass


def _safe_console_error(title: str, message: str, task_id: str = None, agent_id: str = None):
    """Best-effort console error logging for tool-level failures."""
    try:
        console.error(title, message, task_id=task_id, agent_id=agent_id)
    except Exception:
        pass





async def gmail_tool(
    user_input: str = "",
    task_id: str = None,
    light_llm: str = None,
    heavy_llm: str = None,
    agent_id: str = None,
    validation_mode: bool = False,
    credentials: dict = None,
    connection: Connection = None,
    logger: Any = None,
    **kwargs: Any,
):
    """
    Gmail tool - Unified DSL wrapper.
    Routes to gmail_tool_unified which handles action/params directly.
    """
    # Delegate to unified implementation
    return await gmail_tool_unified(
        user_input=user_input,
        task_id=task_id,
        light_llm=light_llm,
        heavy_llm=heavy_llm,
        agent_id=agent_id,
        validation_mode=validation_mode,
        credentials=credentials,
        connection=connection,
        logger=logger,
    )

async def websearch_tool(user_input: str = "", task_id: str = None, light_llm: str = None, heavy_llm: str = None, agent_id: str = None, validation_mode: bool = False, logger: Any = None, **kwargs: Any):
    """
    Web search tool that performs intelligent web search with LLM-powered query extraction and summarization.

    Args:
        user_input: The user's search query or request
        task_id: Task identifier for logging
        light_llm: The light LLM model to use for processing

    Returns:
        Search results summary
    """
    resolved_args = None
    if isinstance(user_input, dict):
        resolved_args = user_input.get("resolved_args")
        parent_message = user_input.get("parent_message", "")
        message_payload = user_input.get("message", "")
        fallback_parent = parent_message if isinstance(parent_message, str) else str(parent_message or "")
        user_input = message_payload if isinstance(message_payload, str) else str(message_payload or "") or fallback_parent

    # Query must be provided in params (from DSL)
    search_query = None
    if isinstance(resolved_args, dict):
        params = resolved_args.get("params", {})
        if isinstance(params, dict) and "query" in params:
            search_query = params.get("query")

    if not search_query:
        raise ToolExecutionError(tool_name="websearch", detail="Web search requires 'query' parameter in params. Use: A websearch(action:\"SEARCH\",params:{query:\"your search query\"})")

    try:
        result, token_info = await web_search(
            query=search_query,
            task_id=task_id,
            model=light_llm,
            agent_id=agent_id,
            validation_mode=validation_mode
        )
        
        # Log tokens for web search
        _safe_log_tokens(logger, task_id, agent_id, token_info, model=light_llm)

        # Store result in task memory if available

        # Store token info in a way the orchestrator can access it
        # We'll attach it to the result string in a way that can be parsed
        setattr(websearch_tool, '_last_token_info', token_info)

        return result

    except Exception as e:
        error_msg = f"Web search failed: {str(e)}"
        _safe_console_error("WEBSEARCH", error_msg, task_id=task_id, agent_id=agent_id)

        return f"Sorry, web search encountered an error: {str(e)}"



# Internal tools registry
internal_tools = {
    "gmail": gmail_tool,
    "sheets": sheets_tool,
    "drive": drive_tool,
    "calendar": calendar_tool,
    "docs": docs_tool,
    "sql": sql_tool,
    "websearch": websearch_tool,
}
