"""
CORTEX Agent - Standardized Error and Warning Code System
Provides consistent error handling across the entire system.
"""

from enum import Enum
from typing import Optional, Dict, Any
from delfhos.errors import ToolDefinitionError
from .console import console


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
        return f"[{self.code}] {self.message}"
    
    def format_full(self) -> str:
        """Get full formatted error message"""
        lines = [f"[{self.code}] {self.message}"]
        if self.description:
            lines.append(f"Description: {self.description}")
        if self.solution:
            lines.append(f"Solution: {self.solution}")
        return "\n".join(lines)


# ==================== ERROR CODE DEFINITIONS ====================

class ErrorCodes:
    """Centralized error code definitions"""
    
    # SYSTEM ERRORS (SYS-XXX)
    SYS_001 = CORTEXError(
        "SYS-001", ErrorCategory.SYSTEM, ErrorSeverity.CRITICAL,
        "System initialization failed",
        "Core system components failed to initialize properly",
        "Check system requirements and dependencies"
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
        "Use supported models: gemini-2.5-flash, gemini-2.5-flash-lite, gemini-3-flash-preview, gemini-3.1-flash-lite-preview"
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
        "Check task ID or verify logging is enabled"
    )
    
    AGT_005 = CORTEXError(
        "AGT-005", ErrorCategory.AGENT, ErrorSeverity.WARNING,
        "Agent already stopped",
        "Attempted to stop agent that is not running",
        "Verify agent state before stopping"
    )
    
    # TOOL ERRORS (TL-XXX)
    TL_001 = CORTEXError(
        "TL-001", ErrorCategory.TOOL, ErrorSeverity.ERROR,
        "Tool not found",
        "Requested tool is not available in the agent",
        "Check tool name spelling or add the tool to the agent"
    )
    
    TL_002 = CORTEXError(
        "TL-002", ErrorCategory.TOOL, ErrorSeverity.ERROR,
        "Tool execution failed",
        "Tool encountered an error during execution",
        "Check tool parameters and network connectivity"
    )
    
    TL_003 = CORTEXError(
        "TL-003", ErrorCategory.TOOL, ErrorSeverity.ERROR,
        "Invalid tool configuration",
        "Tool configuration is missing or invalid",
        "Verify tool setup and required parameters"
    )
    
    TL_004 = CORTEXError(
        "TL-004", ErrorCategory.TOOL, ErrorSeverity.WARNING,
        "Tool performance degraded",
        "Tool is responding slowly or intermittently",
        "Check network connection or try again later"
    )
    
    TL_006 = CORTEXError(
        "TL-006", ErrorCategory.TOOL, ErrorSeverity.ERROR,
        "Connection inactive",
        "Attempted to use an inactive connection",
        "Check connection status or reactivate the connection"
    )
    
    TL_007 = CORTEXError(
        "TL-007", ErrorCategory.TOOL, ErrorSeverity.ERROR,
        "Action not allowed",
        "Requested action is not permitted for this connection",
        "Check connection permissions or request access"
    )
    
    # DSL ERRORS (DSL-XXX)
    DSL_001 = CORTEXError(
        "DSL-001", ErrorCategory.DSL, ErrorSeverity.ERROR,
        "DSL syntax error",
        "Domain Specific Language syntax is invalid",
        "Check DSL structure and command syntax"
    )
    
    # LLM ERRORS (LLM-XXX)
    LLM_001 = CORTEXError(
        "LLM-001", ErrorCategory.LLM, ErrorSeverity.ERROR,
        "Unsupported LLM model",
        "Specified LLM model is not supported",
        "Use supported models: gemini-2.5-flash, gemini-2.5-flash-lite, gemini-3-flash-preview, gemini-3.1-flash-lite-preview"
    )
    
    # CONFIG ERRORS (CFG-XXX)
    CFG_001 = CORTEXError(
        "CFG-001", ErrorCategory.CONFIG, ErrorSeverity.WARNING,
        "Configuration initialization failed",
        "Failed to initialize configuration component",
        "Check dependencies and configuration settings"
    )
    
    # VALIDATION ERRORS (VAL-XXX)
    VAL_001 = CORTEXError(
        "VAL-001", ErrorCategory.VALIDATION, ErrorSeverity.ERROR,
        "Input validation failed",
        "Input parameters failed validation checks",
        "Check input format and required parameters"
    )
    
    VAL_002 = CORTEXError(
        "VAL-002", ErrorCategory.VALIDATION, ErrorSeverity.WARNING,
        "Validation timeout",
        "Validation process exceeded time limit",
        "Simplify validation logic or increase timeout"
    )
    
    # TOOL-SPECIFIC ERRORS
    
    # WEBSEARCH TOOL ERRORS (WEBSEARCH-XXX)
    WEBSEARCH_005 = CORTEXError(
        "WEBSEARCH-005", ErrorCategory.LLM, ErrorSeverity.ERROR,
        "LLM web search failed",
        "The LLM-integrated web search encountered an error during execution",
        "Check LLM API connectivity and model availability, or try again later"
    )


class ErrorHandler:
    """Centralized error handling and reporting"""
    
    @staticmethod
    def report_error(error: CORTEXError, task_id: Optional[str] = None, 
                    agent_id: Optional[str] = None, context: Optional[Dict[str, Any]] = None):
        """Report an error using the console system"""
        
        if error.severity == ErrorSeverity.CRITICAL:
            console.error(f"CRITICAL {error.code}", error.message, task_id=task_id, agent_id=agent_id)
        elif error.severity == ErrorSeverity.ERROR:
            console.error(f"{error.code}", error.message, task_id=task_id, agent_id=agent_id)
        elif error.severity == ErrorSeverity.WARNING:
            console.warning(f"{error.code}", error.message, task_id=task_id, agent_id=agent_id)
        else:  # INFO
            console.info(f"{error.code}", error.message, task_id=task_id, agent_id=agent_id)
        
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

def report_error(code: str, task_id: Optional[str] = None, agent_id: Optional[str] = None, 
                context: Optional[Dict[str, Any]] = None):
    """Quick error reporting by code"""
    error = ErrorHandler.get_error_by_code(code)
    if error:
        ErrorHandler.report_error(error, task_id, agent_id, context)
    else:
        console.error("Unknown Error", f"Error code {code} not found", task_id=task_id, agent_id=agent_id)


def raise_error(code: str, context: Optional[str] = None):
    """Raise exception by error code"""
    error = ErrorHandler.get_error_by_code(code)
    if error:
        raise ErrorHandler.create_exception(error, context)
    else:
        raise ToolDefinitionError(detail=f"Unknown error code: {code}")


# ==================== ERROR CODE REGISTRY ====================
