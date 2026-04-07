import sys
import threading
import time
import re
from enum import Enum
from typing import Optional, Dict

from rich.console import Console, Group
from rich.progress import Progress, SpinnerColumn, TextColumn
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
    pattern = r'\[([^\]]+)\]\(([^\)]+)\)'
    replacement = r'[link=\2]\1[/link]'
    return re.sub(pattern, replacement, text)

class ProfessionalConsole:
    """Minimal, clean console output inspired by modern CLI tools."""

    _SYMBOLS = {
        LogLevel.INFO: "●",
        LogLevel.SUCCESS: "✓",
        LogLevel.WARNING: "!",
        LogLevel.ERROR: "✗",
        LogLevel.DEBUG: "·",
        LogLevel.TASK: "◆",
        LogLevel.SYSTEM: "◆",
        LogLevel.TOOL: "▸",
    }

    def __init__(self, enable_colors: bool = True):
        import sys
        self.console = Console(file=sys.__stderr__)
        self._lock = threading.Lock()
        self.start_time = time.time()
        self.verbose = False  # Set by orchestrator based on verbose="high"

        self.progress = Progress(
            TextColumn("  "),
            SpinnerColumn(spinner_name="dots", style="bright_cyan", speed=1.2),
            TextColumn("{task.description}"),
            console=self.console,
            transient=True
        )
        self.active_tasks: Dict[str, int] = {}
        self._loading_tasks: Dict[str, int] = {}
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
            symbol = self._SYMBOLS.get(level, "●")

            parts = []

            # Timestamps only in verbose mode
            if self.verbose:
                elapsed_ms = int((time.time() - self.start_time) * 1000)
                if elapsed_ms < 1000:
                    time_str = f"+{elapsed_ms}ms"
                else:
                    time_str = f"+{elapsed_ms / 1000:.2f}s"
                parts.append(f"[grey50]{time_str:>10}[/grey50]")

            parts.append(f"  [{color}]{symbol}[/{color}] {message}")

            if details:
                parts.append(f"  [grey50]{details}[/grey50]")

            self.console.print("".join(parts))

    def stop_all(self):
        self.progress.stop()

    def loading_start(self, label: str, key: str):
        """Show a simple circle spinner while an operation is running."""
        if key in self._loading_tasks:
            return
        task_id = self.progress.add_task(label, total=None)
        self._loading_tasks[key] = task_id

    def loading_stop(self, key: str):
        """Remove a spinner loading line."""
        if key in self._loading_tasks:
            self.progress.remove_task(self._loading_tasks.pop(key))

    def loading_stop_all(self):
        """Stop all active spinners and force a clean display refresh."""
        for task_id in list(self._loading_tasks.values()):
            try:
                self.progress.remove_task(task_id)
            except Exception:
                pass
        self._loading_tasks.clear()
        # Stop and restart the live renderer to flush any lingering spinner frames
        try:
            self.progress.stop()
            self.progress.start()
        except Exception:
            pass

    def info(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        if "payload generated" in str(message) or (details and "payload generated" in str(details)):
            return
        self.print(LogLevel.INFO, message, details, task_id, agent_id)

    def success(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.print(LogLevel.SUCCESS, message, details, task_id, agent_id)

    def warning(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.print(LogLevel.WARNING, message, details, task_id, agent_id)

    def error(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.print(LogLevel.ERROR, message, details, task_id, agent_id)

    def debug(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        import os
        if os.environ.get("DELFHOS_DEBUG") == "1":
            self.print(LogLevel.DEBUG, message, details, task_id, agent_id)

    def task(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.print(LogLevel.TASK, message, details, task_id, agent_id)

    def system(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.print(LogLevel.SYSTEM, message, details, task_id, agent_id)

    def tool(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        self.print(LogLevel.TOOL, message, details, task_id, agent_id)

    def print_task_box(self, task_message: str):
        """Display the user's task in a clean, minimal box."""
        display_msg = task_message if len(task_message) < 200 else task_message[:197] + "..."
        task_panel = Panel(
            display_msg,
            title="[bold]Task[/bold]",
            border_style="dim",
            expand=False,
            padding=(0, 2)
        )
        with self._lock:
            self.console.print()
            self.console.print(task_panel)
            self.console.print()
            import sys
            if hasattr(self.console.file, 'flush'):
                self.console.file.flush()
            sys.stdout.flush()
            sys.stderr.flush()

    def task_summary(self, task_id: str, duration: float, tokens: dict, status: str, final_message: str = None, computational_time: float = None, wait_time: float = None, agent_id: Optional[str] = None, task_status: str = "success", tools: list = None, llm_config: Optional[str] = None):
        status_symbol = "✓" if task_status == "success" else "✗"
        status_color = "green" if task_status == "success" else "red"
        status_word = "Completed" if task_status == "success" else "Failed"

        # Build compact stats
        stats = []
        stats.append(f"{duration:.2f}s")
        cost_val = tokens.get('total_cost_usd')
        if cost_val is not None:
            stats.append(f"${float(cost_val):.4f}")

        compact_line = f"  [{status_color}]{status_symbol}[/{status_color}] [bold]{status_word}[/bold]  [grey50]{'  ·  '.join(stats)}[/grey50]"
        self.console.print(compact_line)

        # Verbose: show detailed breakdown
        if self.verbose:
            detail_parts = []
            tokens_used = tokens.get('tokens_used', 0)
            input_t = tokens.get('input_tokens', 0)
            output_t = tokens.get('output_tokens', 0)
            detail_parts.append(f"{tokens_used} tokens (in: {input_t}, out: {output_t})")
            if cost_val is not None:
                detail_parts.append(f"${float(cost_val):.6f}")
            self.console.print(f"    [dim]{'  ·  '.join(detail_parts)}[/dim]")

            if wait_time and wait_time > 0 and computational_time:
                self.console.print(f"    [dim]compute: {computational_time:.2f}s  ·  wait: {wait_time:.2f}s[/dim]")

            if llm_config:
                self.console.print(f"    [dim]LLM: {llm_config}[/dim]")

            if tools:
                user_tools = [t for t in tools if t != "llm_code_generation"]
                if user_tools:
                    self.console.print(f"    [dim]Tools: {', '.join(user_tools)}[/dim]")

        self.console.print()

        # Result panel
        if final_message:
            rich_result = convert_markdown_links_to_rich(final_message)
            markdown_content = Markdown(rich_result, style="white")
            result_panel = Panel(
                markdown_content,
                title="[bold]Result[/bold]",
                border_style="green" if task_status == "success" else "red",
                expand=False,
                padding=(0, 2)
            )
            self.console.print(result_panel)

    def print_exception(self, exc: Exception, title: str = "Task failed"):
        """Print a beautiful error box for a caught exception."""
        from rich.panel import Panel
        from rich.console import Group
        from rich.traceback import Traceback
        from rich.text import Text
        import sys

        try:
            self.stop_all()
        except Exception:
            pass

        code, message, hint = extract_error_payload(exc)

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
            Text(f"Hint: {hint}", style="bold yellow")
        )

        panel = Panel(
            group,
            title=f"[bold red][{code}] Error[/bold red]",
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

    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_val, tb_obj)
        return

    tb = Traceback.from_exception(exc_type, exc_val, tb_obj, show_locals=False)
    code, message, hint = extract_error_payload(exc_val)

    group = Group(
        Text("Delfhos encountered an error:", style="bold red"),
        Text(""),
        tb,
        Text(""),
        Text(f"Message: {message}", style="white"),
        Text(f"Hint: {hint}", style="bold yellow")
    )
    panel = Panel(
        group,
        title=f"[bold red][{code}] Error[/bold red]",
        border_style="red",
        expand=False
    )

    try:
        console.stop_all()
    except:
        pass

    console.console.print(panel)

# Override the global exception hook
sys.excepthook = _delfhos_excepthook

console = ProfessionalConsole()
