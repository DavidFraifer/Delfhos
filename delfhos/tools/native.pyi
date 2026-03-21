"""Type stubs for delfhos.tools.native — lazy-loaded service tool aliases."""

from typing import Any, Dict, List, Optional, Union

class Gmail:
    """
    Gmail integration for reading emails and sending messages via agent.

    Example (service account):
        gmail = Gmail(service_account="sa.json", delegated_user="user@workspace.com")
        agent = Agent(tools=[gmail], llm="gemini-3.1-flash-lite-preview")
        agent.run("Reply to all unread emails with a summary of today's meetings")

    Example (personal OAuth):
        gmail = Gmail(oauth_credentials="client_secrets.json")
        agent.run("Forward important emails to alice@co.com")

    Authentication (choose one):
        service_account: Path to Google Service Account JSON (for Workspace/servers).
        oauth_credentials: Path to OAuth client_secrets.json (for personal accounts).

    Args:
        delegated_user: Email to impersonate (service account only; requires delegation).
        allow: Restrict actions, e.g., ["read"] prevents sending (default: allow all).
        name: Custom label (default: "gmail").
        metadata: Extra info dict for tracking/logging.
    """
    TOOL_NAME: str
    ALLOWED_ACTIONS: List[str]

    def __init__(
        self,
        *,
        service_account: Optional[str] = ...,
        oauth_credentials: Optional[str] = ...,
        delegated_user: Optional[str] = ...,
        allow: Optional[Union[str, List[str]]] = ...,
        confirm: Union[bool, List[str], None] = ...,
        name: str = ...,
        metadata: Optional[Dict[str, Any]] = ...,
    ) -> None: ...

        Args:
            verbose: If True, returns detailed descriptions of each action.

        Returns:
            dict with tool information and available actions.

        Example::

            print(Gmail.inspect())  # See available Gmail actions
            print(Gmail.inspect(verbose=True))  # See detailed descriptions
        """
        ...

    def inspect_instance(self, verbose: bool = False) -> dict:
        """Return instance-specific connection information.

        Args:
            verbose: If True, returns detailed descriptions.
        """
        ...

    def effective_allowed_actions(self) -> Union[List[str], str]:
        """Return the effective action policy: "all" or list of allowed actions."""
        ...


GmailTool = Gmail


class SQL:
    """
    SQL database integration for querying and updating databases.

    Example (connection string):
        db = SQL(url="postgresql://user:pw@localhost/mydb")
        agent = Agent(tools=[db, Sheets()], llm="gemini-3.1-flash-lite-preview")
        agent.run("Query revenue by region and update the Reporting sheet")

    Example (parameters):
        db = SQL(host="localhost", database="analytics", user="reader", password="...")

    Authentication (use either url OR host+params):
        url: Full connection string, e.g. "postgresql://user:pass@host/db".
        host+port+database+user+password: Individual connection parameters.

    Args:
        url: Database connection string (takes priority if both url and host are provided).
        host: Database hostname/IP.
        port: Database port (default: 5432 for PostgreSQL, 3306 for MySQL).
        database: Database name.
        user: Database username.
        password: Database password.
        db_type: "postgresql", "mysql", or "mariadb" (default: "postgresql").
        allow: Restrict actions, e.g., ["query"] blocks writes (default: allow all).
               Supported: "schema" (introspection), "query" (SELECT), "write" (INSERT/UPDATE/DELETE).
        name: Custom label (default: "sql").
        metadata: Extra info dict for tracking/logging.
    """
    TOOL_NAME: str
    ALLOWED_ACTIONS: List[str]

    def __init__(
        self,
        *,
        url: Optional[str] = ...,
        host: Optional[str] = ...,
        port: Optional[int] = ...,
        database: Optional[str] = ...,
        user: Optional[str] = ...,
        password: Optional[str] = ...,
        db_type: str = ...,
        allow: Optional[Union[str, List[str]]] = ...,
        confirm: Union[bool, List[str], None] = ...,
        name: str = ...,
        metadata: Optional[Dict[str, Any]] = ...,
    ) -> None: ...

    @classmethod
    def inspect(cls, verbose: bool = False) -> dict:
        """Inspect available actions for SQL without instantiation."""
        ...

    def inspect_instance(self, verbose: bool = False) -> dict:
        """Return instance-specific connection information."""
        ...

    def effective_allowed_actions(self) -> Union[List[str], str]:
        """Return the effective action policy: "all" or list of allowed actions."""
        ...


SQLTool = SQL


class Sheets:
    """
    Google Sheets integration for reading and writing spreadsheets.

    Example:
        sheets = Sheets(oauth_credentials="client_secrets.json")
        agent = Agent(tools=[sheets, SQL(...)], llm="gemini-3.1-flash-lite-preview")
        agent.run("Pull yesterday's sales from the DB and update the Q3 Summary sheet")

    Authentication (choose one):
        service_account: Google Service Account JSON (for servers).
        oauth_credentials: OAuth client_secrets.json (for personal accounts).

    Args:
        delegated_user: Email to impersonate (service account + delegation only).
        allow: Restrict actions, e.g., ["read"] blocks writing (default: allow all).
                Supported: "read", "write", "create", "format", "chart", "batch".
        name: Custom label (default: "sheets").
        metadata: Extra info dict for tracking/logging.
    """
    TOOL_NAME: str
    ALLOWED_ACTIONS: List[str]

    def __init__(
        self,
        *,
        service_account: Optional[str] = ...,
        oauth_credentials: Optional[str] = ...,
        delegated_user: Optional[str] = ...,
        allow: Optional[Union[str, List[str]]] = ...,
        confirm: Union[bool, List[str], None] = ...,
        name: str = ...,
        metadata: Optional[Dict[str, Any]] = ...,
    ) -> None: ...

    @classmethod
    def inspect(cls, verbose: bool = False) -> dict:
        """Inspect available actions for Sheets without instantiation."""
        ...

    def inspect_instance(self, verbose: bool = False) -> dict:
        """Return instance-specific connection information."""
        ...

    def effective_allowed_actions(self) -> Union[List[str], str]:
        """Return the effective action policy."""
        ...


SheetsTool = Sheets


class Drive:
    """
    Google Drive integration for managing files and folders.

    Example:
        drive = Drive(oauth_credentials="client_secrets.json")
        agent = Agent(tools=[drive, Gmail()], llm="gemini-3.1-flash-lite-preview")
        agent.run("Archive Q3 reports into Completed/Q3 folder and send summary to finance@co.com")

    Authentication (choose one):
        service_account: Google Service Account JSON (for servers).
        oauth_credentials: OAuth client_secrets.json (for personal accounts).

    Args:
        delegated_user: Email to impersonate (service account + delegation only).
        allow: Restrict actions, e.g., ["search", "get"] blocks create/delete (default: allow all).
        name: Custom label (default: "drive").
        metadata: Extra info dict for tracking/logging.
    """
    TOOL_NAME: str
    ALLOWED_ACTIONS: List[str]

    def __init__(
        self,
        *,
        service_account: Optional[str] = ...,
        oauth_credentials: Optional[str] = ...,
        delegated_user: Optional[str] = ...,
        allow: Optional[Union[str, List[str]]] = ...,
        confirm: Union[bool, List[str], None] = ...,
        name: str = ...,
        metadata: Optional[Dict[str, Any]] = ...,
    ) -> None: ...

    @classmethod
    def inspect(cls, verbose: bool = False) -> dict:
        """Inspect available actions for Drive without instantiation."""
        ...

    def inspect_instance(self, verbose: bool = False) -> dict:
        """Return instance-specific connection information."""
        ...

    def effective_allowed_actions(self) -> Union[List[str], str]:
        """Return the effective action policy."""
        ...


DriveTool = Drive


class Calendar:
    """
    Google Calendar integration for reading and managing events.

    Example:
        calendar = Calendar(oauth_credentials="client_secrets.json")
        agent = Agent(tools=[calendar, Gmail()], llm="gemini-3.1-flash-lite-preview")
        agent.run("Find a 1-hour slot next Tuesday and schedule meeting with alice@co.com")

    Authentication (choose one):
        service_account: Google Service Account JSON (for servers).
        oauth_credentials: OAuth client_secrets.json (for personal accounts).

    Args:
        delegated_user: Email to impersonate (service account + delegation only).
        allow: Restrict actions, e.g., ["list"] blocks creating events (default: allow all).
        name: Custom label (default: "calendar").
        metadata: Extra info dict for tracking/logging.
    """
    TOOL_NAME: str
    ALLOWED_ACTIONS: List[str]

    def __init__(
        self,
        *,
        service_account: Optional[str] = ...,
        oauth_credentials: Optional[str] = ...,
        delegated_user: Optional[str] = ...,
        allow: Optional[Union[str, List[str]]] = ...,
        confirm: Union[bool, List[str], None] = ...,
        name: str = ...,
        metadata: Optional[Dict[str, Any]] = ...,
    ) -> None: ...

    @classmethod
    def inspect(cls, verbose: bool = False) -> dict:
        """Inspect available actions for Calendar without instantiation."""
        ...

    def inspect_instance(self, verbose: bool = False) -> dict:
        """Return instance-specific connection information."""
        ...

    def effective_allowed_actions(self) -> Union[List[str], str]:
        """Return the effective action policy."""
        ...


CalendarTool = Calendar


class Docs:
    """
    Google Docs integration for reading and writing documents.

    Example:
        docs = Docs(oauth_credentials="client_secrets.json")
        agent = Agent(tools=[docs, WebSearch()], llm="gemini-3.1-flash-lite-preview")
        agent.run("Research latest Python best practices and write a guide to my Tech Doc")

    Authentication (choose one):
        service_account: Google Service Account JSON (for servers).
        oauth_credentials: OAuth client_secrets.json (for personal accounts).

    Args:
        delegated_user: Email to impersonate (service account + delegation only).
        allow: Restrict actions, e.g., ["read"] blocks editing (default: allow all).
        name: Custom label (default: "docs").
        metadata: Extra info dict for tracking/logging.
    """
    TOOL_NAME: str
    ALLOWED_ACTIONS: List[str]

    def __init__(
        self,
        *,
        service_account: Optional[str] = ...,
        oauth_credentials: Optional[str] = ...,
        delegated_user: Optional[str] = ...,
        allow: Optional[Union[str, List[str]]] = ...,
        confirm: Union[bool, List[str], None] = ...,
        name: str = ...,
        metadata: Optional[Dict[str, Any]] = ...,
    ) -> None: ...

    @classmethod
    def inspect(cls, verbose: bool = False) -> dict:
        """Inspect available actions for Docs without instantiation."""
        ...

    def inspect_instance(self, verbose: bool = False) -> dict:
        """Return instance-specific connection information."""
        ...

    def effective_allowed_actions(self) -> Union[List[str], str]:
        """Return the effective action policy."""
        ...


DocsTool = Docs


class WebSearch:
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

    Args:
        llm: Required. LLM model to use for web search (e.g., "gemini-3.1-flash-lite-preview", "gpt-4").
             Supported: Gemini and OpenAI/GPT models.
        api_key: Optional API key. If not provided, uses env var or falls back to free mode.
        allow: Restrict actions to specific ones (e.g., ["search"]; default: allow all).
        name: Custom label (default: "websearch").
        metadata: Extra context dict (useful for logging/tracking).
    """
    TOOL_NAME: str
    ALLOWED_ACTIONS: List[str]

    def __init__(
        self,
        llm: str,
        api_key: Optional[str] = ...,
        allow: Optional[Union[str, List[str]]] = ...,
        confirm: Union[bool, List[str], None] = ...,
        name: str = ...,
        metadata: Optional[Dict[str, Any]] = ...,
    ) -> None: ...

    @classmethod
    def inspect(cls, verbose: bool = False) -> dict:
        """Inspect available actions for WebSearch without instantiation."""
        ...

    def inspect_instance(self, verbose: bool = False) -> dict:
        """Return instance-specific connection information."""
        ...

    def effective_allowed_actions(self) -> Union[List[str], str]:
        """Return the effective action policy."""
        ...


WebSearchTool = WebSearch
