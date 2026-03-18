import sys
import threading
import time
import re
from enum import Enum
from typing import Optional, Dict

from rich.console import Console, Group
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.columns import Columns


DEFAULT_ERROR_HINT = (
    "Review the error details and retry. If it persists, check docs or open an issue."
)


def normalize_error_code(raw_code: Optional[str]) -> str:
    """Normalize all displayed error codes to ERR-* format."""
    if not raw_code:
        return "ERR-SYSTEM-UNHANDLED"
    code = str(raw_code).strip().upper()
    if code.startswith("ERR-"):
        return code
    return f"ERR-{code}"


def _extract_code_and_message_from_text(text: str) -> tuple[Optional[str], str]:
    """Extract [CODE] Message from exception strings when present."""
    if not text:
        return None, "Unknown error"
    match = re.search(r"\[([A-Za-z0-9-]+)\]\s*(.*)", text)
    if match:
        return match.group(1), (match.group(2) or text).strip()
    return None, text.strip()


def extract_error_payload(exc: BaseException) -> tuple[str, str, str]:
    """Return (normalized_code, message, hint) for any exception type."""
    if hasattr(exc, "code") and hasattr(exc, "resolution"):
        raw_code = getattr(exc, "code", "SYSTEM-UNHANDLED")
        explicit_msg = getattr(exc, "_message", None)
        if explicit_msg:
            msg = str(explicit_msg).strip()
        elif hasattr(exc, "message_template"):
            try:
                kwargs = getattr(exc, "kwargs", {}) or {}
                msg = str(getattr(exc, "message_template")).format(**kwargs).strip()
            except Exception:
                msg = str(exc).strip() or type(exc).__name__
        else:
            msg = str(exc).strip() or type(exc).__name__
        hint = str(getattr(exc, "resolution", "") or DEFAULT_ERROR_HINT).strip()
        return normalize_error_code(raw_code), msg, hint

    exc_text = str(exc).strip() or type(exc).__name__
    parsed_code, parsed_msg = _extract_code_and_message_from_text(exc_text)
    code = normalize_error_code(parsed_code or type(exc).__name__)
    message = parsed_msg if parsed_msg else exc_text
    return code, message, DEFAULT_ERROR_HINT

class LogLevel(Enum):
    INFO = "INFO"
    SUCCESS = "SUCCESS" 
    WARNING = "WARNING"
    ERROR = "ERROR"
    DEBUG = "DEBUG"
    TASK = "TASK"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"

def convert_markdown_links_to_rich(text: str) -> str:
    """Convert markdown links [text](url) to Rich clickable links [link=url]text[/link]"""
    # Pattern: [text](url)
    pattern = r'\[([^\]]+)\]\(([^\)]+)\)'
    replacement = r'[link=\2]\1[/link]'
    return re.sub(pattern, replacement, text)

