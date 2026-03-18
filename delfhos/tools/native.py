"""Lazy-loaded service tool aliases.

All connection classes are loaded on first access (not on import) to keep
``from delfhos import Gmail, Drive`` fast.
"""

_TOOL_MAP = {
    "Gmail":       ("cortex.connections.gmail",      "GmailConnection"),
    "SQL":         ("cortex.connections.sql",         "SQLConnection"),
    "Sheets":      ("cortex.connections.sheets",      "SheetsConnection"),
    "Drive":       ("cortex.connections.drive",        "DriveConnection"),
    "Calendar":    ("cortex.connections.calendar",     "CalendarConnection"),
    "Docs":        ("cortex.connections.docs",         "DocsConnection"),
    "WebSearch":   ("cortex.connections.websearch",    "WebSearchConnection"),
}

# Long-name aliases map to the same classes
_LONG_ALIASES = {
    "GmailTool":     "Gmail",
    "SQLTool":       "SQL",
    "SheetsTool":    "Sheets",
    "DriveTool":     "Drive",
    "CalendarTool":  "Calendar",
    "DocsTool":      "Docs",
    "WebSearchTool": "WebSearch",
}


def __getattr__(name):
    # Short name (Gmail, SQL, ...)
    if name in _TOOL_MAP:
        import importlib
        mod_path, cls_name = _TOOL_MAP[name]
        klass = getattr(importlib.import_module(mod_path), cls_name)
        globals()[name] = klass
        return klass
    # Long name (GmailTool → Gmail, ...)
    if name in _LONG_ALIASES:
        real = __getattr__(_LONG_ALIASES[name])
        globals()[name] = real
        return real
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(list(_TOOL_MAP.keys()) + list(_LONG_ALIASES.keys())))


__all__ = list(_TOOL_MAP.keys()) + list(_LONG_ALIASES.keys())

