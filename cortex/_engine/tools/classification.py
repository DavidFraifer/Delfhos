"""
Tool classification based on heuristics
Used to automatically determine if a tool is a read or write operation,
which determines if it requires human confirmation.
"""

import re

WRITE_VERBS = {
    # Creates
    "create", "add", "insert", "post", "new", "make", "build", "generate",
    # Updates
    "update", "edit", "modify", "patch", "set", "change", "rename",
    # Deletes
    "delete", "remove", "destroy", "purge", "clear", "archive", "drop",
    # Sends
    "send", "publish", "push", "submit", "dispatch", "notify", "broadcast",
    # Writes
    "write", "save", "store", "upload", "import", "commit",
	# Others
	"execute", "run", "start", "stop", "restart", "deploy", "provision"
}

READ_VERBS = {
    "get", "fetch", "read", "list", "search", "find",
    "query", "retrieve", "download", "export", "check",
    "count", "describe", "show", "view", "status", "info", "inspect"
}

WRITE_DESCRIPTION_SIGNALS = [
    "create", "creates", "add", "adds", "insert", "inserts",
    "delete", "deletes", "remove", "removes",
    "update", "updates", "modify", "modifies",
    "send", "sends", "publish", "publishes",
    "permanently", "irreversible", "cannot be undone",
    "write", "writes", "save", "saves", "store", "stores",
]

DELETE_VERBS = {
    "delete", "remove", "destroy", "purge", "clear", "archive", "drop"
}

DELETE_DESCRIPTION_SIGNALS = [
    "delete", "deletes", "remove", "removes", "destroy", "destroys",
    "purge", "drop", "irreversible", "cannot be undone", "permanently",
]

READ_DESCRIPTION_SIGNALS = [
    "retrieve", "retrieves", "fetch", "fetches",
    "list", "lists", "search", "searches",
    "read", "reads", "get", "gets", "returns",
    "view", "views", "show", "shows",
]

def _tokenize(name: str) -> list[str]:
    """Split tool name by snake_case and camelCase into tokens"""
    # Replace separators with space
    name = re.sub(r'[-_]', ' ', name)
    # Split camelCase (e.g. createTask -> create Task)
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    return name.lower().split()

def _classify_from_name(name: str) -> str:
    tokens = _tokenize(name)
    if not tokens:
        return "unknown"
    
    first_verb = tokens[0]
    
    if first_verb in WRITE_VERBS:
        return "write"
    if first_verb in READ_VERBS:
        return "read"
    
    return "unknown"

def _classify_from_description(description: str) -> str:
    if not description:
        return "unknown"
        
    desc_lower = description.lower()
    
    write_hits = sum(1 for s in WRITE_DESCRIPTION_SIGNALS if re.search(r'\b' + re.escape(s) + r'\b', desc_lower))
    read_hits  = sum(1 for s in READ_DESCRIPTION_SIGNALS  if re.search(r'\b' + re.escape(s) + r'\b', desc_lower))
    
    if write_hits > read_hits:
        return "write"
    if read_hits > write_hits:
        return "read"
    return "unknown"

def classify_tool(name: str, description: str = "") -> str:
    """
    Classify if a tool is a read or write operation based on its name and description.
    
    Args:
        name: The name of the tool (e.g., 'create_task', 'get_invoice')
        description: The description of the tool
        
    Returns:
        "write" or "read"
    """
    # Step 1 — try name first, fast and reliable
    result = _classify_from_name(name)
    if result != "unknown":
        return result
    
    # Step 2 — fallback to description
    result = _classify_from_description(description)
    if result != "unknown":
        return result
    
    # Step 3 — genuinely unknown, default to safe side
    return "write"   # when uncertain, require confirmation


def is_delete_tool(name: str, description: str = "") -> bool:
    """Best-effort detection of destructive/delete-like tools."""
    tokens = _tokenize(name)
    if tokens and tokens[0] in DELETE_VERBS:
        return True

    if description:
        desc_lower = description.lower()
        for signal in DELETE_DESCRIPTION_SIGNALS:
            if re.search(r"\b" + re.escape(signal) + r"\b", desc_lower):
                return True

    return False