class ProfessionalConsole:
    def __init__(self, enable_colors: bool = True):
        import sys
        # Always output to the true stderr, bypassing python execution sandbox redirects
        self.console = Console(file=sys.__stderr__)
        self._lock = threading.Lock()
        self.start_time = time.time()  # Track relative time from session start
        
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=self.console,
            transient=True
        )
        self.active_tasks: Dict[str, int] = {}
        # We start the progress live viewer 
        self.progress.start()

    def _get_color(self, level: LogLevel) -> str:
        colors = {
            LogLevel.INFO: "cyan",
            LogLevel.SUCCESS: "green",
            LogLevel.WARNING: "yellow",
            LogLevel.ERROR: "red",
            LogLevel.DEBUG: "bright_black",
            LogLevel.TASK: "blue",
            LogLevel.SYSTEM: "magenta",
            LogLevel.TOOL: "bright_yellow"
        }
        return colors.get(level, "white")

    def print(self, level: LogLevel, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        with self._lock:
            color = self._get_color(level)
            elapsed_ms = int((time.time() - self.start_time) * 1000)
            # Format time: ms for <1000ms, seconds with 2 decimals for >=1000ms
            if elapsed_ms < 1000:
                time_str = f"+{elapsed_ms}ms"
            else:
                time_str = f"+{elapsed_ms / 1000:.2f}s"
            prefix = f"[dim]{time_str:>10}[/dim] \\[[bold {color}]{level.value:^7}[/bold {color}]]"
            
            text = f"{prefix} {message}"
            if details:
                text += f" [dim]{details}[/dim]"
                
            self.console.print(text)

    def start_progress(self, task_name: str, task_id: str):
        if task_id not in self.active_tasks:
            self.active_tasks[task_id] = self.progress.add_task(f"[cyan]Task: {task_id}[/cyan] - {task_name}", total=100)
            
    def update_progress(self, task_id: str, description: str = None, advance: float = 0, completed: float = None):
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            kwargs = {}
            if description: kwargs["description"] = f"[cyan]Task: {task_id}[/cyan] - {description}"
            if advance: kwargs["advance"] = advance
            if completed is not None: kwargs["completed"] = completed
            self.progress.update(task, **kwargs)

    def stop_progress(self, task_id: str):
        if task_id in self.active_tasks:
            self.progress.remove_task(self.active_tasks[task_id])
            del self.active_tasks[task_id]

    def stop_all(self):
        self.progress.stop()

    def info(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        if "payload generated" in str(message) or (details and "payload generated" in str(details)):
            return  # Hide internal payload log
        self.print(LogLevel.INFO, message, details, task_id, agent_id)
        
    def success(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.print(LogLevel.SUCCESS, message, details, task_id, agent_id)
        
    def warning(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.print(LogLevel.WARNING, message, details, task_id, agent_id)
        
    def error(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.print(LogLevel.ERROR, message, details, task_id, agent_id)
        
    def debug(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        import os
        # Only show DEBUG in full debug mode, never show framework internals by default
        if os.environ.get("DELFHOS_DEBUG") == "1":
            self.print(LogLevel.DEBUG, message, details, task_id, agent_id)
        
    def task(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.print(LogLevel.TASK, message, details, task_id, agent_id)
        
    def system(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.print(LogLevel.SYSTEM, message, details, task_id, agent_id)
        
    def tool(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.print(LogLevel.TOOL, message, details, task_id, agent_id)

    def print_task_box(self, task_message: str):
        """Display the user's task in a box at the beginning of execution"""
        # Truncate long messages for display
        display_msg = task_message if len(task_message) < 200 else task_message[:197] + "..."
        task_panel = Panel(display_msg, title="[bold]Task[/bold]", border_style="blue", expand=False)
        # Force immediate print with aggressive flushing
        with self._lock:
            self.console.print(task_panel)
            self.console.print()  # Blank line for spacing
            # Flush all output streams to ensure task box appears first
            import sys
            if hasattr(self.console.file, 'flush'):
                self.console.file.flush()
            sys.stdout.flush()
            sys.stderr.flush()

    def task_summary(self, task_id: str, duration: float, tokens: dict, status: str, final_message: str = None, computational_time: float = None, wait_time: float = None, agent_id: Optional[str] = None, task_status: str = "success", tools: list = None, llm_config: Optional[str] = None):
        # Create summary table
        summary_table = Table(title="Execution Summary", show_header=True, header_style="bold cyan")
        summary_table.add_column("Attribute", style="bold cyan", width=20)
        summary_table.add_column("Value", style="green")

        # Status and outcome
        status_color = "green" if task_status == "success" else "red"
        summary_table.add_row("Status", f"[{status_color}]✓ {task_status.upper()}[/{status_color}]")

        # Timing
        if wait_time and wait_time > 0:
            duration_str = f"{duration:.2f}s (compute: {computational_time:.2f}s, wait: {wait_time:.2f}s)"
        else:
            duration_str = f"{duration:.2f}s"
        summary_table.add_row("Duration", duration_str)

        # Tokens
        summary_table.add_row("Tokens", f"{tokens.get('tokens_used', 0)} (in: {tokens.get('input_tokens', 0)}, out: {tokens.get('output_tokens', 0)})")
        # Cost (USD)
        cost_val = tokens.get('total_cost_usd')
        cost_str = f"${float(cost_val):.6f}" if cost_val is not None else "None"
        summary_table.add_row("Cost (USD)", cost_str)

        # LLM Configuration
        if llm_config:
            summary_table.add_row("LLM", llm_config)

        # Tools used (exclude framework internals like llm_code_generation)
        if tools:
            # Filter out framework internals - only show actual user tools
            user_tools = [t for t in tools if t != "llm_code_generation"]
            if user_tools:
                tools_str = ", ".join(user_tools)
                summary_table.add_row("Tools Used", tools_str)

        summary_panel = Panel(summary_table, border_style="blue", expand=False)
        
        # Create result section if available
        if final_message:
            # Convert markdown links to Rich clickable links and render as markdown
            rich_result = convert_markdown_links_to_rich(final_message)
            # Use uniform white color for all text (no special styling for titles/headings)
            markdown_content = Markdown(rich_result, style="white")
            result_panel = Panel(markdown_content, title="[bold]Result[/bold]", border_style="green", expand=False)
            
            # Display summary and result side-by-side
            side_by_side = Columns([summary_panel, result_panel])
            self.console.print(side_by_side)
        else:
            # Just show summary if no result message
            self.console.print(summary_panel)

    def print_exception(self, exc: Exception, title: str = "Task failed"):
        """Print a beautiful error box for a caught exception."""
        from rich.panel import Panel
        from rich.console import Group
        from rich.traceback import Traceback
        from rich.text import Text
        import sys
        
        # Make sure we stop any ongoing progress bars before printing
        try:
            self.stop_all()
        except Exception:
            pass

        code, message, hint = extract_error_payload(exc)

        # Use sys.exc_info() if available to get the full traceback, else just create from exception
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if exc_value is exc:
            tb = Traceback.from_exception(exc_type, exc_value, exc_traceback, show_locals=False)
        else:
            tb = Traceback.from_exception(type(exc), exc, exc.__traceback__, show_locals=False)

        group = Group(
            Text(f"Delfhos encountered an error during: {title}", style="bold red"),
            Text(""),
            tb,
            Text(""),
            Text(f"Message: {message}", style="white"),
            Text(f"💡 Hint: {hint}", style="bold yellow")
        )

        panel = Panel(
            group,
            title=f"[bold red]❌ [{code}] Delfhos Error[/bold red]",
            border_style="red",
            expand=False
        )
        self.console.print(panel)

def _delfhos_excepthook(exc_type, exc_val, tb_obj):
    """Custom exception hook to print beautiful error boxes for Delfhos errors."""
    from rich.panel import Panel
    from rich.console import Group
    from rich.traceback import Traceback
    from rich.text import Text
    
    # Don't intercept KeyboardInterrupt
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_val, tb_obj)
        return

    # Create the beautiful traceback
    tb = Traceback.from_exception(exc_type, exc_val, tb_obj, show_locals=False)
    code, message, hint = extract_error_payload(exc_val)

    group = Group(
        Text("Delfhos encountered an error:", style="bold red"),
        Text(""),
        tb,
        Text(""),
        Text(f"Message: {message}", style="white"),
        Text(f"💡 Hint: {hint}", style="bold yellow")
    )
    panel = Panel(
        group,
        title=f"[bold red]❌ [{code}] Delfhos Error[/bold red]",
        border_style="red",
        expand=False
    )

    # Make sure we stop any ongoing progress bars before printing
    try:
        console.stop_all()
    except:
        pass
        
    console.console.print(panel)

# Override the global exception hook
sys.excepthook = _delfhos_excepthook

console = ProfessionalConsole()
