"""
Custom Tool abstraction for the Delfhos SDK.

This module provides the base `Tool` class that developers can extend
to easily create and inject custom capabilities into their agents.
"""

from typing import Any, Callable, Dict, List, Optional, Union, get_type_hints
import asyncio
import inspect
import re
import warnings
from delfhos.errors import ToolDefinitionError

_original_get_event_loop = asyncio.get_event_loop


def _compat_get_event_loop():
    """Compatibility shim: recreate an event loop if external libs cleared it."""
    try:
        return _original_get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


asyncio.get_event_loop = _compat_get_event_loop

try:
    asyncio.get_event_loop()
except RuntimeError:
    # Keep compatibility with sync tests that still rely on get_event_loop().
    asyncio.set_event_loop(asyncio.new_event_loop())


# ---------------------------------------------------------------------------
# Exceptions & Warnings
# ---------------------------------------------------------------------------

class ToolException(Exception):
    """Raised inside a tool when the error should be fed back to the LLM
    for self-correction rather than crashing the task.

    Usage inside a custom tool::

        raise ToolException("No results found for that query — try broader keywords.")

    The orchestrator's retry loop will receive this message as context.
    """


class DelfhosToolWarning(UserWarning):
    """Emitted at tool registration when the schema may be incomplete."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TYPE_NAME_MAP = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
    "NoneType": "null",
}

def _normalize_tool_kind(kind: Optional[str]) -> Optional[str]:
    if kind is None:
        return None
    return str(kind).strip().lower()


def _is_typed_dict(annotation) -> bool:
    """Check if an annotation is a TypedDict subclass."""
    return (
        isinstance(annotation, type)
        and issubclass(annotation, dict)
        and hasattr(annotation, "__annotations__")
        and hasattr(annotation, "__required_keys__")
    )


def _describe_type(annotation, _depth: int = 0) -> str:
    """Recursively describe a type annotation, expanding TypedDict fields.

    Returns a concise string the LLM can use to know exact key names and types.
    Examples:
        str                      → "string"
        List[str]                → "array[string]"
        Dict[str, int]           → "object"
        TypedDict {id: str, ...} → "{id: string, amount: number}"
    """
    if _depth > 5:
        return "any"

    if annotation is inspect.Parameter.empty:
        return "any"

    # TypedDict — the key use case
    if _is_typed_dict(annotation):
        hints = get_type_hints(annotation)
        required = getattr(annotation, "__required_keys__", set())
        parts = []
        for fname, ftype in hints.items():
            inner = _describe_type(ftype, _depth + 1)
            opt = "" if fname in required else "?"
            parts.append(f"{fname}{opt}: {inner}")
        return "{" + ", ".join(parts) + "}"

    # Generic types (List[X], Dict[K,V], Optional[X], etc.)
    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", None)

    if origin is list or (origin is not None and getattr(origin, "__name__", "") == "List"):
        if args:
            return f"array[{_describe_type(args[0], _depth + 1)}]"
        return "array"

    if origin is dict or (origin is not None and getattr(origin, "__name__", "") == "Dict"):
        if args and len(args) == 2:
            val = _describe_type(args[1], _depth + 1)
            return f"object[string, {val}]"
        return "object"

    # Union / Optional
    if origin is Union:
        non_none = [a for a in (args or []) if a is not type(None)]
        if len(non_none) == 1:
            return _describe_type(non_none[0], _depth + 1) + "?"
        return " | ".join(_describe_type(a, _depth + 1) for a in non_none)

    # Plain types
    name = getattr(annotation, "__name__", str(annotation))
    return _TYPE_NAME_MAP.get(name, name)


def _friendly_type(annotation) -> str:
    """Convert a type annotation to a human-readable string."""
    return _describe_type(annotation)


# ---------------------------------------------------------------------------
# Docstring schema parsing
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^\s*(Args|Arguments|Parameters|Params|Returns?|Yields?):\s*$", re.IGNORECASE)
_FIELD_RE = re.compile(r"^\s{2,}(\w+)\s*(?::\s*(.+?))?(?:\s*[-—–]\s*(.+))?$")


def _parse_docstring_schema(docstring: str) -> Dict[str, Dict[str, str]]:
    """Parse Google-style docstring sections into structured schema.

    Returns dict of section → {field_name: {"type": ..., "desc": ...}}.
    Sections: "args", "returns".
    """
    if not docstring:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    current_section = None

    for line in docstring.splitlines():
        section_match = _SECTION_RE.match(line)
        if section_match:
            sec = section_match.group(1).lower()
            if sec.startswith("return") or sec.startswith("yield"):
                current_section = "returns"
            else:
                current_section = "args"
            result.setdefault(current_section, {})
            continue

        if current_section is None:
            continue

        field_match = _FIELD_RE.match(line)
        if field_match:
            fname = field_match.group(1)
            ftype = (field_match.group(2) or "").strip()
            fdesc = (field_match.group(3) or "").strip()
            entry: Dict[str, str] = {}
            if ftype:
                entry["type"] = ftype
            if fdesc:
                entry["desc"] = fdesc
            result[current_section][fname] = entry
        elif line.strip() == "":
            current_section = None  # blank line ends section

    return result


# ---------------------------------------------------------------------------
# Signature extraction
# ---------------------------------------------------------------------------

def _extract_signature(func: Callable) -> tuple:
    """Extract parameters and return type from a callable's signature.

    Priority for each parameter type:
      1. TypedDict / generic annotation → expanded automatically
      2. Docstring Args: block → used as fallback description
      3. Plain annotation → used as-is

    Returns:
        (parameters_dict, return_type_str)
        parameters_dict: {name: {"type": ..., "required": bool, "default": ..., "desc": ...}}
        return_type_str: human-readable return type or None
    """
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return None, None

    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    # Parse docstring for supplementary field info
    doc_schema = _parse_docstring_schema(func.__doc__ or "")
    doc_args = doc_schema.get("args", {})

    params: Dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        ann = hints.get(name, param.annotation)
        type_str = _describe_type(ann)

        # Merge docstring info for this param
        doc_entry = doc_args.get(name, {})
        if type_str == "object" and doc_entry.get("type"):
            # Docstring has more specific info than bare "object"
            type_str = doc_entry["type"]

        entry: Dict[str, Any] = {"type": type_str}
        if doc_entry.get("desc"):
            entry["desc"] = doc_entry["desc"]
        if param.default is not inspect.Parameter.empty:
            entry["required"] = False
            entry["default"] = param.default
        else:
            entry["required"] = True
        params[name] = entry

    # Return type
    ret_ann = hints.get("return", sig.return_annotation)
    ret_type = _describe_type(ret_ann) if ret_ann is not inspect.Parameter.empty else None

    # Enrich return type from docstring if type annotation is bare "object"
    doc_returns = doc_schema.get("returns", {})
    if ret_type == "object" and doc_returns:
        # Build inline schema from docstring Returns: fields
        field_parts = []
        for fname, finfo in doc_returns.items():
            ftype = finfo.get("type", "any")
            field_parts.append(f"{fname}: {ftype}")
        if field_parts:
            ret_type = "{" + ", ".join(field_parts) + "}"

    return params if params else None, ret_type


def build_api_signature(tool_name: str, description: str, parameters: Optional[Dict[str, Any]], return_type: Optional[str]) -> str:
    """Build a precise API doc string for the LLM code-generation prompt."""
    parts = []

    # Build signature: await get_weather(location: string) -> string
    if parameters:
        param_parts = []
        desc_parts = []
        for pname, pinfo in parameters.items():
            ptype = pinfo.get("type", "any")
            if pinfo.get("required", True):
                param_parts.append(f"{pname}: {ptype}")
            else:
                default = pinfo.get("default")
                default_repr = repr(default) if default is not None else "None"
                param_parts.append(f"{pname}: {ptype} = {default_repr}")
            if pinfo.get("desc"):
                desc_parts.append(f"#   {pname}: {pinfo['desc']}")
        sig_str = ", ".join(param_parts)
    else:
        sig_str = ""
        desc_parts = []

    ret_str = f" -> {return_type}" if return_type else ""
    parts.append(f"# await {tool_name}({sig_str}){ret_str}")
    parts.append(f"# {description}")
    if desc_parts:
        parts.extend(desc_parts)

    return "\n".join(parts)


class Tool:
    """
    Internal wrapper used by the @tool decorator.

    Public custom-tool authoring should use only @tool.
    """

    tool_name: str = ""
    description: str = ""
    parameters: Optional[Dict[str, Any]] = None
    return_type: Optional[str] = None
    handle_error: Union[bool, str, Callable, None] = True
    confirm: bool = False
    kind: Optional[str] = None

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        func: Optional[Callable] = None,
        handle_error: Union[bool, str, Callable, None] = True,
        confirm: bool = False,
        kind: Optional[str] = None,
        _from_decorator: bool = False,
        _internal_use: bool = False,
    ):
        """
        Initialize the tool.
        
            name: The internal identifier for the tool (e.g., 'weather_api').
            description: A short description of what the tool does.
            parameters: Optional parameter schema. Auto-extracted from func signature if not provided.
            func: Callable to execute.
            handle_error: Controls what happens when the tool raises ToolException.
                - True (default): the exception message is returned as the tool's result.
                - True: the exception message is returned as the tool's result.
                - str: that string is returned as the tool's result.
                - callable(ToolException) -> str: custom handler.
            confirm: If True, tool execution will always trigger a human approval request.
            kind: Arbitrary kind / category of this tool call (e.g. "read", "write", "send").
        """
        is_base_tool = type(self) is Tool
        if is_base_tool and not (_from_decorator or _internal_use):
            raise ToolDefinitionError(detail="Direct Tool(...) construction is disabled. Use @tool on a function.")

        if is_base_tool and func is None:
            raise ToolDefinitionError(detail="Tool wrapper requires a callable func.")

        if func is not None:
            self.tool_name = name or self.tool_name or func.__name__
            self.description = description or self.description or func.__doc__
        else:
            # Subclass compatibility: allow class-based tools with custom execute().
            self.tool_name = name or self.tool_name or type(self).__name__.lower()
            self.description = description or self.description or (self.__doc__ or "")

        self._func = func
        self.handle_error = handle_error
        self.confirm = bool(confirm)
        self.kind = _normalize_tool_kind(kind)

        # Auto-extract parameters and return type from the callable's signature
        auto_params, auto_return = None, None
        if func is not None:
            auto_params, auto_return = _extract_signature(func)

        self.parameters = parameters or self.parameters or auto_params
        self.return_type = self.return_type or auto_return

        # Dev-time warning for bare `dict` with no key information
        self._warn_bare_dicts()

        # Detect sync vs async once at init time — never re-check at call time
        self._is_async = asyncio.iscoroutinefunction(self._func) if self._func is not None else False

        if not self.tool_name:
            raise ToolDefinitionError(detail="A Tool must have a name.")
            
        if not self.description and not getattr(self, "ACTION_SUMMARIES", None):
            try:
                from cortex._engine.utils.console import console
                console.warning("TOOL VALIDATION", f"Tool '{self.tool_name}' has no docstring or description. Using default.")
            except ImportError:
                import sys
                print(f"WARNING: Tool '{self.tool_name}' has no docstring or description.", file=sys.stderr)
            
            self.description = f"Auto-explanatory tool: {self.tool_name}"

    def api_doc(self) -> str:
        """Return a precise API doc string for LLM code-generation."""
        return build_api_signature(self.tool_name, self.description, self.parameters, self.return_type)

    async def execute(self, *args, **kwargs) -> Any:
        """
        Async entry point — always safe to await regardless of whether the
        underlying function is sync or async.

        - Validates keyword arguments against the parameter schema (when available).
        - Async functions are awaited directly.
        - Sync functions are dispatched to a thread-pool executor so they
          never block the event loop.
        - ToolException is caught and routed through ``handle_error``.

        This method is used by @tool-created wrappers.
        """
        func = self._func
        if func is None:
            raise ToolDefinitionError(detail="Tool wrapper requires a callable func.")

        # Convert positional args → kwargs using schema parameter order so that
        # both get_weather("Madrid") and get_weather(location="Madrid") are handled
        # identically by validation and by the underlying function.
        if args and self.parameters:
            param_names = list(self.parameters.keys())
            leftover = []
            for i, val in enumerate(args):
                if i < len(param_names) and param_names[i] not in kwargs:
                    kwargs[param_names[i]] = val
                else:
                    leftover.append(val)
            args = tuple(leftover)

        # Lightweight input validation against the parameter schema
        if self.parameters:
            self._validate_inputs(kwargs)

        try:
            if self._is_async:
                return await func(*args, **kwargs)

            # Run sync function in a thread pool to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

        except ToolException as exc:
            return self._handle_tool_error(exc)

    def run(self, *args, **kwargs) -> Any:
        """
        Sync entry point for sync-only contexts (e.g. testing, CLI scripts).
        Calls the underlying function directly without any async machinery.
        """
        func = self._func
        if func is None:
            raise ToolDefinitionError(detail="Custom Tools must implement `execute()` or provide a `func`.")
        return func(*args, **kwargs)

    def __call__(self, *args, **kwargs) -> Any:
        # The orchestrator always awaits execute(), so forward there.
        return self.execute(*args, **kwargs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _warn_bare_dicts(self) -> None:
        """Warn if any param or return type is bare 'object' with no schema."""
        if self.parameters:
            for pname, pinfo in self.parameters.items():
                if pinfo.get("type") == "object":
                    warnings.warn(
                        f"Tool '{self.tool_name}', param '{pname}': annotated as dict with no key schema. "
                        f"Use a TypedDict or add an Args: docstring section so the LLM knows which keys to use.",
                        DelfhosToolWarning,
                        stacklevel=3,
                    )
        if self.return_type == "object":
            warnings.warn(
                f"Tool '{self.tool_name}': return type is dict with no key schema. "
                f"Use a TypedDict or add a Returns: docstring section.",
                DelfhosToolWarning,
                stacklevel=3,
            )

    _PYTHON_TYPES = {
        "string": str, "integer": int, "number": (int, float),
        "boolean": bool, "array": list, "object": dict,
    }

    def _validate_inputs(self, kwargs: dict) -> None:
        """Check required params are present and types match (best-effort)."""
        for pname, pinfo in self.parameters.items():
            if pinfo.get("required", True) and pname not in kwargs:
                raise ToolException(f"Missing required parameter '{pname}' for tool '{self.tool_name}'.")
            if pname in kwargs:
                type_str = pinfo.get("type", "")
                # TypedDict expanded type → expect a dict
                if type_str.startswith("{"):
                    expected: Any = dict
                # array[X] or bare array → expect a list
                elif type_str.startswith("array"):
                    expected = list
                else:
                    expected = self._PYTHON_TYPES.get(type_str)
                if expected and not isinstance(kwargs[pname], expected):
                    raise ToolException(
                        f"Parameter '{pname}' expected {type_str}, "
                        f"got {type(kwargs[pname]).__name__}."
                    )

    def _handle_tool_error(self, exc: ToolException) -> str:
        """Route a ToolException through the configured handler."""
        handler = self.handle_error
        if handler is None:
            raise exc
        if handler is True:
            return f"Tool error: {exc}"
        if isinstance(handler, str):
            return handler
        if callable(handler):
            return handler(exc)
        raise exc


# ---------------------------------------------------------------------------
# @tool decorator
# ---------------------------------------------------------------------------

def tool(
    _func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    handle_error: Union[bool, str, Callable, None] = True,
    return_errors: Optional[bool] = None,
    confirm: bool = False,
    kind: Optional[str] = None,
) -> Union[Tool, Callable[[Callable], Tool]]:
    """Decorator that turns a plain function into a Delfhos Tool.

    Can be used with or without arguments::

        @tool
        def get_weather(location: str) -> str:
            \"\"\"Get current weather for a city.\"\"\"
            return weather_api.fetch(location)

        @tool(name="weather", handle_error=True)
        async def get_weather(location: str) -> str:
            ...

        @tool(name="weather")
        async def get_weather(location: str) -> str:
            ...

    The function's name, docstring, type hints, and defaults are all
    captured automatically — zero boilerplate.
    """
    def _wrap(fn: Callable) -> Tool:
        effective_handle_error = handle_error if return_errors is None else bool(return_errors)
        return Tool(
            name=name,
            description=description,
            func=fn,
            handle_error=effective_handle_error,
            confirm=confirm,
            kind=kind,
            _from_decorator=True,
        )

    if _func is not None:
        # Called as @tool without arguments
        return _wrap(_func)
    # Called as @tool(...) with arguments
    return _wrap
