import sys
import threading
import time
import re
from contextlib import contextmanager
from enum import Enum
from typing import Optional, Dict

from rich.align import Align
from rich.box import ROUNDED
from rich.columns import Columns
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text


# ── Delfhos brand palette (Code-act Framework v2.0.0) ─────────────
# Monochrome metallic finish: carbon / graphite / stark white / muted zinc.
# Soft amber is the sole warm accent, reserved for warnings & cursors.
# Mint green is the success accent, reserved for ticks and completions.
BRAND_CARBON      = "#050505"  # Forged Carbon Matte  (backgrounds)
BRAND_GRAPHITE    = "#121212"  # Graphite Anodized    (panels)
BRAND_STARK       = "#FFFFFF"  # Stark Matte White    (primary text, logo, brand accent)
BRAND_ZINC        = "#717983"  # Muted Zinc Neutral   (metadata, annotations, dim)
BRAND_ZINC_BRIGHT = "#A8ADB5"  # brighter zinc        (secondary text)
BRAND_AMBER       = "#FF7983"  # Soft Amber           (warnings, cursors)
BRAND_ERROR       = "#E05561"  # desaturated red      (errors — stays tonally close to amber)
BRAND_SUCCESS     = "#D4D7DB"  # near-stark silver    (success, subtle)
BRAND_MINT        = "#4EC994"  # Mint Green           (ticks, success accents)


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
            SpinnerColumn(spinner_name="dots", style=BRAND_AMBER, speed=1.2),
            TextColumn(f"[{BRAND_ZINC_BRIGHT}]{{task.description}}[/{BRAND_ZINC_BRIGHT}]"),
            console=self.console,
            transient=True
        )
        self.active_tasks: Dict[str, int] = {}
        self._loading_tasks: Dict[str, int] = {}

        # When True, all print/loading output is queued instead of displayed.
        # This prevents concurrent async task output from corrupting the
        # interactive approval prompt (questionary).
        self._suppressed = False
        self._suppressed_queue: list = []
        self._suppression_depth = 0
        self._pause_depth = 0
        self._progress_running = False

    def _remove_all_loading_tasks_locked(self):
        for task_id in list(self._loading_tasks.values()):
            try:
                self.progress.remove_task(task_id)
            except Exception:
                pass
        self._loading_tasks.clear()

    def _stop_progress_locked(self):
        if not self._progress_running:
            return
        try:
            self.progress.stop()
        except Exception:
            pass
        finally:
            self._progress_running = False

    def _start_progress_locked(self):
        if self._progress_running:
            return
        if self._suppression_depth > 0 or self._pause_depth > 0:
            return
        if not self._loading_tasks:
            return
        try:
            self.progress.start()
            self._progress_running = True
        except Exception:
            self._progress_running = False

    def _get_color(self, level: LogLevel) -> str:
        # Monochrome metallic palette. Only warnings/errors carry warm hue
        # (soft amber / desaturated red) — everything else lives on the
        # carbon → zinc → stark-white axis, matching the brand system.
        colors = {
            LogLevel.INFO:    BRAND_ZINC_BRIGHT,
            LogLevel.SUCCESS: BRAND_MINT,
            LogLevel.WARNING: BRAND_AMBER,
            LogLevel.ERROR:   BRAND_ERROR,
            LogLevel.DEBUG:   BRAND_ZINC,
            LogLevel.TASK:    BRAND_STARK,
            LogLevel.SYSTEM:  BRAND_ZINC_BRIGHT,
            LogLevel.TOOL:    BRAND_ZINC_BRIGHT,
        }
        return colors.get(level, BRAND_STARK)

    def print(self, level: LogLevel, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None):
        with self._lock:
            if self._suppressed:
                self._suppressed_queue.append((level, message, details, task_id, agent_id))
                return

            self._print_line(level, message, details)

    def _print_line(self, level: LogLevel, message: str, details: Optional[str] = None):
        """Render a single log line to the console (caller must hold _lock)."""
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
            parts.append(f"[#717983]{time_str:>10}[/#717983]")

        parts.append(f"  [{color}]{symbol}[/{color}] {message}")

        if details:
            parts.append(f"  [#717983]{details}[/#717983]")

        self.console.print("".join(parts))

    def stop_all(self):
        with self._lock:
            self._remove_all_loading_tasks_locked()
            self._stop_progress_locked()

    def suppress(self):
        """Suppress all output, queuing it for later.

        Used during interactive approval prompts so concurrent async task
        output doesn't corrupt the terminal.  Call ``unsuppress()`` when
        the interactive session is over.
        """
        with self._lock:
            self._suppression_depth += 1
            self._suppressed = True

            # Already suppressed by another caller; keep waiting for the
            # matching number of unsuppress() calls before resuming output.
            if self._suppression_depth > 1:
                return

            # Stop the live progress renderer completely — its repaints
            # would overwrite the questionary prompt otherwise.
            self._remove_all_loading_tasks_locked()
            self._stop_progress_locked()

    def unsuppress(self):
        """Resume normal output and flush any queued messages."""
        with self._lock:
            if self._suppression_depth == 0:
                return

            self._suppression_depth -= 1
            self._suppressed = self._suppression_depth > 0

            # Still suppressed by another caller.
            if self._suppression_depth > 0:
                return

            # Restart the live progress renderer unless chat input has paused it.
            self._start_progress_locked()

            # Flush queued messages
            queued = list(self._suppressed_queue)
            self._suppressed_queue.clear()
            for level, message, details, _tid, _aid in queued:
                self._print_line(level, message, details)

    def pause_live(self, clear_tasks: bool = False):
        """Temporarily pause live spinner rendering (nesting-safe)."""
        with self._lock:
            self._pause_depth += 1
            if clear_tasks:
                self._remove_all_loading_tasks_locked()
            self._stop_progress_locked()

    def resume_live(self):
        """Resume live spinner rendering when all pauses have completed."""
        with self._lock:
            if self._pause_depth == 0:
                return
            self._pause_depth -= 1
            if self._pause_depth == 0 and self._suppression_depth == 0:
                self._start_progress_locked()

    @contextmanager
    def paused_live(self, clear_tasks: bool = False):
        """Context manager form of pause_live()/resume_live()."""
        self.pause_live(clear_tasks=clear_tasks)
        try:
            yield
        finally:
            self.resume_live()

    def loading_start(self, label: str, key: str):
        """Show a simple circle spinner while an operation is running."""
        with self._lock:
            if self._suppressed or self._pause_depth > 0 or key in self._loading_tasks:
                return
            try:
                task_id = self.progress.add_task(label, total=None)
            except Exception:
                return
            self._loading_tasks[key] = task_id
            self._start_progress_locked()

    def loading_stop(self, key: str):
        """Remove a spinner loading line."""
        with self._lock:
            task_id = self._loading_tasks.pop(key, None)
            if task_id is None:
                return
            try:
                self.progress.remove_task(task_id)
            except Exception:
                pass
            if not self._loading_tasks:
                self._stop_progress_locked()

    def loading_stop_all(self):
        """Stop all active spinners and force a clean display refresh."""
        with self._lock:
            self._remove_all_loading_tasks_locked()
            # Stop the live renderer and keep it idle until a new spinner starts.
            self._stop_progress_locked()

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
        """Display the user's task in a clean, accented box."""
        display_msg = task_message if len(task_message) < 400 else task_message[:397] + "..."

        body = Text()
        body.append("❯ ", style=f"bold {BRAND_STARK}")
        body.append(display_msg, style=BRAND_STARK)

        task_panel = Panel(
            body,
            title=f"[bold {BRAND_STARK}]Task[/bold {BRAND_STARK}]",
            title_align="left",
            border_style=BRAND_ZINC,
            box=ROUNDED,
            expand=False,
            padding=(0, 2),
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

    # Delfhos ASCII logo (matches delfhosLogo.png)
    _LOGO_LINES = [
        "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
        "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
        "@@@@@@              @@@@@@@@@@@@@@",
        "@@@@@@@@              @@@@@@@@@@@@",
        "@@@@@@@@@@              @@@@@@@@@@",
        "@@@@@@@@@@@ @@@@@        @@@@@@@@@",
        "@@@@@@@@@   @@@@@@@        @@@@@@@",
        "@@@@@@@     @@@@@@@@@        @@@@@",
        "@@@@@       @@@@@@@@@@@        @@@",
        "@@@@@@@     @@@@@@@@@        @@@@@",
        "@@@@@@@@@   @@@@@@@        @@@@@@@",
        "@@@@@@@@@@@ @@@@@         @@@@@@@@",
        "@@@@@@@@@@              @@@@@@@@@@",
        "@@@@@@@@              @@@@@@@@@@@@",
        "@@@@@@              @@@@@@@@@@@@@@",
        "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
        "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
    ]

    def print_welcome_banner(
        self,
        version: str,
        llm_config: Optional[str] = None,
        tools: Optional[list] = None,
        agent_id: Optional[str] = None,
        cwd: Optional[str] = None,
    ):
        """Render a Claude-Code-style welcome banner with the Delfhos ASCII logo."""
        tool_list = tools or []
        tool_count = len(tool_list)
        model_str = (llm_config or "not configured").strip()

        # ── Left column: ASCII logo ───────────────────────────────────
        logo_text = Text()
        for i, line in enumerate(self._LOGO_LINES):
            if i > 0:
                logo_text.append("\n")
            logo_text.append(line, style=f"bold {BRAND_STARK}")

        # ── Right column: name chip + info rows ───────────────────────
        header = Text()
        header.append("Delfhos", style=f"bold {BRAND_STARK}")
        header.append("  ")
        # Stark-white chip on graphite — matches the "Stark Matte White" swatch.
        header.append(f" v{version} ", style=f"bold {BRAND_CARBON} on {BRAND_STARK}")

        if tool_count == 0:
            tools_line = "none"
        elif tool_count <= 5:
            tools_line = ", ".join(tool_list)
        else:
            tools_line = ", ".join(tool_list[:5]) + f"  +{tool_count - 5} more"

        info_rows = Table.grid(padding=(0, 2))
        info_rows.add_column(style=BRAND_ZINC, no_wrap=True)
        info_rows.add_column(style=BRAND_STARK, overflow="fold")
        info_rows.add_row("Model", model_str)
        info_rows.add_row("Tools", f"{tool_count} connected  [{BRAND_ZINC}]·[/{BRAND_ZINC}]  {tools_line}")
        if agent_id:
            info_rows.add_row("Agent", f"[dim]{agent_id}[/dim]")
        if cwd:
            info_rows.add_row("Cwd", f"[dim]{cwd}[/dim]")

        # Vertically center the info block beside the logo.
        # Logo is 17 lines; info block ~5 lines → pad ~6 lines from top.
        logo_height = len(self._LOGO_LINES)
        info_height = 2 + info_rows.row_count + (1 if agent_id else 0) + (1 if cwd else 0)
        top_pad = max(0, (logo_height - info_height) // 2)
        right_col = Group(Text("\n" * (top_pad - 1)) if top_pad > 0 else Text(""), header, Text(""), info_rows)

        # ── Side-by-side: logo | info ─────────────────────────────────
        side_by_side = Table.grid(padding=(0, 4))
        side_by_side.add_column(no_wrap=True)
        side_by_side.add_column()
        side_by_side.add_row(logo_text, right_col)

        # ── Bottom hint bar ───────────────────────────────────────────
        hint = Text()
        sep_style = BRAND_ZINC
        cmd_style = f"bold {BRAND_STARK}"
        hint.append("/help", style=cmd_style)
        hint.append("  ·  ", style=sep_style)
        hint.append("/clear", style=cmd_style)
        hint.append("  ·  ", style=sep_style)
        hint.append("/stop", style=cmd_style)
        hint.append("  ·  ", style=sep_style)
        hint.append("/exit", style=cmd_style)

        body = Group(side_by_side, Text(""), hint)

        banner = Panel(
            body,
            border_style=BRAND_ZINC,
            box=ROUNDED,
            expand=False,
            padding=(1, 2),
        )

        with self._lock:
            self.console.print()
            self.console.print(banner)
            self.console.print()

    def task_summary(self, task_id: str, duration: float, tokens: dict, status: str, final_message: str = None, computational_time: float = None, wait_time: float = None, agent_id: Optional[str] = None, task_status: str = "success", tools: list = None, llm_config: Optional[str] = None):
        # Stop all spinners before printing so the progress renderer doesn't
        # race with console.print() calls and cause ghost spinner lines.
        self.loading_stop_all()

        status_symbol = "✓" if task_status == "success" else "✗"
        status_color = BRAND_MINT if task_status == "success" else BRAND_ERROR
        status_word = "Completed" if task_status == "success" else "Failed"

        def _as_int(value) -> int:
            try:
                if value is None:
                    return 0
                return int(value)
            except (TypeError, ValueError):
                return 0

        input_t = _as_int(tokens.get('input_tokens', tokens.get('prompt_tokens', 0)))
        output_t = _as_int(tokens.get('output_tokens', tokens.get('completion_tokens', 0)))
        tokens_used = _as_int(tokens.get('tokens_used', tokens.get('total_tokens', input_t + output_t)))

        # Build compact stats
        stats = []
        stats.append(f"{duration:.2f}s")
        stats.append(f"{tokens_used:,} tok")
        stats.append(f"in/out {input_t:,}/{output_t:,}")
        cost_val = tokens.get('total_cost_usd')
        if cost_val is not None:
            stats.append(f"${float(cost_val):.4f}")

        sep = f"  [{BRAND_ZINC}]·[/{BRAND_ZINC}]  "
        compact_line = (
            f"  [{status_color}]{status_symbol}[/{status_color}] "
            f"[bold {status_color}]{status_word}[/bold {status_color}]"
            f"  [{BRAND_ZINC}]│[/{BRAND_ZINC}]  "
            f"[{BRAND_ZINC_BRIGHT}]{sep.join(stats)}[/{BRAND_ZINC_BRIGHT}]"
        )
        self.console.print(compact_line)

        # Verbose: show detailed breakdown
        if self.verbose:
            detail_parts = []
            detail_parts.append(f"tokens={tokens_used:,}")
            detail_parts.append(f"in={input_t:,}")
            detail_parts.append(f"out={output_t:,}")
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
            markdown_content = Markdown(rich_result, style=BRAND_STARK)
            result_color = BRAND_MINT if task_status == "success" else BRAND_ERROR
            border_color = BRAND_MINT if task_status == "success" else BRAND_ERROR
            result_icon = "✓" if task_status == "success" else "✗"
            result_panel = Panel(
                markdown_content,
                title=f"[bold {result_color}]{result_icon} Result[/bold {result_color}]",
                title_align="left",
                border_style=border_color,
                box=ROUNDED,
                expand=False,
                padding=(0, 2),
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
            Text(f"Delfhos encountered an error during: {title}", style=f"bold {BRAND_ERROR}"),
            Text(""),
            tb,
            Text(""),
            Text(f"Message: {message}", style=BRAND_STARK),
            Text(f"Hint: {hint}", style=f"bold {BRAND_AMBER}")
        )

        panel = Panel(
            group,
            title=f"[bold {BRAND_ERROR}][{code}] Error[/bold {BRAND_ERROR}]",
            border_style=BRAND_ERROR,
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
        Text("Delfhos encountered an error:", style=f"bold {BRAND_ERROR}"),
        Text(""),
        tb,
        Text(""),
        Text(f"Message: {message}", style=BRAND_STARK),
        Text(f"Hint: {hint}", style=f"bold {BRAND_AMBER}")
    )
    panel = Panel(
        group,
        title=f"[bold {BRAND_ERROR}][{code}] Error[/bold {BRAND_ERROR}]",
        border_style=BRAND_ERROR,
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
