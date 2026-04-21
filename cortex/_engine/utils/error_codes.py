"""
CORTEX Agent - Standardized Error and Warning Code System
Provides consistent error handling across the entire system.
"""

from enum import Enum
from typing import Optional, Dict, Any, Union
from delfhos.errors import ToolDefinitionError, format_error_block
from .console import console


DOCS_URL = "https://delfhos.com/docs"
ISSUES_URL = "https://github.com/DavidFraifer/Delfhos/issues"


def _internal_error_hint() -> str:
    return (
        f"This is an internal error. If it persists, check {DOCS_URL} "
        f"or open an issue: {ISSUES_URL}"
    )


def _docs_hint(prefix: str) -> str:
    return f"{prefix} See {DOCS_URL}"


def _issues_hint(prefix: str) -> str:
    return f"{prefix} Report it here: {ISSUES_URL}"


class ErrorSeverity(Enum):
    """Error severity levels"""
    INFO = "INFO"
    WARNING = "WARNING" 
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ErrorCategory(Enum):
    """Error categories for organization"""
    SYSTEM = "SYSTEM"
    AGENT = "AGENT"
    TOOL = "TOOL"
    DSL = "DSL"
    LLM = "LLM"
    MEMORY = "MEMORY"
    NETWORK = "NETWORK"
    CONFIG = "CONFIG"
    VALIDATION = "VALIDATION"


class CORTEXError:
    """Standardized error/warning representation"""
    
    def __init__(self, code: str, category: ErrorCategory, severity: ErrorSeverity, 
                 message: str, description: str = "", solution: str = ""):
        self.code = code
        self.category = category
        self.severity = severity
        self.message = message
        self.description = description
        self.solution = solution
    
    def __str__(self):
        return f"[{self.display_code}] {self.message}"

    @property
    def display_code(self) -> str:
        """Canonical display code format shared across SDK + engine output."""
        if self.code.startswith("ERR-"):
            return self.code
        return f"ERR-{self.code}"
    
    def format_full(self) -> str:
        """Get full formatted error message (verbose)"""
        lines = [f"[{self.display_code}] {self.message}"]
        if self.description:
            lines.append(f"Description: {self.description}")
        if self.solution:
            lines.append(f"Solution: {self.solution}")
        return "\n".join(lines)
    
    def format_message(self) -> str:
        """Format error for console output (matches SDK error format)"""
        return format_error_block(self.display_code, self.message, self.solution)


# ==================== ERROR CODE DEFINITIONS ====================

