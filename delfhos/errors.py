"""
Delfhos Error Management System.

Provides rich, clear, and actionable exceptions.
Each error includes:
1. A clear message describing the issue.
2. A hint/resolution explaining how the developer can fix it.
3. An error code for standardized debugging.
"""
from typing import Optional


class DelfhosConfigError(Exception):
    """Base class for all Delfhos exceptions."""
    code: str = "ERR_BASE"
    message_template: str = "{message}"
    resolution: str = "Review the latest Delfhos documentation."

    def __init__(self, message: Optional[str] = None, **kwargs):
        self._message = message
        self.kwargs = kwargs
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        if self._message:
            msg = self._message
        else:
            try:
                msg = self.message_template.format(**self.kwargs)
            except KeyError as exc:
                missing_key = exc.args[0]
                provided = ", ".join(sorted(self.kwargs.keys())) or "none"
                msg = (
                    f"Internal error formatting '{self.__class__.__name__}': missing template key "
                    f"'{missing_key}'. Provided keys: {provided}."
                )
            except Exception as exc:
                msg = f"Internal error formatting '{self.__class__.__name__}' failed: {exc}"
        
        return (
            f"\n\n"
            f"❌ [{self.code}] Delfhos Error\n"
            f"{'-' * 40}\n"
            f"Message: {msg}\n"
            f"{'-' * 40}\n"
            f"💡 Hint: {self.resolution}\n"
        )


class ModelConfigurationError(DelfhosConfigError):
    code = "ERR_MODEL_001"
    message_template = "The model '{model_name}' requires specific parameters."
    resolution = "Ensure you have the correct API key set in your environment variables for this provider."

class AgentConfirmationError(DelfhosConfigError):
    code = "ERR_AGENT_001"
    message_template = "Agent strict confirm policy '{confirm}' failed because injected tools are missing the 'kind' attribute."
    resolution = "Ensure all your tools declare `@tool(kind='read'|'write')` matching your Agent's strict confirm policy, or set Agent(confirm=False|True)."

class MemorySetupError(DelfhosConfigError):
    code = "ERR_MEM_001"
    message_template = "Persistent memory path '{path}' is invalid or inaccessible."
    resolution = "Check that the directory exists and you have write permissions, or use an in-memory database like ':memory:'."

class ToolExecutionError(DelfhosConfigError):
    """Raised when a tool fails internally and handle_error=False is used."""
    code = "ERR_TOOL_001"
    message_template = "Tool '{tool_name}' failed during execution: {detail}"
    resolution = "Review the arguments sent to the tool. If the error is expected, consider setting `@tool(handle_error=True)` so the LLM can see the error as a string message and recover."

class MCPConnectionError(DelfhosConfigError):
    code = "ERR_MCP_001"
    message_template = "MCP server '{server}' failed to start or connect over stdio."
    resolution = "Ensure the MCP command (e.g., 'npx -y @modelcontextprotocol/server-...') is installed and executable in your current environment."

class EnvironmentKeyError(DelfhosConfigError):
    code = "ERR_ENV_001"
    message_template = "Missing required environment variable: '{key}'"
    resolution = "Export the variable in your shell (e.g. `export {key}=value`) or add it to your .env file."

class ToolDefinitionError(DelfhosConfigError, TypeError):
    code = "ERR_TOOL_002"
    message_template = "Invalid Tool definition: {detail}"
    resolution = "Ensure you are using the `@tool` decorator correctly on a callable function, and not attempting to instantiate the internal Tool class directly."


class OptionalDependencyError(DelfhosConfigError):
    code = "ERR_REQ_001"
    message_template = "The '{package}' package is required for this feature. {detail}"
    resolution = "Install the required package by running: `pip install {package}`"


class ConnectionConfigurationError(DelfhosConfigError, ValueError):
    code = "ERR_CONN_001"
    message_template = "Invalid connection configuration for '{tool_name}': {detail}"
    resolution = "Review the connection parameters. Ensure you are providing the correct authentication variables (e.g. URL, credentials file, or host variables)."


class ConnectionFileNotFoundError(ConnectionConfigurationError, FileNotFoundError):
    code = "ERR_CONN_002"
    message_template = "Missing required credentials file for '{tool_name}': {detail}"
    resolution = "Verify the credentials file path and make sure the file exists with correct read permissions."


class LLMExecutionError(DelfhosConfigError):
    code = "ERR_LLM_001"
    message_template = "Language Model API failed: {detail}"
    resolution = "Ensure your API key is valid and you have internet connectivity, or check the provider's status page."
