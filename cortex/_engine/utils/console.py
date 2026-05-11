import sys
import threading
import time
import re
from contextlib import contextmanager
from enum import Enum
from typing import Optional, Dict

from rich.box import SQUARE
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text
from rich.theme import Theme


# ── Delfhos design system palette (see DESIGN.md §2, §4, §11) ─────
# Near-monochrome. Color earns its place. Mono for technical surfaces.
# These hex values are the canonical tokens shared with the marketing
# site and docs — keep them in sync with `app/globals.css`.

# Surfaces
BG          = "#000000"
BG_CARD     = "#0d0d0d"
BG_RAISED   = "#141414"
RULE        = "#2a2a2a"

# Text
TEXT        = "#ffffff"
TEXT_SUB    = "#c8c8c8"
TEXT_MUTE   = "#8e8e8e"
TEXT_FAINT  = "#4a4a4a"

# Syntax / log roles
KEYWORD     = "#c4b5fd"
FUNC        = "#7dd3fc"
STRING      = "#86efac"
NUMBER      = "#7dd3fc"
DECORATOR   = "#f9a8d4"
OPERATOR    = "#6e6e6e"
COMMENT     = "#4a4a4a"

# Semantic — reserved for terminal states
SUCCESS     = "#22c55e"
SUCCESS_SOFT = "#86efac"
WARNING     = "#f59e0b"
ERROR       = "#ef4444"
ERROR_SOFT  = "#fca5a5"
INFO        = "#3b82f6"


# Markdown theme aligned with the Delfhos palette.
# Overrides Rich's default magenta headings and cyan code blocks.
_MARKDOWN_THEME = Theme({
    "markdown.h1":          f"bold {TEXT}",
    "markdown.h1.border":   RULE,
    "markdown.h2":          f"bold {FUNC}",
    "markdown.h3":          FUNC,
    "markdown.h4":          f"italic {FUNC}",
    "markdown.h5":          f"italic {TEXT_MUTE}",
    "markdown.h6":          TEXT_FAINT,
    "markdown.strong":      f"bold {TEXT}",
    "markdown.em":          f"italic {TEXT_SUB}",
    "markdown.code":        f"{STRING} on {BG_CARD}",
    "markdown.code_block":  f"{STRING} on {BG_CARD}",
    "markdown.block_quote": TEXT_MUTE,
    "markdown.list":        TEXT_SUB,
    "markdown.item.bullet": OPERATOR,
    "markdown.item.number": FUNC,
    "markdown.hr":          RULE,
    "markdown.link":        FUNC,
    "markdown.link_url":    f"underline {FUNC}",
    "markdown.table.border":  RULE,
    "markdown.table.header":  f"bold {TEXT_SUB}",
})


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


def _label(text: str) -> Text:
    """Simple lowercase muted label."""
    return Text(text.lower(), style=TEXT_MUTE)


def _hairline(width: int = 64) -> Text:
    """A thin rule made from U+2500, color RULE — never `=`, never `*` (§11.3)."""
    return Text("─" * width, style=RULE)


