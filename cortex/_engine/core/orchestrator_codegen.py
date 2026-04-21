"""
OrchestratorCodegenMixin

LLM-based prefiltering, connection filtering, SQL-schema fetching, and
Python code generation.  Intended to be mixed into the Orchestrator class.
"""

from typing import Any, Dict, List, Optional
import asyncio
import os
import time
from datetime import datetime, timezone

from ..utils.console import console
from ..utils.llm_utils import normalize_llm_result
from ..internal.llm import llm_completion_async
from delfhos.errors import (
    CodeGenerationError,
    LLMExecutionError,
    PrefilterError,
    SQLSchemaError,
)
from ..tools.tool_registry import (
    build_prefilter_prompt,
    build_filtered_api_docs,
    get_available_actions_for_connections,
    parse_prefilter_response,
    filter_selected_actions,
    build_connection_context_for_prompt,
)
from ..trace import PrefilterTrace, CodeGenTrace
from .python_executor import parse_python_code


class OrchestratorCodegenMixin:
    """Mixin that adds prefiltering and Python code-generation to the Orchestrator."""

    PREFILTER_MEMORY_MAX_CHARS = 1200
    PREFILTER_MEMORY_MAX_LINES = 20

    # ------------------------------------------------------------------ #
    #  Connection-filter helpers                                           #
    # ------------------------------------------------------------------ #

    def _normalize_connection_filter_response(self, response: str) -> str:
        return (
            (response or "")
            .strip()
            .upper()
            .replace("OUTPUT:", "")
            .replace("CONNECTIONS:", "")
            .replace("SELECTED:", "")
            .strip()
        )

    def _compact_prefilter_memory_context(self, memory_context: Optional[str]) -> str:
        """Trim memory context for prefilter to reduce token usage."""
        if not memory_context or not isinstance(memory_context, str):
            return ""
        lines = [l.strip() for l in memory_context.splitlines() if l.strip()]
        if len(lines) > self.PREFILTER_MEMORY_MAX_LINES:
            lines = lines[: self.PREFILTER_MEMORY_MAX_LINES]
        compact = "\n".join(lines)
        if len(compact) > self.PREFILTER_MEMORY_MAX_CHARS:
            compact = compact[: self.PREFILTER_MEMORY_MAX_CHARS].rstrip() + "\n... [truncated]"
        return compact

    def _extract_selected_connection_indices(
        self, response_clean: str, total_connections: int
    ) -> list:
        parts = [p.strip() for p in response_clean.split(",")]
        selected_indices = []
        for part in parts:
            digits = "".join(c for c in part if c.isdigit())
            if digits:
                idx = int(digits)
                if 1 <= idx <= total_connections:
                    selected_indices.append(idx)
        return selected_indices

    def _parse_connection_filter_selection(
        self, response: str, connections: list, task_id: str = ""
    ) -> list:
        response_clean = self._normalize_connection_filter_response(response)
        if response_clean == "NONE" or not response_clean:
            console.debug(
                "Connection filtering: No relevant connections", "", task_id=task_id, agent_id=self.agent_id
            )
            return []
        try:
            selected_indices = self._extract_selected_connection_indices(
                response_clean, len(connections)
            )
            if not selected_indices:
                console.warning(
                    "Connection filtering: No valid connection numbers found in response",
                    f"Response was: {response_clean}, using all connections",
                    task_id=task_id,
                    agent_id=self.agent_id,
                )
                return []
            selected_connections = [connections[i - 1] for i in selected_indices]
            selected_names = [
                c.connection_name if hasattr(c, "connection_name") else "Connection"
                for c in selected_connections
            ]
            console.debug(
                "Connection filtering completed",
                f"Selected {len(selected_connections)} connections: {', '.join(selected_names)}",
                task_id=task_id,
                agent_id=self.agent_id,
            )
            return selected_connections
        except (IndexError, ValueError, TypeError) as parse_error:
            console.warning(
                "Failed to parse connection filtering response",
                f"Response: {response_clean}, Error: {parse_error}, using all connections",
                task_id=task_id,
                agent_id=self.agent_id,
            )
            return []

    # ------------------------------------------------------------------ #
    #  LLM connection filter (legacy / standalone path)                   #
    # ------------------------------------------------------------------ #

    async def llm_filter_connections(self, message: str, task_id: str = "") -> list:
        """Filter connections based on task description using LLM."""
        await self.track_tool_timing_async(
            task_id, "llm_connection_filtering", None, self.prefilter_llm,
            description=self._ui_text("analyzing_connections"), is_starting=True,
        )
        llm_start_time = time.time()
        connections = list(self.tools.connections.values())

        if not connections:
            llm_duration = time.time() - llm_start_time
            await self.track_tool_timing_async(
                task_id, "llm_connection_filtering", llm_duration, self.prefilter_llm,
                description=self._ui_text("analyzing_connections"), is_starting=False,
            )
            return []

        if len(connections) < 3:
            console.debug(
                "Connection filtering skipped",
                f"Only {len(connections)} connections available",
                task_id=task_id, agent_id=self.agent_id,
            )
            llm_duration = time.time() - llm_start_time
            await self.track_tool_timing_async(
                task_id, "llm_connection_filtering", llm_duration, self.prefilter_llm,
                description="Skipped filtering (low count)", is_starting=False,
            )
            return connections

        connection_list = []
        for idx, conn in enumerate(connections, 1):
            conn_name = getattr(conn, "connection_name", f"Connection {idx}")
            conn_tool = getattr(conn, "tool_name", "unknown")
            conn_desc = (
                conn.metadata.get("description", "") if hasattr(conn, "metadata") else ""
            ) or getattr(conn, "description", "")
            connection_list.append(
                f"{idx}. {conn_name} ({conn_tool}): {conn_desc or 'No description'}"
            )
        connections_text = "\n".join(connection_list)

        prompt = f"""You are a connection filter. Analyze the task and select ONLY the connections needed.

Task: {message}

Available Connections:
{connections_text}

Guidelines:
- Read/search emails → need gmail connection
- Create Google Sheets (spreadsheet) → need sheets connection
- Create Google Docs (document) → need docs connection
- Create Excel/CSV files (local files) → need files connection
- Upload files to Drive → need drive connection
- Database queries → need sql connection
- Search web → need websearch connection...

IMPORTANT:
- "Use excel" usually means Google Sheets (use sheets), NOT local Excel file (files)
- Only use drive if task explicitly mentions uploading to Drive or searching Drive
- Only use files if task explicitly mentions saving local files (Excel/CSV files on disk)

CRITICAL: Output ONLY comma-separated numbers (e.g., "1" or "1,2"). Do NOT output "ALL", "all", connection names, or any text. If no connections match, output "NONE".

Examples:
Task: "Read emails from contacto@civislend.com and create Excel file"
Connections:
1. Gmail (gmail): Email access
2. Sheets (sheets): Google Spreadsheets
3. Files (files): Local file operations
Output: 1,2

Task: "Read emails and create a spreadsheet with the data"
Connections:
1. Gmail (gmail): Email
2. Sheets (sheets): Spreadsheets
Output: 1,2

Task: "Give me top 10 expensive tasks from database"
Connections:
1. Gmail (gmail): Email
2. Sales DB (sql): Database
Output: 2

Now analyze the task and output ONLY the connection numbers (comma-separated) or "NONE":"""

        try:
            llm_result = await llm_completion_async(
                model=self.prefilter_llm, prompt=prompt, temperature=0.0, max_tokens=50
            )
            llm_duration = time.time() - llm_start_time
            await self.track_tool_timing_async(
                task_id, "llm_connection_filtering", llm_duration, self.prefilter_llm,
                description=self._ui_text("analyzing_connections"), is_starting=False,
            )
            response, norm_token_info = normalize_llm_result(llm_result)
            self._safe_add_tokens(
                task_id, norm_token_info, self.prefilter_llm, "llm_connection_filtering",
                duration=llm_duration,
            )
            console.debug(
                "Connection filtering LLM response",
                f"Raw response: {response}",
                task_id=task_id, agent_id=self.agent_id,
            )
            return self._parse_connection_filter_selection(response, connections, task_id=task_id)
        except (LLMExecutionError, RuntimeError, OSError) as e:
            llm_duration = time.time() - llm_start_time
            await self.track_tool_timing_async(
                task_id, "llm_connection_filtering", llm_duration, self.light_llm,
                description=self._ui_text("analyzing_connections"), is_starting=False,
            )
            console.error(
                "Connection filtering failed",
                f"{type(e).__name__}: {str(e)}",
                task_id=task_id, agent_id=self.agent_id,
            )
            return []

    # ------------------------------------------------------------------ #
    #  SQL schema helpers                                                  #
    # ------------------------------------------------------------------ #

    async def _fetch_sql_schema(self, task_id: str) -> Optional[str]:
        """Fetch SQL schema for all active SQL connections (with per-connection caching)."""
        schema_start = time.time()
        sql_conns = [
            conn
            for conn in self.tools.connections.values()
            if getattr(conn, "tool_name", "").lower() == "sql" and conn.is_active()
        ]
        if not sql_conns:
            return None

        schema_parts = []
        for sql_conn in sql_conns:
            conn_name = sql_conn.connection_name
            current_time = time.time()
            cache_key = f"sql_schema_{conn_name}"

            if not hasattr(self, "_sql_schema_cache_map"):
                self._sql_schema_cache_map: Dict[str, str] = {}
                self._sql_schema_time_map: Dict[str, float] = {}

            cached = self._sql_schema_cache_map.get(cache_key)
            cached_time = self._sql_schema_time_map.get(cache_key, 0)

            if cached and (current_time - cached_time < self.SQL_SCHEMA_CACHE_TTL):
                schema_text = cached
                console.debug(
                    "SQL schema used from cache",
                    f"connection={conn_name}",
                    task_id=task_id, agent_id=self.agent_id,
                )
            else:
                schema_result = await self.tools.execute_tool(
                    sql_conn.connection_name,
                    context={"action": "SCHEMA", "params": {}},
                    task_id=task_id,
                    light_llm=self.light_llm,
                    heavy_llm=self.heavy_llm,
                    agent_id=self.agent_id,
                    validation_mode=False,
                )
                if isinstance(schema_result, dict) and "schema" in schema_result:
                    schema_text = str(schema_result.get("schema") or "")
                else:
                    schema_text = str(schema_result or "")
                self._sql_schema_cache_map[cache_key] = schema_text
                self._sql_schema_time_map[cache_key] = current_time

            if schema_text:
                if len(sql_conns) > 1:
                    schema_parts.append(f'--- Connection: "{conn_name}" ---\n{schema_text}')
                else:
                    schema_parts.append(schema_text)

        return "\n\n".join(schema_parts) if schema_parts else None

    # ------------------------------------------------------------------ #
    #  Prefilter (enabled path)                                           #
    # ------------------------------------------------------------------ #

    async def _run_prefilter(
        self,
        message: str,
        task_id: str,
        memory_context: Optional[str],
        connections: list,
        available_actions: dict,
        schema_task: Optional[asyncio.Task],
    ):
        """Run the LLM prefilter. Returns (selected_actions, connection_map, python_api_docs, schema_task)."""
        prefilter_task_text = message
        if memory_context:
            compact = self._compact_prefilter_memory_context(memory_context)
            if compact:
                prefilter_task_text = f"{message}\n\n[Relevant memory facts]\n{compact}"

        prefilter_prompt = build_prefilter_prompt(
            prefilter_task_text, available_actions,
            connections=connections, custom_descriptions=self.tool_descriptions,
        )

        await self.track_tool_timing_async(
            task_id, "prefilter", None, self.prefilter_llm,
            description=self._ui_text("analyzing_connections"), is_starting=True,
        )

        prefilter_start = time.time()
        prefilter_result = await llm_completion_async(
            model=self.prefilter_llm,
            prompt=prefilter_prompt,
            temperature=0.0,
            max_tokens=1000,
        )
        prefilter_duration = time.time() - prefilter_start

        prefilter_response, prefilter_tokens = normalize_llm_result(prefilter_result)

        # ── Direct-answer shortcut ─────────────────────────────────────────
        if prefilter_response.strip().upper().startswith("ANSWER:"):
            answer_text = prefilter_response.strip()[7:].strip()
            if schema_task and not schema_task.done():
                schema_task.cancel()
            await self.track_tool_timing_async(
                task_id, "prefilter", prefilter_duration, self.prefilter_llm,
                description="Direct answer (no tools needed)", is_starting=False,
                metadata={"direct_answer": True},
            )
            self._safe_add_tokens(
                task_id, prefilter_tokens, self.prefilter_llm, "prefilter",
                duration=prefilter_duration,
            )
            console.debug(
                "Prefilter direct answer",
                f"Answered directly without code generation ({prefilter_duration*1000:.0f}ms)",
                task_id=task_id, agent_id=self.agent_id,
            )
            escaped = answer_text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
            return f'print("""{escaped}""")', {}, None, schema_task  # type: ignore[return-value]

        selected_actions, connection_map = parse_prefilter_response(
            prefilter_response, connections
        )

        selected_actions, blocked_actions = filter_selected_actions(
            selected_actions, available_actions
        )
        if blocked_actions:
            console.warning(
                "Prefilter proposed disallowed actions",
                f"Blocked: {', '.join(sorted(blocked_actions))}",
                task_id=task_id, agent_id=self.agent_id,
            )

        # ── Verbose actions table ──────────────────────────────────────────
        if self.verbose == "high":
            self._print_verbose_actions_table(
                available_actions, selected_actions, task_id=task_id
            )

        # ── Update trace ───────────────────────────────────────────────────
        if self.current_trace:
            pf_end_dt = datetime.now()
            pf_start_dt = datetime.fromtimestamp(prefilter_start)
            base_selected = {a.split(":")[0] for a in selected_actions}
            tools_rej = [a for a in available_actions if a not in base_selected]
            self.current_trace.prefilter = PrefilterTrace(
                started_at=pf_start_dt,
                duration_ms=int(prefilter_duration * 1000),
                model_used=self.prefilter_llm,
                tools_available=len(available_actions),
                tools_selected=list(base_selected),
                tools_rejected=tools_rej,
                tokens_input=prefilter_tokens.get(
                    "input_tokens", prefilter_tokens.get("prompt_tokens", 0)
                ),
                tokens_output=prefilter_tokens.get(
                    "output_tokens", prefilter_tokens.get("completion_tokens", 0)
                ),
                ran_parallel_with="sql_schema_fetch" if schema_task else None,
            )
            self.current_trace.add_event(
                "prefilter_complete", f"{len(selected_actions)} tools selected", t=pf_end_dt
            )

        await self.track_tool_timing_async(
            task_id, "prefilter", prefilter_duration, self.prefilter_llm,
            description=self._ui_text("analyzing_connections"), is_starting=False,
            metadata={"selected_tools": selected_actions, "connection_map": connection_map},
        )
        self._safe_add_tokens(
            task_id, prefilter_tokens, self.prefilter_llm, "prefilter",
            duration=prefilter_duration,
        )

        selected_tools = {a.split(":")[0] if ":" in a else a for a in selected_actions}
        tool_label = "tool" if len(selected_tools) == 1 else "tools"
        console.info(
            "Prefiltering", f"— {len(selected_tools)} {tool_label} selected",
            task_id=task_id, agent_id=self.agent_id,
        )

        python_api_docs = build_filtered_api_docs(
            selected_actions, custom_descriptions=self.tool_descriptions
        )
        return selected_actions, connection_map, python_api_docs, schema_task

    def _print_verbose_actions_table(
        self, available_actions: dict, selected_actions: list, task_id: str = ""
    ):
        """Print the available/selected actions table in verbose mode."""
        from rich.panel import Panel
        from rich.table import Table
        from collections import defaultdict

        actions_by_tool: Dict[str, list] = defaultdict(list)
        if isinstance(available_actions, dict):
            for tool, acts_set in available_actions.items():
                for act in acts_set:
                    if act not in actions_by_tool[tool]:
                        actions_by_tool[tool].append(act)
        else:
            for action in available_actions:
                parts = action.split(":")
                tool = parts[0] if parts else "unknown"
                act = ":".join(parts[1:]) if len(parts) > 1 else tool
                if act not in actions_by_tool[tool]:
                    actions_by_tool[tool].append(act)

        if self.memory:
            actions_by_tool["memory"] = ["save"]

        internal_tool_names = {
            "files", "llm", "lzmafilter", "sql", "gmail", "sheets",
            "drive", "calendar", "docs", "websearch", "memory",
        }

        actions_table = Table(
            title="Available Actions for Agent", show_header=True, header_style="bold cyan"
        )
        actions_table.add_column("Tool", style="cyan", width=20)
        actions_table.add_column("Actions", style="green")
        actions_table.add_column("Type", style="dim yellow", width=12)

        def _is_selected(tool_name: str) -> bool:
            return any(
                a.startswith(tool_name + ":") or a == tool_name or a == f"[{tool_name}]"
                for a in selected_actions
            )

        user_tools_added = False
        for tool_name in sorted(actions_by_tool.keys()):
            if tool_name in internal_tool_names:
                continue
            if not user_tools_added:
                user_tools_added = True
            acts_str = ", ".join(sorted(actions_by_tool[tool_name]))
            style = "bold green" if _is_selected(tool_name) else "dim"
            actions_table.add_row(
                f"[{style}]{tool_name}[/{style}]",
                f"[{style}]{acts_str}[/{style}]",
                "[bold magenta]User[/bold magenta]",
            )

        if user_tools_added:
            actions_table.add_row("[dim]─[/dim]", "[dim]─[/dim]", "[dim]─[/dim]")

        for tool_name in sorted(actions_by_tool.keys()):
            if tool_name not in internal_tool_names:
                continue
            acts_str = ", ".join(sorted(actions_by_tool[tool_name]))
            style = "bold green" if _is_selected(tool_name) else "dim"
            actions_table.add_row(
                f"[{style}]{tool_name}[/{style}]",
                f"[{style}]{acts_str}[/{style}]",
                "[dim white]Internal[/dim white]",
            )

        actions_table.caption = (
            "[bold]Legend:[/bold] "
            "[bold magenta]User[/bold magenta] = Tools you provided (Native, APITool, Custom Tools) | "
            "[dim white]Internal[/dim white] = Sandbox-only tools (files, llm)"
        )
        console.console.print(Panel(actions_table, border_style="cyan", expand=False))
        console.console.print()

    # ------------------------------------------------------------------ #
    #  Main entry: Python code generation                                  #
    # ------------------------------------------------------------------ #

    async def llm_generate_python(
        self,
        message: str,
        task_id: str = "",
        sql_schema: str = None,
        relevant_connections: list = None,
        memory_context: str = None,
    ) -> str:
        """Generate Python code to accomplish *message*. Returns executable code string."""
        connections = (
            relevant_connections
            if relevant_connections is not None
            else list(self.tools.connections.values())
        )
        available_actions = get_available_actions_for_connections(
            connections, custom_tools=self.tools.tools
        )
        has_sql_connections = "sql" in self.tools.tools
        schema_task: Optional[asyncio.Task] = None

        if has_sql_connections:
            schema_task = asyncio.create_task(self._fetch_sql_schema(task_id))

        # ── Prefilter (optional) ───────────────────────────────────────────
        if not self.enable_prefilter:
            all_actions = [
                f"{tool_name}:{action}"
                for tool_name, actions in available_actions.items()
                for action in actions
            ]
            selected_actions = all_actions
            connection_map: Dict[str, list] = {}
            for conn in (relevant_connections or list(self.tools.connections.values())):
                tool_name = getattr(conn, "tool_name", "").lower()
                if tool_name:
                    connection_map.setdefault(tool_name, []).append(
                        getattr(conn, "connection_name", "")
                    )
            python_api_docs = build_filtered_api_docs(
                all_actions, custom_descriptions=self.tool_descriptions
            )
            console.info(
                "Code generation",
                "Starting (prefilter disabled - using all tools)",
                task_id=task_id, agent_id=self.agent_id,
            )
        else:
            result = await self._run_prefilter(
                message, task_id, memory_context, connections,
                available_actions, schema_task,
            )
            # Direct-answer shortcut: _run_prefilter returns code string directly
            if isinstance(result[0], str) and result[2] is None:
                return result[0]
            selected_actions, connection_map, python_api_docs, schema_task = result

        # ── Await SQL schema ───────────────────────────────────────────────
        needs_sql = any(a.lower().startswith("sql:") for a in selected_actions)
        sql_schema_section = ""

        if needs_sql and schema_task:
            try:
                await self.track_tool_timing_async(
                    task_id, "sql_schema", None, None,
                    description=self._ui_text("fetching_schema"), is_starting=True,
                )
                schema_wait_start = time.time()
                sql_schema = await schema_task
                schema_wait_duration = time.time() - schema_wait_start
                if sql_schema:
                    self._sql_schema_cache = sql_schema
                    self._sql_schema_last_fetch = time.time()
                await self.track_tool_timing_async(
                    task_id, "sql_schema", schema_wait_duration, None,
                    description=self._ui_text("fetching_schema"), is_starting=False,
                )
                console.debug(
                    "SQL schema ready",
                    f"({schema_wait_duration*1000:.0f}ms wait after prefilter)",
                    task_id=task_id, agent_id=self.agent_id,
                )
            except (OSError, RuntimeError, ValueError, asyncio.CancelledError) as e:
                console.error(
                    "SQL schema introspection failed",
                    f"SQLSchemaError: {e}",
                    task_id=task_id, agent_id=self.agent_id,
                )
                sql_schema = None
        else:
            if schema_task and not schema_task.done():
                schema_task.cancel()
            sql_schema = None

        if sql_schema:
            sql_schema_section = (
                f"\n\n**DATABASE SCHEMA** (YAML format `table: col(type)`. "
                f"Use ONLY these exact table/column names):\n{sql_schema}"
            )

        # ── Build prompt ───────────────────────────────────────────────────
        agent_context_section = (
            f"\n\nContext:\n{self.system_prompt}" if self.system_prompt else ""
        )

        workspace_files_section = ""
        workspace_files = getattr(self, "workspace_files", [])
        if workspace_files:
            sandbox_mode = getattr(self, "sandbox_mode", "auto")
            if sandbox_mode == "local":
                file_paths = workspace_files
            else:
                file_paths = [f"/workspace/{os.path.basename(p)}" for p in workspace_files]
            files_list = "\n".join(f"- {p}" for p in file_paths)
            workspace_files_section = f"\n\nWorkspace Files (read-only, use these exact paths):\n{files_list}"
        memory_context_section = (
            f"\n\nLong-term Memory (relevant facts):\n{memory_context}" if memory_context else ""
        )
        connection_context_section = build_connection_context_for_prompt(
            connection_map, connections
        )
        current_date_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")

        examples_section = ""  # Examples are included in compressed API docs

        memory_tool_section = ""
        if self.memory:
            guidelines = (getattr(self.memory, "guidelines", "") or "").strip() or (
                "Store stable user preferences, durable facts, and final decisions."
            )
            memory_tool_section = (
                "\n\nMEMORY:\n"
                f"- `await memory.save(\"fact\", desc=\"why\")` (Markdown. Atomic facts.)\n"
                f"- Follow: {guidelines}"
            )

        python_prompt = (
            f'Task: "{message}"{sql_schema_section}{connection_context_section}'
            f"{agent_context_section}{workspace_files_section}{memory_context_section}\n"
            f"Date: {current_date_str}\n\n"
            "BEFORE CODING: If task is vague (missing names/dates/files), output ONLY a print() asking clarification. "
            'E.g.: `print("Need keywords to find invoice")`\n\n'
            f"{python_api_docs}{memory_tool_section}\n\n"
            "RULES:\n"
            "- ONLY Python code. Minimal code. Async (await). NO asyncio.run(); define `async def main():...` & `await main()`.\n"
            "- Use ONLY the namespaces shown above. Do NOT invent variable names. NEVER pass connection_name (auto-detected).\n"
            '- EVERY tool call MUST include `desc="<specific action>"` (e.g. `desc="Searching AI news April 2026"`). SELF-CHECK: if any call is missing `desc=`, rewrite before returning.\n'
            "- `files` tool ONLY reads Sandbox uploads.\n"
            "- Only print() is visible. Print final answers in Markdown, use `format_table()`. Match user language.\n"
            "- Wait for tool output before generating text that depends on it.\n"
            "- Processing N items: ALWAYS `asyncio.gather(*[process(x) for x in items])`, NEVER sequential `for` loops with `await`.\n"
            "- Libs: asyncio, json, re, datetime, time, math, statistics. NO pandas.\n"
            "- APITool responses are dict/list/str. If str, parse with `json.loads(result)` before using as dict/list.\n"
            '- WEBSEARCH: ask "Return ONLY JSON: {k:v}" → `safe_json_loads(response)` (None if invalid → print raw, abort). NEVER hardcode facts.\n'
            "- Large data → `llm.call`: pre-process with Python first (filter/slice/summarise). Never pass raw bulks.\n"
            "- To return files/datasets/large text to the user: call `add_to_output_files(name, content)` (name=logical label, content=str/bytes/dict/list). The file is saved and accessible via Response.files after the task.\n"
            f"{examples_section}\n\n"
            "OUTPUT: Python code ONLY. NO comments. Only print() is visible, use markdown."
        )

        # ── Call LLM ───────────────────────────────────────────────────────
        try:
            await self.track_tool_timing_async(
                task_id, "llm_code_generation", None, self.code_generation_llm,
                description=self._ui_text("planning"), is_starting=True,
            )
            llm_start_time = time.time()
            llm_result = await llm_completion_async(
                model=self.code_generation_llm,
                prompt=python_prompt,
                temperature=0.0,
                max_tokens=4000,
                response_format=None,
            )
            llm_duration = time.time() - llm_start_time

            await self.track_tool_timing_async(
                task_id, "llm_code_generation", llm_duration, self.code_generation_llm,
                description=self._ui_text("planning"), is_starting=False,
            )
            self.track_tool_usage(task_id, "llm_code_generation", self.code_generation_llm)

            response, norm_token_info = normalize_llm_result(llm_result)
            try:
                self._add_tokens(
                    task_id, norm_token_info, self.code_generation_llm,
                    "llm_code_generation", duration=llm_duration,
                )
            except (AttributeError, TypeError, KeyError):
                pass  # best-effort token accounting

            console.debug(
                "LLM Python generation",
                f"Generated {len(response)} chars",
                task_id=task_id, agent_id=self.agent_id,
            )

            python_code = parse_python_code(response)

            if not python_code or not python_code.strip():
                console.error(
                    "No valid Python code extracted",
                    "LLM response did not contain executable code",
                    task_id=task_id, agent_id=self.agent_id,
                )
                return ""

            # ── Update trace ───────────────────────────────────────────────
            if self.current_trace:
                cg_end_dt = datetime.now()
                cg_start_dt = datetime.fromtimestamp(llm_start_time)
                if not self.current_trace.code_generation:
                    self.current_trace.code_generation = CodeGenTrace(
                        started_at=cg_start_dt,
                        duration_ms=int(llm_duration * 1000),
                        model_used=self.code_generation_llm,
                        system_prompt=python_prompt if self.trace_mode == "full" else "...",
                        code_generated=python_code,
                        tokens_input=norm_token_info.get("input_tokens", 0),
                        tokens_output=norm_token_info.get("output_tokens", 0),
                        attempt=1,
                    )
                    self.current_trace.add_event(
                        "codegen_complete",
                        f"{self.current_trace.code_generation.tokens_output} tokens generated",
                        t=cg_end_dt,
                    )
                else:
                    self.current_trace.code_generation.attempt += 1

            # ── Basic scope-error detection ────────────────────────────────
            self._warn_on_scope_errors(python_code, task_id=task_id)

            console.debug(
                "Python code extracted",
                f"Ready to execute ({len(python_code)} chars)",
                task_id=task_id, agent_id=self.agent_id,
            )
            return python_code.strip()

        except (LLMExecutionError, RuntimeError, ValueError, OSError) as e:
            import traceback
            error_trace = traceback.format_exc()
            console.error(
                "Python code generation failed",
                f"{type(e).__name__}: {str(e)}\n\nTraceback:\n{error_trace}",
                task_id=task_id, agent_id=self.agent_id,
            )
            raise CodeGenerationError(detail=str(e)) from e

    # ------------------------------------------------------------------ #
    #  Utilities                                                           #
    # ------------------------------------------------------------------ #

    def _warn_on_scope_errors(self, python_code: str, task_id: str = ""):
        """Heuristic check for loop-variable usage outside the loop."""
        lines = python_code.split("\n")
        common_loop_vars = ["email", "file_path", "attachment", "row", "item", "data"]
        for var_name in common_loop_vars:
            in_loop = False
            loop_start = None
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if f"for {var_name} in" in stripped:
                    in_loop = True
                    loop_start = i + 1
                elif in_loop:
                    current_indent = len(line) - len(line.lstrip())
                    prev_indent = (
                        len(lines[i - 1]) - len(lines[i - 1].lstrip()) if i > 0 else 0
                    )
                    if current_indent < prev_indent and current_indent <= 2:
                        in_loop = False
                if not in_loop and loop_start and any(
                    f"{var_name}{c}" in stripped for c in ("[", ".", ",", ")")
                ):
                    console.warning(
                        "Potential scope error detected",
                        f"Line {i+1}: '{stripped[:80]}' uses '{var_name}' outside loop "
                        f"context (loop started at line {loop_start}). This may cause NameError.",
                        task_id=task_id, agent_id=self.agent_id,
                    )