class ErrorCodes:
    """Centralized error code definitions"""
    
    # SYSTEM ERRORS (SYS-XXX)
    SYS_001 = CORTEXError(
        "SYS-001", ErrorCategory.SYSTEM, ErrorSeverity.CRITICAL,
        "System initialization failed",
        "Core system components failed to initialize properly",
        _internal_error_hint()
    )
    
    # AGENT ERRORS (AGT-XXX)
    AGT_001 = CORTEXError(
        "AGT-001", ErrorCategory.AGENT, ErrorSeverity.ERROR,
        "Agent not started",
        "Attempted to run task on agent that hasn't been started",
        "Call agent.start() before running tasks"
    )
    
    AGT_002 = CORTEXError(
        "AGT-002", ErrorCategory.AGENT, ErrorSeverity.ERROR,
        "Invalid LLM model",
        "Specified LLM model is not supported",
        "Use supported model families only: gemini-*, gpt-* and claude-*"
    )
    
    AGT_003 = CORTEXError(
        "AGT-003", ErrorCategory.AGENT, ErrorSeverity.ERROR,
        "No tools configured",
        "Agent requires at least one tool to function",
        "Add tools using the tools parameter: Agent(tools=['websearch'])"
    )
    
    AGT_004 = CORTEXError(
        "AGT-004", ErrorCategory.AGENT, ErrorSeverity.WARNING,
        "Task stop failed",
        "Unable to stop specific task",
        _issues_hint("Verify the task ID exists. If the issue persists,")
    )
    
    AGT_005 = CORTEXError(
        "AGT-005", ErrorCategory.AGENT, ErrorSeverity.WARNING,
        "Agent already stopped",
        "Attempted to stop agent that is not running",
        _issues_hint("Check agent state with agent.info() before stopping. If unexpected,")
    )

    AGT_006 = CORTEXError(
        "AGT-006", ErrorCategory.AGENT, ErrorSeverity.ERROR,
        "Budget exceeded",
        "Cumulative agent LLM cost has reached the configured budget_usd limit",
        "Raise budget_usd, reset the counter with agent.reset_budget(), or stop the agent"
    )

    # TOOL ERRORS (TOL-XXX)
    TOL_001 = CORTEXError(
        "TOL-001", ErrorCategory.TOOL, ErrorSeverity.ERROR,
        "Tool not found",
        "Requested tool is not available in the agent",
        "Check tool name spelling or add the tool to the agent"
    )
    
    TOL_002 = CORTEXError(
        "TOL-002", ErrorCategory.TOOL, ErrorSeverity.ERROR,
        "Tool execution failed",
        "Tool encountered an error during execution",
        "Check tool parameters and network connectivity"
    )
    
    TOL_003 = CORTEXError(
        "TOL-003", ErrorCategory.TOOL, ErrorSeverity.ERROR,
        "Invalid tool configuration",
        "Tool configuration is missing or invalid",
        "Verify tool setup and required parameters"
    )
    
    TOL_004 = CORTEXError(
        "TOL-004", ErrorCategory.TOOL, ErrorSeverity.WARNING,
        "Tool performance degraded",
        "Tool is responding slowly or intermittently",
        _docs_hint("Check your network connection and retry. If persistent,")
    )
    
    TOL_006 = CORTEXError(
        "TOL-006", ErrorCategory.TOOL, ErrorSeverity.ERROR,
        "Connection inactive",
        "Attempted to use an inactive connection",
        "Check connection status or reactivate the connection"
    )
    
    TOL_007 = CORTEXError(
        "TOL-007", ErrorCategory.TOOL, ErrorSeverity.ERROR,
        "Action not allowed",
        "Requested action is not permitted for this connection",
        "Check connection permissions or request access"
    )
    
    # DSL ERRORS (DSL-XXX)
    DSL_001 = CORTEXError(
        "DSL-001", ErrorCategory.DSL, ErrorSeverity.ERROR,
        "DSL syntax error",
        "Domain Specific Language syntax is invalid",
        _docs_hint("Check DSL structure and command syntax.")
    )
    
    # LLM ERRORS (LLM-XXX)
    LLM_001 = CORTEXError(
        "LLM-001", ErrorCategory.LLM, ErrorSeverity.ERROR,
        "Unsupported LLM model",
        "Specified LLM model is not supported",
        "Use supported model families only: gemini-*, gpt-* and claude-*"
    )
    
    # CONFIG ERRORS (CFG-XXX)
    CFG_001 = CORTEXError(
        "CFG-001", ErrorCategory.CONFIG, ErrorSeverity.WARNING,
        "Configuration initialization failed",
        "Failed to initialize configuration component",
        _internal_error_hint()
    )
    
    # VALIDATION ERRORS (VAL-XXX)
    VAL_001 = CORTEXError(
        "VAL-001", ErrorCategory.VALIDATION, ErrorSeverity.ERROR,
        "Input validation failed",
        "Input parameters failed validation checks",
        _docs_hint("Check input format and required parameters.")
    )
    
    VAL_002 = CORTEXError(
        "VAL-002", ErrorCategory.VALIDATION, ErrorSeverity.WARNING,
        "Validation timeout",
        "Validation process exceeded time limit",
        _issues_hint("This appears to be an internal validation timeout. If it happens frequently,")
    )
    
    # TOOL-SPECIFIC ERRORS
    
    # WEB SEARCH TOOL ERRORS (WEB-XXX)
    WEB_005 = CORTEXError(
        "WEB-005", ErrorCategory.LLM, ErrorSeverity.ERROR,
        "LLM web search failed",
        "The LLM-integrated web search encountered an error during execution",
        _docs_hint("Check LLM API connectivity and model availability. If the issue persists,")
    )
    
    WEB_006 = CORTEXError(
        "WEB-006", ErrorCategory.TOOL, ErrorSeverity.ERROR,
        "Model does not support web search",
        "The specified LLM model does not support web search capability",
        "Web search is supported for Gemini and OpenAI/GPT models. Initialize WebSearch with a supported model:\n"
        "  WebSearch(llm='gemini-3.1-flash-lite-preview')  # Gemini\n"
        "  WebSearch(llm='gpt-4')  # OpenAI"
    )


