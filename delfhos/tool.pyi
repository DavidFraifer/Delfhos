"""Type stubs for delfhos.tool — Custom tool abstraction."""

from typing import Any, Callable, Dict, List, Optional, Union

class ToolException(Exception):
    """Raised inside a tool when the error should be fed back to the LLM
    for self-correction rather than crashing the task.

    Usage inside a custom tool::

        raise ToolException("No results found for that query — try broader keywords.")

    The orchestrator's retry loop will receive this message as context.
    """
    ...


class DelfhosToolWarning(UserWarning):
    """Emitted at tool registration when the schema may be incomplete."""
    ...


class Tool:
    """
    Wraps a callable into an agent-executable tool with schema, error handling, and confirmation.

    **Don't construct directly** — use the @tool decorator instead::

        @tool
        def my_function(x: str, y: int = 10) -> str:
            '''Do something with x and optional y.'''
            return f"{x} * {y}"

        agent = Agent(tools=[my_function], llm="gemini-3.1-flash-lite-preview")

    The decorator automatically captures the function's:
      • Name (or override with name="custom_name")
      • Docstring (or override with description="...")
      • Parameter types and defaults
      • Return type
    """
    tool_name: str
    description: str
    parameters: Optional[Dict[str, Any]]
    return_type: Optional[str]
    handle_error: Union[bool, str, Callable, None]
    confirm: bool

    def api_doc(self) -> str:
        """Return a precise API doc string for LLM code-generation."""
        ...

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        """Async entry point — always safe to await."""
        ...

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Sync entry point for sync-only contexts (e.g. testing, CLI scripts)."""
        ...

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


def tool(
    _func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    handle_error: Union[bool, str, Callable, None] = True,
    return_errors: Optional[bool] = None,
    confirm: bool = True,
) -> Union[Tool, Callable[[Callable], Tool]]:
    """Convert a function into an agent-executable tool with automatic schema extraction.

    The decorator captures your function's name, docstring, parameters, and return type
    automatically. Zero boilerplate.

    **Basic usage** (no args)::

        @tool
        def get_weather(location: str, units: str = "C") -> str:
            \"\"\"Fetch the current weather for a city.\"\"\"
            return weather_api.fetch(location=location, units=units)

        agent = Agent(tools=[get_weather], llm="gemini-3.1-flash-lite-preview")
        agent.run("What's the weather in Paris?")

    **Advanced usage** (with options)::

        @tool(
            name="fetch_weather",  # override auto-detected name
            handle_error="Could not reach the weather API. Please try again in a moment.",
            confirm=True  # always ask before running
        )
        async def get_weather(location: str) -> str:
            ...

    Args:
        name: Custom tool name (default: function name).
        description: Override auto-extracted docstring.
        handle_error: How to handle ToolException errors:
            - True (default): return exception message to agent.
            - str: return that custom string instead.
            - callable: fn(exception) -> str for custom error handling.
        confirm: If True, require approval before execution.

    Returns:
        A Tool instance that integrates seamlessly with Agent.
    """
    ...
