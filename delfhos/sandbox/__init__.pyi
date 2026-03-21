"""Type stubs for delfhos.sandbox — Mock implementations for testing."""

from typing import Any, Dict, List, Optional, Union

class MockDatabase:
    """
    In-memory SQLite database pre-populated with dummy enterprise data.
    Requires ZERO configuration. Perfect for testing and tutorials.
    """
    TOOL_NAME: str
    ALLOWED_ACTIONS: List[str]
    is_sandbox: bool

    def __init__(self, name: str = "db", allow: Optional[Union[str, List[str]]] = None, confirm: Union[bool, List[str], None] = True) -> None: ...

    @classmethod
    def inspect(cls, verbose: bool = False) -> dict:
        """Inspect available mock SQL actions without creating an instance."""
        ...

    def execute_mock_query(self, query: str) -> Union[List[Dict[str, Any]], int]: ...
    def get_mock_schema(self) -> str: ...


class MockEmail:
    """
    Mock Email connection that pretends to be Gmail but uses local dictionaries.
    Requires ZERO configuration. Perfect for testing and tutorials.
    """
    TOOL_NAME: str
    ALLOWED_ACTIONS: List[str]
    is_sandbox: bool

    def __init__(self, name: str = "gmail", allow: Optional[Union[str, List[str]]] = None, confirm: Union[bool, List[str], None] = True) -> None: ...

    @classmethod
    def inspect(cls, verbose: bool = False) -> dict:
        """Inspect available mock email actions without creating an instance."""
        ...

    def mock_search_emails(self, query: str = "", max_results: int = 10) -> List[Dict[str, Any]]: ...
    def mock_get_email(self, message_id: str) -> Optional[Dict[str, Any]]: ...
    def mock_send_email(self, to: str, subject: str, body: str) -> str: ...

__all__ = ["MockDatabase", "MockEmail"]
