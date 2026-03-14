"""
cortex.tool_docs — LLM API documentation for each tool.

Each file defines how the Cortex engine explains a tool to the LLM:
  - ACTIONS          : what the tool can do
  - ACTION_SUMMARIES : short descriptions used for task prefiltering
  - PYTHON_API       : Python code snippets injected into code-generation prompts
  - EXAMPLES         : concrete usage examples

HOW TO ADD A NEW TOOL
----------------------
1. Add your tool doc class here:  cortex/tool_docs/mytool.py
2. Add your tool connection here:  cortex/connections/mytool.py
3. Add the execution code here:    cortex/_engine/tools/mytool/
4. Register execution in:          cortex/_engine/tools/internal_tools.py

See: examples/custom_connection.py for a full walkthrough.
"""

from .gmail     import GmailDoc
from .sql       import SQLDoc
from .sheets    import SheetsDoc
from .drive     import DriveDoc
from .calendar  import CalendarDoc
from .gdocs     import DocsDoc
from .websearch import WebSearchDoc
from .llm       import LLMDoc
from .files     import FilesDoc

# Registry: tool_name → Doc class (used by the engine to build LLM prompts)
TOOL_DOCS = {
    "gmail":     GmailDoc,
    "sql":       SQLDoc,
    "sheets":    SheetsDoc,
    "drive":     DriveDoc,
    "calendar":  CalendarDoc,
    "docs":      DocsDoc,
    "websearch": WebSearchDoc,
    "llm":       LLMDoc,
    "files":     FilesDoc,
}

__all__ = [
    "GmailDoc", "SQLDoc", "SheetsDoc", "DriveDoc", "CalendarDoc",
    "DocsDoc", "WebSearchDoc", "LLMDoc", "FilesDoc",
    "TOOL_DOCS",
]