class ErrorHandler:
    """Centralized error handling and reporting"""
    
    @staticmethod
    def report_error(error: CORTEXError, task_id: Optional[str] = None, 
                    agent_id: Optional[str] = None, context: Optional[Dict[str, Any]] = None):
        """Report an error using the console system with beautiful formatting"""
        
        # Format error message in same style as SDK errors
        formatted = error.format_message()
        
        # Send to console based on severity
        if error.severity == ErrorSeverity.CRITICAL:
            console.error(f"CRITICAL {error.display_code}", formatted, task_id=task_id, agent_id=agent_id)
        elif error.severity == ErrorSeverity.ERROR:
            console.error(f"{error.display_code}", formatted, task_id=task_id, agent_id=agent_id)
        elif error.severity == ErrorSeverity.WARNING:
            console.warning(f"{error.display_code}", formatted, task_id=task_id, agent_id=agent_id)
        else:  # INFO
            console.info(f"{error.display_code}", formatted, task_id=task_id, agent_id=agent_id)
        
        # Log additional context if provided
        if context:
            context_str = ", ".join([f"{k}: {v}" for k, v in context.items()])
            console.debug("Error Context", context_str, task_id=task_id, agent_id=agent_id)
    
    @staticmethod
    def get_error_by_code(code: str) -> Optional[CORTEXError]:
        """Get error definition by code"""
        for attr_name in dir(ErrorCodes):
            if not attr_name.startswith('_'):
                error = getattr(ErrorCodes, attr_name)
                if isinstance(error, CORTEXError) and error.code == code:
                    return error
        return None
    
    @staticmethod
    def create_exception(error: CORTEXError, context: Optional[str] = None) -> Exception:
        """Create an appropriate exception from error code"""
        message = str(error)
        if context:
            message += f" | Context: {context}"
        
        if error.severity == ErrorSeverity.CRITICAL:
            return RuntimeError(message)
        elif error.category == ErrorCategory.VALIDATION:
            return ValueError(message)
        elif error.category == ErrorCategory.CONFIG:
            return FileNotFoundError(message)
        elif error.category == ErrorCategory.NETWORK:
            return ConnectionError(message)
        else:
            return Exception(message)


# ==================== CONVENIENCE FUNCTIONS ====================

def _format_context(context: Optional[Union[str, Dict[str, Any]]]) -> str:
    if context is None:
        return ""
    if isinstance(context, str):
        return context
    if isinstance(context, dict):
        if not context:
            return ""
        return ", ".join(f"{k}={context[k]!r}" for k in sorted(context.keys()))
    return str(context)


def report_error(code: str, task_id: Optional[str] = None, agent_id: Optional[str] = None,
                context: Optional[Dict[str, Any]] = None):
    """Quick error reporting by code"""
    error = ErrorHandler.get_error_by_code(code)
    if error:
        ErrorHandler.report_error(error, task_id, agent_id, context)
    else:
        unknown_code = code if str(code).startswith("ERR-") else f"ERR-{code}"
        formatted = format_error_block(unknown_code, "Error code not found", "Verify the code is registered in ErrorCodes.")
        console.error("Unknown Error", formatted, task_id=task_id, agent_id=agent_id)


def raise_error(code: str, context: Optional[Union[str, Dict[str, Any]]] = None):
    """Raise exception by error code"""
    error = ErrorHandler.get_error_by_code(code)
    if error:
        raise ErrorHandler.create_exception(error, _format_context(context))
    else:
        context_str = _format_context(context)
        display_code = code if str(code).startswith("ERR-") else f"ERR-{code}"
        detail = f"Unknown error code: {display_code}"
        if context_str:
            detail += f" | Context: {context_str}"
        raise ToolDefinitionError(detail=detail)


# ==================== ERROR CODE REGISTRY ====================