class ProfessionalConsole:
    """Console output aligned with the Delfhos design system.

    Quiet by default. Confident when it counts. Near-monochrome.
    See DESIGN.md §11 for the rules this class implements.
    """

    # Glyphs are uniform across the system (§11.2). No emoji, ever.
    _SYMBOLS = {
        LogLevel.INFO:    "·",
        LogLevel.SUCCESS: "✓",
        LogLevel.WARNING: "!",
        LogLevel.ERROR:   "✗",
        LogLevel.DEBUG:   "·",
        LogLevel.TASK:    "▸",
        LogLevel.SYSTEM:  "▸",
        LogLevel.TOOL:    "▸",
    }

    # Lowercase 3–4 char level tags shown in verbose mode (§11.2).
    _TAGS = {
        LogLevel.INFO:    "info",
        LogLevel.SUCCESS: "ok",
        LogLevel.WARNING: "warn",
        LogLevel.ERROR:   "err",
        LogLevel.DEBUG:   "dbg",
        LogLevel.TASK:    "task",
        LogLevel.SYSTEM:  "sys",
        LogLevel.TOOL:    "tool",
    }

    def __init__(self, enable_colors: bool = True):
        self.console = Console(file=sys.__stderr__)
        self._lock = threading.Lock()
        self.start_time = time.time()
        self.verbose = False  # Set by orchestrator based on verbose="high"

        # Single-color spinner per §10 — no rainbow progress bars.
        # Layout mirrors `_print_line` exactly so the spinner glyph sits in
        # the same column as level symbols (✓ ✗ ▸ ·) and its label aligns
        # with message text. Geometry: 2-space indent · 1-char glyph ·
        # 2-space gap · description.
        self.progress = Progress(
            TextColumn("  "),
            SpinnerColumn(spinner_name="dots", style=FUNC, speed=1.2),
            TextColumn(f"  [{TEXT_SUB}]{{task.description}}[/{TEXT_SUB}]"),
            console=self.console,
            transient=True,
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
        # Map levels to design-system roles (DESIGN.md §4 console-log mapping).
        # Color earns its place: only the three semantic terminal states wear
        # a saturated hue. Action levels (task/system/tool) live on the mute
        # axis — their `scope` tag (sky, FUNC) is the sole accent, which keeps
        # the page calm and lets `✓` / `✗` / `!` actually mean something.
        colors = {
            LogLevel.INFO:    TEXT_MUTE,
            LogLevel.SUCCESS: SUCCESS_SOFT,
            LogLevel.WARNING: WARNING,
            LogLevel.ERROR:   ERROR_SOFT,
            LogLevel.DEBUG:   TEXT_FAINT,
            LogLevel.TASK:    TEXT_MUTE,
            LogLevel.SYSTEM:  TEXT_MUTE,
            LogLevel.TOOL:    TEXT_MUTE,
        }
        return colors.get(level, TEXT)

    def print(self, level: LogLevel, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None, scope: Optional[str] = None):
        with self._lock:
            if self._suppressed:
                self._suppressed_queue.append((level, message, details, task_id, agent_id, scope))
                return

            self._print_line(level, message, details, scope=scope)

    def _print_line(self, level: LogLevel, message: str, details: Optional[str] = None, scope: Optional[str] = None):
        """Render a single log line per §11.1 (caller must hold _lock).

        Non-verbose: ``  {symbol}  [{scope}]  {message}  [{details-mute}]``
        Verbose:     ``+{time}  {tag}  {symbol}  [{scope}]  {message}  [{details}]``

        ``scope`` renders in #7dd3fc (func color — "an actor / callable", §4).
        ``message`` renders in #ffffff (primary text).
        ``details`` renders in #8e8e8e (mute) on a hanging-indented second line.
        """
        color = self._get_color(level)
        symbol = self._SYMBOLS.get(level, "·")

        line = Text("  ")

        if self.verbose:
            elapsed_ms = int((time.time() - self.start_time) * 1000)
            if elapsed_ms < 1000:
                time_str = f"+{elapsed_ms}ms"
            else:
                time_str = f"+{elapsed_ms / 1000:.2f}s"
            line.append(f"{time_str:>8}", style=TEXT_MUTE)
            line.append("  ")
            tag = self._TAGS.get(level, "log")
            line.append(f"{tag:<4}", style=color)
            line.append("  ")

        line.append(symbol, style=color)
        line.append("  ")

        # Track visible char count for inline-vs-multiline decision.
        vis = 2 + 1 + 2  # leading spaces + symbol + gap

        if self.verbose:
            vis += 8 + 2 + 4 + 2  # time + gap + tag + gap

        # Optional scope — rendered in func color (#7dd3fc) per §4.
        if scope:
            line.append(str(scope), style=FUNC)
            line.append("  ", style=OPERATOR)
            vis += len(str(scope)) + 2

        # Body in primary text — competes with nothing.
        line.append(str(message), style=TEXT)
        vis += len(str(message))

        if details:
            details_str = str(details)
            term_width = min(self.console.width or 100, 120)
            if vis + 2 + len(details_str) <= term_width:
                # ── Inline: fits on the same line ──────────────────────────
                line.append("  ", style=TEXT_MUTE)
                line.append(details_str, style=TEXT_MUTE)
            else:
                # ── Multiline: arrow continuation on next line ──────────────
                line.append("\n      ", style=TEXT_MUTE)
                line.append("↳  ", style=TEXT_FAINT)
                line.append(details_str, style=TEXT_MUTE)

        self.console.print(line)

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

            if self._suppression_depth > 1:
                return

            self._remove_all_loading_tasks_locked()
            self._stop_progress_locked()

    def unsuppress(self):
        """Resume normal output and flush any queued messages."""
        with self._lock:
            if self._suppression_depth == 0:
                return

            self._suppression_depth -= 1
            self._suppressed = self._suppression_depth > 0

            if self._suppression_depth > 0:
                return

            self._start_progress_locked()

            queued = list(self._suppressed_queue)
            self._suppressed_queue.clear()
            for item in queued:
                level, message, details, _tid, _aid = item[:5]
                scope = item[5] if len(item) > 5 else None
                self._print_line(level, message, details, scope=scope)

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
        """Show a single-color dots spinner while an operation is running."""
        with self._lock:
            if self._suppressed or self._pause_depth > 0 or key in self._loading_tasks:
                return
            # Blank line before the spinner so it doesn't visually merge with
            # the log line immediately above it.
            if not self._loading_tasks:
                self.console.print()
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
            self._stop_progress_locked()

    def info(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None, scope: Optional[str] = None):
        if "payload generated" in str(message) or (details and "payload generated" in str(details)):
            return
        self.print(LogLevel.INFO, message, details, task_id, agent_id, scope=scope)

    def success(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None, scope: Optional[str] = None):
        self.print(LogLevel.SUCCESS, message, details, task_id, agent_id, scope=scope)

    def warning(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None, scope: Optional[str] = None):
        self.print(LogLevel.WARNING, message, details, task_id, agent_id, scope=scope)

    def error(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None, scope: Optional[str] = None):
        self.print(LogLevel.ERROR, message, details, task_id, agent_id, scope=scope)

    def debug(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None, scope: Optional[str] = None):
        import os
        if os.environ.get("DELFHOS_DEBUG") == "1":
            self.print(LogLevel.DEBUG, message, details, task_id, agent_id, scope=scope)

    def task(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None, scope: Optional[str] = None):
        self.print(LogLevel.TASK, message, details, task_id, agent_id, scope=scope)

    def system(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None, scope: Optional[str] = None):
        self.print(LogLevel.SYSTEM, message, details, task_id, agent_id, scope=scope)

    def tool(self, message: str, details: Optional[str] = None, task_id: Optional[str] = None, agent_id: Optional[str] = None, scope: Optional[str] = None):
        self.print(LogLevel.TOOL, message, details, task_id, agent_id, scope=scope)

    def section_banner(self, title: str, eyebrow: str = "DELFHOS"):
        """Tight title + hairline rule."""
        with self._lock:
            head = Text()
            head.append("  ")
            head.append(title, style=TEXT_MUTE)
            self.console.print()
            self.console.print(head)
            rule = Text("  ")
            rule.append("─" * 64, style=RULE)
            self.console.print(rule)

    def print_task_box(self, task_message: str):
        """Render the user's task as a brutalist plate (§6, §11)."""
        display_msg = task_message if len(task_message) < 400 else task_message[:397] + "..."

        body = Text()
        body.append("❯ ", style=TEXT_MUTE)
        body.append(display_msg, style=TEXT)

        title = Text("task", style=TEXT_MUTE)

        task_panel = Panel(
            body,
            title=title,
            title_align="left",
            border_style=RULE,
            box=SQUARE,
            expand=False,
            padding=(0, 2),
        )
        with self._lock:
            self.console.print()
            self.console.print(task_panel)
            self.console.print()
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
        """Welcome banner — eyebrow + ASCII logo + key/value rows (§3.3, §6)."""
        tool_list = tools or []
        tool_count = len(tool_list)
        model_str = (llm_config or "not configured").strip()

        # ── Left column: ASCII logo in stark white, no bold ───────────
        logo_text = Text()
        for i, line in enumerate(self._LOGO_LINES):
            if i > 0:
                logo_text.append("\n")
            logo_text.append(line, style=TEXT)

        # ── Right column: name + version chip + key/value table ──────
        header = Text()
        header.append("delfhos", style=TEXT)
        header.append("   ")
        # White-on-black chip echoes the primary pill (§7).
        header.append(f" v{version} ", style=f"{BG} on {TEXT}")

        if tool_count == 0:
            tools_line = "none"
        elif tool_count <= 5:
            tools_line = ", ".join(tool_list)
        else:
            tools_line = ", ".join(tool_list[:5]) + f"  +{tool_count - 5} more"

        info_rows = Table.grid(padding=(0, 2))
        # Eyebrow keys: mono uppercase faint (§3.3).
        info_rows.add_column(style=TEXT_MUTE, no_wrap=True)
        info_rows.add_column(style=TEXT, overflow="fold")
        info_rows.add_row("model", model_str)

        tools_value = Text()
        tools_value.append(f"{tool_count}", style=NUMBER)
        tools_value.append(" connected  ", style=TEXT)
        tools_value.append("·", style=TEXT_FAINT)
        tools_value.append("  ")
        tools_value.append(tools_line, style=TEXT_SUB)
        info_rows.add_row("tools", tools_value)
        if agent_id:
            info_rows.add_row("agent", Text(str(agent_id), style=TEXT_SUB))
        if cwd:
            info_rows.add_row("cwd", Text(str(cwd), style=TEXT_SUB))

        # Vertically center the info block beside the logo.
        # `info_rows.row_count` already accounts for the optional agent/cwd
        # rows; the +2 covers the header line and its trailing blank.
        logo_height = len(self._LOGO_LINES)
        info_height = 2 + info_rows.row_count
        top_pad = max(0, (logo_height - info_height) // 2)
        right_col = Group(
            Text("\n" * (top_pad - 1)) if top_pad > 0 else Text(""),
            header,
            Text(""),
            info_rows,
        )

        side_by_side = Table.grid(padding=(0, 4))
        side_by_side.add_column(no_wrap=True)
        side_by_side.add_column()
        side_by_side.add_row(logo_text, right_col)

        # ── Hairline + slash-command hint bar (§11.6: no bold) ────────
        hint = Text()
        sep = Text("  ·  ", style=TEXT_FAINT)
        for i, cmd in enumerate(("/help", "/clear", "/stop", "/exit")):
            if i:
                hint.append_text(sep)
            hint.append(cmd, style=TEXT)

        body = Group(side_by_side, Text(""), hint)

        title = Text("delfhos", style=TEXT_MUTE)
        banner = Panel(
            body,
            title=title,
            title_align="left",
            border_style=RULE,
            box=SQUARE,
            expand=False,
            padding=(1, 2),
        )

        with self._lock:
            self.console.print()
            self.console.print(banner)
            self.console.print()

    def task_summary(self, task_id: str, duration: float, tokens: dict, status: str, final_message: str = None, computational_time: float = None, wait_time: float = None, agent_id: Optional[str] = None, task_status: str = "success", tools: list = None, llm_config: Optional[str] = None):
        """Compact end-of-task line + optional Result plate (§4, §6, §11)."""
        # Stop spinners first so the live renderer doesn't race with prints.
        self.loading_stop_all()

        is_ok = task_status == "success"
        status_symbol = "✓" if is_ok else "✗"
        # Soft tones for the inline status; saturated tones reserved for borders.
        status_color = SUCCESS_SOFT if is_ok else ERROR_SOFT
        status_word = "done" if is_ok else "failed"

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
        cost_val = tokens.get('total_cost_usd')

        # Compact one-liner:
        #   ✓ done  │  1.23s · 4,210 tok · in/out 3,100/1,110 · $0.00041
        line = Text("  ")
        line.append(f"{status_symbol} ", style=status_color)
        line.append(status_word, style=status_color)
        line.append("   │   ", style=TEXT_FAINT)

        meta_pairs = [
            (f"{duration:.2f}", "s"),
            (f"{tokens_used:,}", " tok"),
        ]
        for i, (num, unit) in enumerate(meta_pairs):
            if i:
                line.append("  ·  ", style=TEXT_FAINT)
            line.append(num, style=NUMBER)
            line.append(unit, style=TEXT_MUTE)

        line.append("  ·  ", style=TEXT_FAINT)
        line.append("in/out ", style=TEXT_MUTE)
        line.append(f"{input_t:,}", style=NUMBER)
        line.append("/", style=OPERATOR)
        line.append(f"{output_t:,}", style=NUMBER)

        if cost_val is not None:
            line.append("  ·  ", style=TEXT_FAINT)
            line.append("$", style=TEXT_MUTE)
            line.append(f"{float(cost_val):.4f}", style=NUMBER)

        self.console.print(line)

        # Verbose breakdown — keys mute, values typed.
        if self.verbose:
            detail = Text("      ")
            parts = [
                ("tokens=", f"{tokens_used:,}"),
                ("in=",     f"{input_t:,}"),
                ("out=",    f"{output_t:,}"),
            ]
            if cost_val is not None:
                parts.append(("cost=$", f"{float(cost_val):.6f}"))
            for i, (k, v) in enumerate(parts):
                if i:
                    detail.append("  ·  ", style=TEXT_FAINT)
                detail.append(k, style=TEXT_MUTE)
                detail.append(v, style=NUMBER)
            self.console.print(detail)

            if wait_time and wait_time > 0 and computational_time:
                t = Text("      ")
                t.append("compute=", style=TEXT_MUTE)
                t.append(f"{computational_time:.2f}s", style=NUMBER)
                t.append("  ·  ", style=TEXT_FAINT)
                t.append("wait=", style=TEXT_MUTE)
                t.append(f"{wait_time:.2f}s", style=NUMBER)
                self.console.print(t)

            if llm_config:
                t = Text("      ")
                t.append("llm=", style=TEXT_MUTE)
                t.append(str(llm_config), style=STRING)
                self.console.print(t)

            if tools:
                user_tools = [t for t in tools if t != "llm_code_generation"]
                if user_tools:
                    t = Text("      ")
                    t.append("tools=", style=TEXT_MUTE)
                    t.append(", ".join(user_tools), style=STRING)
                    self.console.print(t)

        self.console.print()

        # Result plate — brutalist, hairline border tinted by outcome.
        if final_message:
            rich_result = convert_markdown_links_to_rich(final_message)
            markdown_content = Markdown(rich_result, style=TEXT)
            border_color = SUCCESS_SOFT if is_ok else ERROR_SOFT
            title = Text("result", style=border_color)
            result_panel = Panel(
                markdown_content,
                title=title,
                title_align="left",
                border_style=border_color,
                box=SQUARE,
                expand=False,
                padding=(0, 2),
            )
            self.console.push_theme(_MARKDOWN_THEME)
            self.console.print(result_panel)
            self.console.pop_theme()

    def print_exception(self, exc: Exception, title: str = "Task failed"):
        """Render a caught exception as a brutalist error plate."""
        from rich.traceback import Traceback

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

        header = Text()
        header.append("✗ ", style=ERROR_SOFT)
        header.append(f"Delfhos encountered an error during: ", style=TEXT_MUTE)
        header.append(title, style=TEXT)

        message_line = Text()
        message_line.append("message  ", style=TEXT_MUTE)
        message_line.append(message, style=TEXT)

        hint_line = Text()
        hint_line.append("hint     ", style=TEXT_MUTE)
        hint_line.append(hint, style=WARNING)

        group = Group(header, Text(""), tb, Text(""), message_line, hint_line)

        title_text = Text()
        title_text.append("error", style=ERROR_SOFT)
        if code:
            title_text.append(f"  {code}", style=TEXT_MUTE)

        panel = Panel(
            group,
            title=title_text,
            title_align="left",
            border_style=ERROR_SOFT,
            box=SQUARE,
            expand=False,
            padding=(0, 2),
        )
        self.console.print(panel)


def _delfhos_excepthook(exc_type, exc_val, tb_obj):
    """Custom exception hook to print a brutalist error plate."""
    from rich.traceback import Traceback

    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_val, tb_obj)
        return

    tb = Traceback.from_exception(exc_type, exc_val, tb_obj, show_locals=False)
    code, message, hint = extract_error_payload(exc_val)

    header = Text()
    header.append("✗ ", style=ERROR_SOFT)
    header.append("Delfhos encountered an error", style=TEXT)

    message_line = Text()
    message_line.append("message  ", style=TEXT_MUTE)
    message_line.append(message, style=TEXT)

    hint_line = Text()
    hint_line.append("hint     ", style=TEXT_MUTE)
    hint_line.append(hint, style=WARNING)

    group = Group(header, Text(""), tb, Text(""), message_line, hint_line)

    title_text = Text()
    title_text.append("error", style=ERROR_SOFT)
    if code:
        title_text.append(f"  {code}", style=TEXT_MUTE)

    panel = Panel(
        group,
        title=title_text,
        title_align="left",
        border_style=ERROR_SOFT,
        box=SQUARE,
        expand=False,
        padding=(0, 2),
    )

    try:
        console.stop_all()
    except Exception:
        pass

    console.console.print(panel)


# Override the global exception hook
sys.excepthook = _delfhos_excepthook

console = ProfessionalConsole()
