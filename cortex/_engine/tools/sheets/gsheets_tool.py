from __future__ import annotations

import ast
import json
import re
import sys
import os
from typing import Any, Dict
from typing import List, Optional, Sequence, Tuple
from delfhos.errors import ConnectionConfigurationError, ToolDefinitionError, ToolExecutionError

from ...utils.console import console
from .gsheets_client import (
    GoogleSheetsClient,
    GoogleSheetsError,
    a1_to_grid_range,
    normalize_sheet_title,
    parse_a1_token,
    split_sheet_and_range,
)

# Try to import API manager for automatic API enabling
_api_manager = None
_has_api_manager = False
try:
    # Try to find api module (could be in parent directory)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # From cortex/_engine/tools/ -> go up 3 levels to project root
    project_root = os.path.abspath(os.path.join(current_dir, '../../..'))
    api_path = os.path.join(project_root, 'api')
    if os.path.exists(api_path):
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from api.utils.google_api_manager import get_api_manager
        _has_api_manager = True
except (ImportError, Exception):
    _has_api_manager = False


COLOR_MAP = {
    "blue": {"red": 0.11, "green": 0.53, "blue": 0.98},
    "lightblue": {"red": 0.68, "green": 0.85, "blue": 0.90},  # Light blue color
    "indigo": {"red": 0.38, "green": 0.31, "blue": 0.86},
    "red": {"red": 0.91, "green": 0.34, "blue": 0.22},
    "green": {"red": 0.18, "green": 0.63, "blue": 0.38},
    "teal": {"red": 0.0, "green": 0.58, "blue": 0.54},
    "yellow": {"red": 0.99, "green": 0.84, "blue": 0.0},
    "orange": {"red": 0.98, "green": 0.60, "blue": 0.08},
    "purple": {"red": 0.60, "green": 0.35, "blue": 0.71},
    "gray": {"red": 0.6, "green": 0.6, "blue": 0.6},
    "black": {"red": 0, "green": 0, "blue": 0},
    "white": {"red": 1, "green": 1, "blue": 1},
}


class SheetOpsInterpreter:
    """Executes the compact SheetOps DSL defined for the sheets tool."""

    def __init__(
        self,
        client: GoogleSheetsClient,
        spreadsheet_id: str,
        variables: Optional[Dict[str, Any]] = None,
        *,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        default_sheet: Optional[str] = None,
    ):
        self.client = client
        self.spreadsheet_id = spreadsheet_id
        self.variables = variables or {}
        self.task_id = task_id
        self.agent_id = agent_id
        self.operations_log: List[str] = []
        self.current_sheet: Optional[str] = None
        self.current_sheet_id: Optional[int] = None
        # Batching: collect operations instead of executing immediately
        self.pending_batch_requests: List[Dict[str, Any]] = []
        self.pending_value_updates: List[Dict[str, Any]] = []  # For write operations
        self.pending_appends: List[Dict[str, Any]] = []  # For append operations
        self.pending_clears: List[str] = []  # For clear operations
        if default_sheet:
            self._set_sheet(default_sheet)

    def run(self, ops: Sequence[Any]) -> Dict[str, Any]:
        if not ops:
            raise ToolExecutionError(tool_name="gsheets", detail="Google Sheets BATCH requires at least one operation in 'ops'.")

        # First pass: collect all operations
        for raw_op in ops:
            op = str(raw_op or "").strip()
            if not op:
                continue
            if op.startswith("@"):
                sheet_name = self._strip_quotes(op[1:].strip())
                if not sheet_name:
                    raise ToolExecutionError(tool_name="gsheets", detail="Sheet context '@SheetName' cannot be empty.")
                self._set_sheet(sheet_name)
                continue
            self._ensure_sheet_context()
            summary = self._execute_command(op)
            if summary:
                self.operations_log.append(summary)

        # Execute all batched operations at the end
        self._execute_batched_operations()

        return {
            "operations": self.operations_log,
            "active_sheet": self.current_sheet,
        }

    def _execute_command(self, op: str) -> str:
        command, args = self._parse_command(op)
        
        # Check if the command looks like JSON (starts with { or contains JSON-like structure)
        if command.startswith("{") or command.startswith("'{"):
            raise ToolDefinitionError(
                f"Invalid SheetOps format: '{op}' appears to be JSON. "
                f"SheetOps requires plain strings, not JSON objects. "
                f"Example: use 'w A1 | [\\'Header\\']' not {{'operation': 'w', 'range': 'A1'}}. "
                f"Format: ['@Sheet1', 'w A1 | [values]', 'a | [values]']"
            )
        
        # Map of valid commands
        handler_map = {
            "w": self._cmd_write,
            "a": self._cmd_append,
            "clr": self._cmd_clear,
            "ins": self._cmd_insert,
            "del": self._cmd_delete,
            "mg": self._cmd_merge,
            "auto": self._cmd_auto_resize,
            "fmt": self._cmd_format,
            "chart": self._cmd_chart,
            # Allow shorthand 'c' as alias for 'chart'
            "c": self._cmd_chart,
            # Import CSV text directly into sheet
            "csv": self._cmd_csv,
            "v": self._cmd_validation,
            "p": self._cmd_protection,
        }
        
        handler = handler_map.get(command)
        
        # If not a known command, check if it looks like a range (common LLM mistake)
        if not handler:
            # Check if command looks like partial JSON
            if "{" in command or "'{" in command or '"operation"' in command.lower():
                raise ToolDefinitionError(
                    f"Invalid SheetOps format: '{op}' contains JSON-like structure. "
                    f"SheetOps requires plain string commands, not JSON objects. "
                    f"Example format: 'w A1 | [\\'Header1\\',\\'Header2\\']' not {{'operation': 'w'}}. "
                    f"Valid commands: w (write), a (append), clr (clear), fmt (format), chart, etc."
                )
            
            # Check if the command looks like an A1 range (e.g., "A1", "A1:C1", "Sheet1!A1")
            # This usually means the LLM generated a range without a command prefix
            if self._looks_like_a1_range(command):
                raise ToolDefinitionError(
                    f"Invalid SheetOps syntax: '{op}' looks like a range (e.g., A1:C1) but is missing a command. "
                    f"Use a command prefix like 'w A1:C1 | [values]' for write, 'a | [values]' for append, etc. "
                    f"Valid commands: w (write), a (append), clr (clear), fmt (format), chart, etc."
                )
            
            raise ToolDefinitionError(
                f"Unsupported SheetOps command '{command}'. "
                f"Valid commands: w (write), a (append), clr (clear), fmt (format), chart, ins (insert), del (delete), mg (merge), auto (auto-resize), v (validation), p (protection)."
            )
        
        return handler(*args)
    
    def _looks_like_a1_range(self, text: str) -> bool:
        """Check if text looks like an A1 notation range (e.g., A1, A1:C1, Sheet1!A1)
        Returns False for known SheetOps commands.
        """
        if not text:
            return False
        text = text.strip()
        
        # Known SheetOps commands - these are NOT ranges
        # Include 'c' as shorthand alias for 'chart'
        known_commands = {'w', 'a', 'clr', 'ins', 'del', 'mg', 'auto', 'fmt', 'chart', 'c', 'v', 'p'}
        if text.lower() in known_commands:
            return False
        
        # Pattern: must have column letters followed by row number, or just row number, or sheet!range
        # Examples: A1, A1:C1, Sheet1!A1, $A$1, A1:B10, 1, 5
        # Does NOT match: w, a, clr (commands) - already filtered above
        a1_pattern = r'^(\$?[A-Z]+\$?\d+|\$?\d+)(:\$?[A-Z]+\$?\d+)?$'
        sheet_range_pattern = r'^[^\s!]+!\$?[A-Z]+\$?\d+'
        
        # Check if it matches A1 pattern
        is_a1 = bool(re.match(a1_pattern, text, re.IGNORECASE)) or bool(re.match(sheet_range_pattern, text, re.IGNORECASE))
        
        # Additional check: single letter columns (A, B, C, etc.) without numbers
        # These are ambiguous - could be column reference or could be part of a command
        # We'll only treat as range if it's clearly not a command (already checked above)
        if re.match(r'^[A-Z]+$', text, re.IGNORECASE) and not is_a1:
            # Pure column letters without number - treat as potential range only if not a command
            return True
        
        return is_a1

    def _parse_command(self, op: str) -> Tuple[str, List[str]]:
        segments = [segment.strip() for segment in op.split("|")]
        head = segments[0]
        inline_parts = head.split()
        command = inline_parts[0].lower()
        args: List[str] = []
        if len(inline_parts) > 1:
            args.append(" ".join(inline_parts[1:]))
        args.extend(segments[1:])
        return command, args

    def _set_sheet(self, sheet_name: str):
        normalized = normalize_sheet_title(sheet_name)
        if not normalized:
            raise ToolExecutionError(tool_name="gsheets", detail="Sheet name cannot be empty.")
        sheet_title, sheet_id = self.client.ensure_sheet(self.spreadsheet_id, normalized)
        self.current_sheet = sheet_title
        self.current_sheet_id = sheet_id

    def _ensure_sheet_context(self):
        if self.current_sheet and self.current_sheet_id is not None:
            return
        # Default to the first sheet (Sheet1) if none specified yet
        self._set_sheet(self.current_sheet or "Sheet1")

    # === Command handlers ===

    def _cmd_write(self, *args) -> str:
        """Write command: accepts range and value, ignores extra arguments"""
        range_arg = args[0] if len(args) > 0 else None
        value_arg = args[1] if len(args) > 1 else None
        
        if not range_arg:
            raise ToolExecutionError(tool_name="gsheets", detail="Write command requires a range argument.")
        if value_arg is None:
            raise ToolExecutionError(tool_name="gsheets", detail="Write command requires a value.")
        target_range = self._resolve_range(range_arg)
        values = self._coerce_to_matrix(self._resolve_value(value_arg))
        # Collect for batching instead of executing immediately
        self.pending_value_updates.append({
            "range": target_range,
            "values": values
        })
        return f"wrote {len(values)} row(s) to {target_range}"

    def _cmd_append(self, first_arg: Optional[str] = None, second_arg: Optional[str] = None) -> str:
        if second_arg is None:
            value_token = first_arg
            target = None
        else:
            target = first_arg
            value_token = second_arg
        if value_token is None:
            raise ToolExecutionError(tool_name="gsheets", detail="Append command requires a value.")
        
        # Ensure we have a valid sheet context
        self._ensure_sheet_context()
        
        # For append operations, use just the sheet name (not a range)
        # Google Sheets API append operation expects sheet name like "Sheet1", not "Sheet1!A1"
        if target:
            # If a target is specified, extract just the sheet name if it looks like a range
            # Validate that target doesn't contain invalid characters (like email subjects)
            if any(char in target for char in ['[', ']', ':', '"', "'"]):
                # If target contains special characters that look like data, it's likely a mistake
                # Use the current sheet instead
                sheet_name = self.current_sheet
            else:
                sheet_part, _ = split_sheet_and_range(target)
                if sheet_part:
                    # Ensure the sheet exists and get its actual title
                    normalized = normalize_sheet_title(sheet_part)
                    if normalized:
                        sheet_title, _ = self.client.ensure_sheet(self.spreadsheet_id, normalized)
                        sheet_name = sheet_title
                    else:
                        sheet_name = self.current_sheet
                else:
                    sheet_name = self.current_sheet
        else:
            sheet_name = self.current_sheet
        
        if not sheet_name:
            raise ToolExecutionError(tool_name="gsheets", detail="No sheet context available for append operation.")
        
        rows = self._coerce_to_matrix(self._resolve_value(value_token))
        # Collect for batching - append needs to be executed in order, so we'll do it separately
        # Use just the sheet name for append operations (Google Sheets API requirement)
        self.pending_appends.append({
            "range": sheet_name,
            "values": rows
        })
        return f"appended {len(rows)} row(s) to {sheet_name}"

    def _cmd_clear(self, range_arg: Optional[str] = None) -> str:
        if not range_arg:
            raise ToolExecutionError(tool_name="gsheets", detail="Clear command requires a range.")
        target_range = self._resolve_range(range_arg)
        # Collect for batching instead of executing immediately
        self.pending_clears.append(target_range)
        return f"cleared {self._display_range(target_range)}"

    def _cmd_insert(self, dimension_arg: Optional[str] = None, idx_arg: Optional[str] = None, qty_arg: Optional[str] = None) -> str:
        dimension = (dimension_arg or "").lower()
        if dimension not in {"row", "col", "column"}:
            raise ToolExecutionError(tool_name="gsheets", detail="Insert command must specify 'row' or 'col'.")
        index = self._parse_int(idx_arg, "Insert index", default=1) - 1
        quantity = self._parse_int(qty_arg, "Insert quantity", default=1)
        sheet_id = self._get_sheet_id_for_dimension(None)
        dim_key = "ROWS" if dimension == "row" else "COLUMNS"
        request = {
            "insertDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": dim_key,
                    "startIndex": max(index, 0),
                    "endIndex": max(index, 0) + max(quantity, 1),
                },
                "inheritFromBefore": True,
            }
        }
        # Collect for batching instead of executing immediately
        self.pending_batch_requests.append(request)
        return f"inserted {quantity} {dimension}(s) at {index + 1}"

    def _cmd_delete(self, dimension_arg: Optional[str] = None, idx_arg: Optional[str] = None, qty_arg: Optional[str] = None) -> str:
        dimension = (dimension_arg or "").lower()
        if dimension not in {"row", "col", "column"}:
            raise ToolExecutionError(tool_name="gsheets", detail="Delete command must specify 'row' or 'col'.")
        index = self._parse_int(idx_arg, "Delete index", default=1) - 1
        quantity = self._parse_int(qty_arg, "Delete quantity", default=1)
        sheet_id = self._get_sheet_id_for_dimension(None)
        dim_key = "ROWS" if dimension == "row" else "COLUMNS"
        request = {
            "deleteDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": dim_key,
                    "startIndex": max(index, 0),
                    "endIndex": max(index, 0) + max(quantity, 1),
                }
            }
        }
        # Collect for batching instead of executing immediately
        self.pending_batch_requests.append(request)
        return f"deleted {quantity} {dimension}(s) starting at {index + 1}"

    def _cmd_merge(self, range_arg: Optional[str] = None) -> str:
        if not range_arg:
            raise ToolExecutionError(tool_name="gsheets", detail="Merge command requires a range.")
        grid_range, display = self._grid_range_with_display(range_arg)
        request = {
            "mergeCells": {
                "range": grid_range,
                "mergeType": "MERGE_ALL",
            }
        }
        # Collect for batching instead of executing immediately
        self.pending_batch_requests.append(request)
        return f"merged cells in {display}"

    def _cmd_auto_resize(self, range_arg: Optional[str] = None) -> str:
        if not range_arg:
            raise ToolExecutionError(tool_name="gsheets", detail="Auto command requires a range.")
        grid_range, display = self._grid_range_with_display(range_arg)
        requests = []
        if "startColumnIndex" in grid_range and "endColumnIndex" in grid_range:
            requests.append(
                {
                    "autoResizeDimensions": {
                        "dimensions": {
                            "sheetId": grid_range["sheetId"],
                            "dimension": "COLUMNS",
                            "startIndex": grid_range["startColumnIndex"],
                            "endIndex": grid_range["endColumnIndex"],
                        }
                    }
                }
            )
        if "startRowIndex" in grid_range and "endRowIndex" in grid_range:
            requests.append(
                {
                    "autoResizeDimensions": {
                        "dimensions": {
                            "sheetId": grid_range["sheetId"],
                            "dimension": "ROWS",
                            "startIndex": grid_range["startRowIndex"],
                            "endIndex": grid_range["endRowIndex"],
                        }
                    }
                }
            )
        if not requests:
            raise ToolExecutionError(tool_name="gsheets", detail="Auto command requires a concrete row or column range.")
        # Collect for batching instead of executing immediately
        self.pending_batch_requests.extend(requests)
        return f"auto-resized {display}"

    def _cmd_format(self, range_arg: Optional[str] = None, tags_arg: Optional[str] = None) -> str:
        if not range_arg:
            raise ToolExecutionError(tool_name="gsheets", detail="Format command requires a range.")
        tags = [tag.strip() for tag in (tags_arg or "").split(",") if tag.strip()]
        if not tags:
            raise ToolExecutionError(tool_name="gsheets", detail="Format command requires at least one tag.")
        grid_range, display = self._grid_range_with_display(range_arg)
        repeat_cell = {
            "range": grid_range,
            "cell": {"userEnteredFormat": {}},
            "fields": [],
        }
        requests: List[Dict[str, Any]] = []
        border_requests: List[Dict[str, Any]] = []
        banding_request: Optional[Dict[str, Any]] = None

        for tag in tags:
            lower = tag.lower()
            if lower == "header":
                repeat_cell["cell"].setdefault("userEnteredFormat", {}).setdefault("textFormat", {})["bold"] = True
                repeat_cell["cell"]["userEnteredFormat"]["horizontalAlignment"] = "CENTER"
                repeat_cell["cell"]["userEnteredFormat"]["backgroundColor"] = COLOR_MAP["blue"]
            elif lower in {"bold", "italic", "strike"}:
                repeat_cell["cell"].setdefault("userEnteredFormat", {}).setdefault("textFormat", {})[lower] = True
            elif lower in {"left", "right", "center"}:
                repeat_cell["cell"].setdefault("userEnteredFormat", {})["horizontalAlignment"] = lower.upper()
            elif lower == "wrap":
                repeat_cell["cell"].setdefault("userEnteredFormat", {})["wrapStrategy"] = "WRAP"
            elif lower in {"currency", "percent", "date"}:
                fmt_type = {"currency": "CURRENCY", "percent": "PERCENT", "date": "DATE"}[lower]
                repeat_cell["cell"].setdefault("userEnteredFormat", {})["numberFormat"] = {"type": fmt_type}
            elif lower.startswith("text:"):
                color = self._parse_color(lower.split(":", 1)[1])
                repeat_cell["cell"].setdefault("userEnteredFormat", {}).setdefault("textFormat", {})[
                    "foregroundColor"
                ] = color
            elif lower.startswith("bg:"):
                color = self._parse_color(lower.split(":", 1)[1])
                repeat_cell["cell"].setdefault("userEnteredFormat", {})["backgroundColor"] = color
            elif lower.startswith("border:"):
                side = lower.split(":", 1)[1]
                border_requests.append(self._build_border_request(grid_range, side))
            elif lower.startswith("alt-rows:"):
                color = self._parse_color(lower.split(":", 1)[1])
                banding_request = self._build_banding_request(grid_range, color)

        # Collect fields from the userEnteredFormat dict, not the entire cell dict
        repeat_cell["fields"] = _collect_repeat_fields(repeat_cell["cell"].get("userEnteredFormat", {}))
        requests.append({"repeatCell": repeat_cell})
        requests.extend(border_requests)
        if banding_request:
            requests.append(banding_request)
        # Collect for batching instead of executing immediately
        self.pending_batch_requests.extend(requests)
        return f"applied formatting ({', '.join(tags)}) to {display}"

    def _cmd_chart(
        self,
        type_arg: Optional[str] = None,
        data_arg: Optional[str] = None,
        dest_arg: Optional[str] = None,
    ) -> str:
        chart_type = (type_arg or "bar").lower()
        data_range = data_arg or ""
        if not data_range:
            raise ToolExecutionError(tool_name="gsheets", detail="Chart command requires a data range.")

        data_sheet_name, pure_range = split_sheet_and_range(data_range)
        data_sheet_id = self._get_sheet_id_for_dimension(data_sheet_name)
        grid_range = a1_to_grid_range(pure_range, data_sheet_id)
        dest_sheet_name = None
        dest_cell = dest_arg or "A1"
        if "!" in dest_cell:
            dest_sheet_name, dest_cell = split_sheet_and_range(dest_cell)

        dest_sheet_id = self._get_sheet_id_for_dimension(dest_sheet_name)
        anchor = a1_to_grid_range(dest_cell, dest_sheet_id)

        request = self._build_chart_request(chart_type, grid_range, anchor, data_sheet_id, dest_sheet_id)
        # Collect for batching instead of executing immediately
        self.pending_batch_requests.append(request)
        return f"added {chart_type} chart for {self._display_range(data_range)}"

    def _cmd_csv(
        self,
        range_arg: Optional[str] = None,
        csv_arg: Optional[str] = None,
    ) -> str:
        """
        Import CSV data into the sheet starting at the given range.
        Usage in SheetOps: "csv A1 | col1,col2\\n1,2\\n3,4"
        - First arg: start cell / range (e.g., A1, Sheet1!A1)
        - Second arg: CSV text (header + rows)
        """
        if not range_arg:
            raise ToolExecutionError(tool_name="gsheets", detail="CSV command requires a start range (e.g., A1).")
        if not csv_arg:
            raise ToolExecutionError(tool_name="gsheets", detail="CSV command requires CSV text as second argument.")

        import csv
        from io import StringIO

        # Parse CSV into 2D list
        reader = csv.reader(StringIO(csv_arg))
        values = [row for row in reader]

        # Resolve range and queue as a value update (same pattern as _cmd_write)
        target_range = self._resolve_range(range_arg)
        # Collect for batching instead of executing immediately
        self.pending_value_updates.append({
            "range": target_range,
            "values": values
        })
        return f"imported CSV into {self._display_range(range_arg)}"

    def _cmd_validation(self, range_arg: Optional[str] = None, rule_arg: Optional[str] = None) -> str:
        if not range_arg or not rule_arg:
            raise ToolExecutionError(tool_name="gsheets", detail="Validation command requires range and rule.")
        grid_range, display = self._grid_range_with_display(range_arg)
        rule = self._build_validation_rule(rule_arg)
        request = {"setDataValidation": {"range": grid_range, "rule": rule}}
        # Collect for batching instead of executing immediately
        self.pending_batch_requests.append(request)
        return f"applied validation '{rule_arg}' to {display}"

    def _cmd_protection(self, range_arg: Optional[str] = None, mode_arg: Optional[str] = None) -> str:
        if not range_arg:
            raise ToolExecutionError(tool_name="gsheets", detail="Protection command requires a range.")
        mode = (mode_arg or "strict").lower()
        grid_range, display = self._grid_range_with_display(range_arg)
        request = {
            "addProtectedRange": {
                "protectedRange": {
                    "range": grid_range,
                    "description": f"Protected by agent ({mode})",
                    "warningOnly": mode != "strict",
                }
            }
        }
        # Collect for batching instead of executing immediately
        self.pending_batch_requests.append(request)
        return f"added {mode} protection to {display}"

    # === Batch execution ===

    def _execute_batched_operations(self):
        """Execute all collected operations in optimized batches."""
        # Execute clear operations first (they're fast and need to happen before writes)
        for clear_range in self.pending_clears:
            self.client.clear_range(self.spreadsheet_id, clear_range)
        
        # Convert write operations to batchUpdate requests
        for write_op in self.pending_value_updates:
            range_str = write_op["range"]
            values = write_op["values"]
            
            # Parse the start range to get sheet and starting cell
            sheet_part, pure_range = split_sheet_and_range(range_str)
            sheet_name = sheet_part or self.current_sheet or "Sheet1"
            sheet_id = self._get_sheet_id_for_dimension(sheet_name)
            
            # Parse start cell (e.g., "A1" from "A1" or "A1:D1")
            if ":" in pure_range:
                start_token = pure_range.split(":")[0]
            else:
                start_token = pure_range
            
            # Get start column and row (parse_a1_token returns 0-based indices)
            start_col, start_row = parse_a1_token(start_token)
            
            # Calculate end column and row based on data size
            num_rows = len(values)
            num_cols = max(len(row) for row in values) if values else 0
            
            # Calculate end positions (0-indexed, exclusive)
            # start_col and start_row are already 0-indexed from parse_a1_token
            end_col = (start_col if start_col is not None else 0) + num_cols
            end_row = (start_row if start_row is not None else 0) + num_rows
            
            # Create grid range that covers all cells being written
            grid_range: Dict[str, Any] = {"sheetId": sheet_id}
            if start_row is not None:
                grid_range["startRowIndex"] = start_row
                grid_range["endRowIndex"] = end_row
            else:
                grid_range["startRowIndex"] = 0
                grid_range["endRowIndex"] = end_row
            
            if start_col is not None:
                grid_range["startColumnIndex"] = start_col
                grid_range["endColumnIndex"] = end_col
            else:
                grid_range["startColumnIndex"] = 0
                grid_range["endColumnIndex"] = end_col
            
            # Convert values to cell data format for batchUpdate
            rows = []
            for row in values:
                cells = []
                for value in row:
                    cell_data = {"userEnteredValue": {}}
                    # Handle None/null values
                    if value is None:
                        cell_data["userEnteredValue"]["stringValue"] = ""
                    # Handle booleans first (before string conversion)
                    elif isinstance(value, bool):
                        cell_data["userEnteredValue"]["boolValue"] = value
                    # Handle string booleans ("true", "false") - convert to actual booleans
                    elif isinstance(value, str) and value.lower() in ("true", "false"):
                        cell_data["userEnteredValue"]["boolValue"] = value.lower() == "true"
                    # Handle numbers
                    elif isinstance(value, (int, float)):
                        # Ensure it's a valid number (not NaN or Infinity)
                        if isinstance(value, float) and (value != value or abs(value) == float('inf')):
                            cell_data["userEnteredValue"]["stringValue"] = str(value)
                        else:
                            cell_data["userEnteredValue"]["numberValue"] = value
                    # Handle formulas
                    elif isinstance(value, str) and value.startswith("="):
                        cell_data["userEnteredValue"]["formulaValue"] = value
                    # Everything else as string
                    else:
                        cell_data["userEnteredValue"]["stringValue"] = str(value)
                    cells.append(cell_data)
                rows.append({"values": cells})
            
            # Create updateCells request for batchUpdate
            request = {
                "updateCells": {
                    "range": grid_range,
                    "rows": rows,
                    "fields": "userEnteredValue"
                }
            }
            self.pending_batch_requests.append(request)
        
        # Execute all batchUpdate requests together (if any)
        # This batches all format, insert, delete, merge, auto-resize, chart, validation, and protection operations
        if self.pending_batch_requests:
            self.client.batch_update(self.spreadsheet_id, self.pending_batch_requests)
        
        # Execute append operations last (these need to be done separately and in order)
        # since they depend on existing data and need to be sequential
        for append_op in self.pending_appends:
            self.client.append_values(
                self.spreadsheet_id,
                append_op["range"],
                append_op["values"]
            )

    # === Helpers ===

    def _resolve_range(self, range_expr: str) -> str:
        sheet_part, pure_range = split_sheet_and_range(range_expr)
        sheet_name = sheet_part or self.current_sheet or "Sheet1"
        if "!" in range_expr:
            return f"{sheet_name}!{pure_range}"
        return f"{sheet_name}!{pure_range}"

    def _grid_range_with_display(self, range_expr: str) -> Tuple[Dict[str, Any], str]:
        sheet_part, pure_range = split_sheet_and_range(range_expr)
        sheet_name = sheet_part or self.current_sheet or "Sheet1"
        sheet_id = self._get_sheet_id_for_dimension(sheet_name)
        grid = a1_to_grid_range(pure_range, sheet_id)
        display = self._display_range(f"{sheet_name}!{pure_range}")
        return grid, display

    def _get_sheet_id_for_dimension(self, sheet_name: Optional[str]) -> int:
        name = sheet_name or self.current_sheet or "Sheet1"
        return self.client.get_sheet_id(self.spreadsheet_id, name, create_if_missing=True)

    def _display_range(self, range_expr: str) -> str:
        return range_expr

    def _resolve_value(self, token: Any) -> Any:
        if token is None:
            return ""
        if isinstance(token, (list, dict)):
            return token
        text = str(token).strip()
        # Handle variable references first (e.g., $data)
        # This allows passing Python lists directly without JSON serialization
        if text.startswith("$") and text[1:].strip():
            var_name = text[1:].strip()
            var_value = self.variables.get(var_name, "")
            if isinstance(var_value, dict) and "value" in var_value:
                return var_value.get("value")
            return var_value
        # Check if it's a JSON-like structure first (before variable substitution)
        # This prevents $ signs in string values from being treated as variables
        if text.startswith("[") or text.startswith("{"):
            # Normalize fancy quotes and guillemets that break JSON parsing
            sanitized = (
                text.replace("“", '"')
                    .replace("”", '"')
                    .replace("«", '"')
                    .replace("»", '"')
                    .strip()
            )
            import json as _json
            # Try JSON first (most common for our payloads)
            try:
                return _json.loads(sanitized)
            except Exception:
                pass
            # Fallback to Python literal
            try:
                parsed = ast.literal_eval(sanitized)
                return parsed
            except Exception:
                # Additional fallbacks for escaped or double-wrapped content
                try:
                    # If it's wrapped in quotes entirely, strip and retry
                    if sanitized.startswith('"') and sanitized.endswith('"'):
                        inner = sanitized[1:-1]
                        try:
                            return _json.loads(inner)
                        except Exception:
                            try:
                                return ast.literal_eval(inner)
                            except Exception:
                                pass
                    # Replace escaped quotes and retry (no raw strings to avoid parser issues)
                    unescaped = sanitized.replace('\\"', '"').replace("\\'", "'")
                    try:
                        return _json.loads(unescaped)
                    except Exception:
                        try:
                            return ast.literal_eval(unescaped)
                        except Exception:
                            pass
                    # Heuristic: if it still looks like a list-of-lists, try raw and deescaped variants
                    if sanitized.startswith("[[") and "],[" in sanitized:
                        try:
                            return ast.literal_eval(sanitized)
                        except Exception:
                            try:
                                return _json.loads(sanitized)
                            except Exception:
                                try:
                                    deescaped = bytes(sanitized, "utf-8").decode("unicode_escape")
                                    return ast.literal_eval(deescaped)
                                except Exception:
                                    pass
                except Exception:
                    console.error("Value parsing error", f"{e}", task_id=self.task_id, agent_id=self.agent_id)
        # Replace embedded placeholders - but only if the text is NOT a JSON structure
        # Use a more restrictive pattern that requires variable names to start with a letter or underscore
        def _sub(match):
            key = match.group(1)
            val = self.variables.get(key, "")
            if isinstance(val, dict) and "value" in val:
                return str(val.get("value", ""))
            return str(val)

        # Only replace $variable where variable starts with letter or underscore (valid variable name)
        # This prevents $170 from being treated as a variable
        text = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", _sub, text)
        if text.startswith(("'", '"')) and text.endswith(text[0]):
            return text[1:-1]
        lower = text.lower()
        if lower in {"true", "false"}:
            return lower == "true"
        return text

    def _coerce_to_matrix(self, value: Any) -> List[List[Any]]:
        if isinstance(value, list):
            if not value:
                return [[""]]
            if all(isinstance(item, list) for item in value):
                return [self._coerce_row(row) for row in value]  # type: ignore
            return [self._coerce_row(value)]
        if isinstance(value, str) and "\n" in value:
            rows = [row.strip() for row in value.splitlines() if row.strip()]
            return [[row] for row in rows] or [[value]]
        return [[value]]

    def _coerce_row(self, row: Any) -> List[Any]:
        if isinstance(row, list):
            return [self._stringify_cell(cell) for cell in row]
        return [self._stringify_cell(row)]

    def _stringify_cell(self, cell: Any) -> Any:
        if isinstance(cell, (dict, list)):
            return json.dumps(cell, ensure_ascii=False)
        return cell

    def _parse_int(self, value: Optional[str], label: str, default: int = 0) -> int:
        if value is None or not str(value).strip():
            return default
        try:
            return int(str(value).strip())
        except ValueError as exc:
            raise ToolExecutionError(tool_name="gsheets", detail=f"{label} must be a number.") from exc

    def _strip_quotes(self, text: str) -> str:
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            return text[1:-1]
        return text

    def _parse_color(self, token: str) -> Dict[str, float]:
        token = token.strip().lower()
        if token in COLOR_MAP:
            return COLOR_MAP[token]
        if token.startswith("#") and len(token) in {4, 7}:
            return hex_to_color(token)
        raise ToolExecutionError(tool_name="gsheets", detail=f"Unsupported color value '{token}'.")

    def _build_border_request(self, grid_range: Dict[str, Any], side: str) -> Dict[str, Any]:
        sides = []
        if side == "all":
            sides = ["top", "bottom", "left", "right"]
        else:
            sides = [side]
        border = {"style": "SOLID", "width": 1, "color": COLOR_MAP["gray"]}
        request = {"updateBorders": {"range": grid_range.copy()}}
        for s in sides:
            key = s.lower()
            if key not in {"top", "bottom", "left", "right"}:
                continue
            request["updateBorders"][key] = border
        return request

    def _build_banding_request(self, grid_range: Dict[str, Any], color: Dict[str, float]) -> Dict[str, Any]:
        return {
            "addBanding": {
                "bandedRange": {
                    "range": grid_range,
                    "rowProperties": {
                        "headerColor": color,
                        "firstBandColor": color,
                        "secondBandColor": COLOR_MAP["white"],
                    },
                }
            }
        }

    def _build_validation_rule(self, rule: str) -> Dict[str, Any]:
        rule = rule.strip()
        lower = rule.lower()
        if lower == "bool":
            return {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
        if lower.startswith("list:"):
            values = [value.strip() for value in rule.split(":", 1)[1].split(",") if value.strip()]
            return {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": value} for value in values],
                },
                "showCustomUi": True,
            }
        if lower == "date":
            return {"condition": {"type": "DATE_IS_VALID"}, "strict": True, "showCustomUi": True}
        raise ToolExecutionError(tool_name="gsheets", detail=f"Unsupported validation rule '{rule}'.")

    def _build_chart_request(
        self,
        chart_type: str,
        data_range: Dict[str, Any],
        anchor: Dict[str, Any],
        data_sheet_id: int,
        dest_sheet_id: int,
    ) -> Dict[str, Any]:
        chart_type_map = {
            "bar": "BAR",
            "line": "LINE",
            "pie": "PIE",
            "col": "COLUMN",
            "column": "COLUMN",
        }
        normalized = chart_type_map.get(chart_type, "BAR")
        if normalized == "PIE":
            spec = {
                "title": "Pie Chart",
                "pieChart": {
                    "domain": {"sourceRange": {"sources": [data_range]}},
                    "series": {"sourceRange": {"sources": [data_range]}},
                },
            }
        else:
            # Use first column as domain, remaining columns as series
            domain_range = data_range.copy()
            domain_range["endColumnIndex"] = domain_range["startColumnIndex"] + 1
            series_range = data_range.copy()
            series_start = data_range["startColumnIndex"] + 1
            series_range["startColumnIndex"] = series_start
            spec = {
                "title": f"{normalized.title()} Chart",
                "basicChart": {
                    "chartType": normalized,
                    "legendPosition": "BOTTOM_LEGEND",
                    "domains": [{"domain": {"sourceRange": {"sources": [domain_range]}}}],
                    "series": [
                        {"series": {"sourceRange": {"sources": [series_range]}}}
                    ],
                },
            }
        request = {
            "addChart": {
                "chart": {
                    "spec": spec,
                    "position": {
                        "overlayPosition": {
                            "anchorCell": {
                                "sheetId": dest_sheet_id,
                                "rowIndex": anchor.get("startRowIndex", 0),
                                "columnIndex": anchor.get("startColumnIndex", 0),
                            }
                        }
                    },
                }
            }
        }
        return request


def _collect_repeat_fields(format_dict: Dict[str, Any]) -> str:
    fields = []
    if not format_dict:
        return ""
    for key, value in format_dict.items():
        if isinstance(value, dict):
            for sub_key in value.keys():
                fields.append(f"userEnteredFormat.{key}.{sub_key}")
        else:
            fields.append(f"userEnteredFormat.{key}")
    return ",".join(sorted(set(fields)))


def hex_to_color(value: str) -> Dict[str, float]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    r = int(value[0:2], 16) / 255.0
    g = int(value[2:4], 16) / 255.0
    b = int(value[4:6], 16) / 255.0
    return {"red": r, "green": g, "blue": b}


def _coerce_ops(ops_payload: Any) -> List[str]:
    def _extract_op_string(item: Any) -> Optional[str]:
        """Extract SheetOps string from various formats (string, dict, etc.)"""
        if isinstance(item, str):
            return item.strip() if item.strip() else None
        if isinstance(item, dict):
            # Try common keys that LLM might use
            op_value = (
                item.get("operation") or 
                item.get("op") or 
                item.get("command") or 
                item.get("cmd") or
                item.get("value") or
                item.get("text")
            )
            if op_value:
                return str(op_value).strip() if str(op_value).strip() else None
            # If dict has only one key-value pair, use the value
            if len(item) == 1:
                return str(list(item.values())[0]).strip() if list(item.values())[0] else None
            # If no recognizable key, convert entire dict to string (will error later with better message)
            return None
        return str(item).strip() if str(item).strip() else None
    
    if isinstance(ops_payload, list):
        result = []
        for item in ops_payload:
            op_str = _extract_op_string(item)
            if op_str:
                result.append(op_str)
            elif isinstance(item, dict):
                # Dict that couldn't be extracted - provide helpful error context
                raise ToolDefinitionError(
                    f"Invalid SheetOps format: received dict {item} but couldn't extract operation. "
                    f"Expected format: list of strings like ['@Sheet1', 'w A1 | [\\'Header\\']', 'a | [\\'Data\\']']. "
                    f"If using JSON, use array of strings, not objects."
                )
        return result
    if isinstance(ops_payload, str):
        text = ops_payload.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                result = []
                for item in parsed:
                    op_str = _extract_op_string(item)
                    if op_str:
                        result.append(op_str)
                    elif isinstance(item, dict):
                        raise ToolDefinitionError(
                            f"Invalid SheetOps format: received dict {item} in JSON. "
                            f"Expected array of strings like [\"@Sheet1\", \"w A1 | ['Header']\"]. "
                            f"Don't use objects with 'operation' keys - use plain strings."
                        )
                return result
        except json.JSONDecodeError:
            pass
        if text.startswith("[") and text.endswith("]"):
            # Attempt literal eval for Python-style lists
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, list):
                    result = []
                    for item in parsed:
                        op_str = _extract_op_string(item)
                        if op_str:
                            result.append(op_str)
                        elif isinstance(item, dict):
                            raise ToolDefinitionError(
                                f"Invalid SheetOps format: received dict {item}. "
                                f"Expected list of strings like ['@Sheet1', 'w A1 | [\\'Header\\']']."
                            )
                    return result
            except Exception:
                pass
        # Fallback: split on newline/semicolon
        segments = re.split(r"[\n;]", text)
        return [segment.strip().strip('"').strip("'") for segment in segments if segment.strip()]
    raise ToolExecutionError(tool_name="gsheets", detail="ops must be a list or JSON array/string.")


async def gsheets_tool(
    user_input: Any = "",
    task_id: Optional[str] = None,
    light_llm: Optional[str] = None,
    heavy_llm: Optional[str] = None,
    agent_id: Optional[str] = None,
    validation_mode: bool = False,
    credentials: Optional[Dict[str, Any]] = None,
    connection: Any = None,
    **kwargs: Any,
):
    context = user_input if isinstance(user_input, dict) else {}
    action = (context.get("action") or "").upper()
    params = context.get("params") or {}
    variables = context.get("variables") or {}
    default_sheet = params.get("sheet") or params.get("default_sheet")

    if not action:
        raise ToolExecutionError(tool_name="gsheets", detail="Google Sheets tool requires an action (CREATE, READ, or BATCH).")

    # CREATE doesn't need spreadsheet_id
    if action != "CREATE":
        spreadsheet_id = (
            params.get("spreadsheet_id")
            or params.get("sheet_id")
            or params.get("spreadsheet")
            or (getattr(connection, "metadata", {}) or {}).get("spreadsheet_id")
        )
        if not spreadsheet_id:
            raise ConnectionConfigurationError(
                tool_name="gsheets",
                detail="Google Sheets requires 'spreadsheet_id' in params or connection metadata."
            )

    # Get credentials - prioritize direct credentials, then try connection object
    creds_payload = credentials or {}
    if not creds_payload and connection is not None:
        try:
            creds_payload = connection.get_credentials()
        except Exception as e:
            console.tool(f"[SHEETS] Warning: Failed to get credentials from connection: {e}", task_id=task_id, agent_id=agent_id)
            creds_payload = {}
    
    # Validate that we have credentials before proceeding
    if not creds_payload:
        raise GoogleSheetsError(
            "Google Sheets connection is missing OAuth credentials. "
            "Please reconnect Google Sheets to continue."
        )
    
    # Log credential keys for debugging (without exposing sensitive values)
    cred_keys = list(creds_payload.keys()) if isinstance(creds_payload, dict) else []
    console.debug(f"[SHEETS] Credentials available with keys: {cred_keys}", task_id=task_id, agent_id=agent_id)

    # Try to ensure Sheets API is enabled automatically
    if _has_api_manager:
        try:
            api_manager = get_api_manager()
            if api_manager:
                api_manager.ensure_api_enabled('sheets')
        except Exception as e:
            # Non-fatal - continue even if API enabling fails
            console.tool(f"[SHEETS] Warning: Could not auto-enable Sheets API: {e}", task_id=task_id, agent_id=agent_id)

    client = GoogleSheetsClient(creds_payload)

    if action == "CREATE":
        title = params.get("title") or params.get("name")
        if not title:
            raise ToolExecutionError(tool_name="gsheets", detail="sheets CREATE requires params.title or params.name.")
        folder_id = params.get("folderId") or params.get("folder_id")
        
        # Ensure service is initialized (this builds credentials)
        client._ensure_service()
        
        # Access credentials from the client
        if not hasattr(client, '_credentials') or not client._credentials:
            raise GoogleSheetsError("Sheets connection is missing OAuth credentials.")
            
        initial_data = params.get("data")
        ops_payload = params.get("ops")
        
        # Helper to convert 2D list to Sheets API GridData
        def list_to_grid_data(values):
            rows = []
            for row in values:
                cells = []
                for val in row:
                    cell = {"userEnteredValue": {}}
                    if isinstance(val, bool):
                        cell["userEnteredValue"]["boolValue"] = val
                    elif isinstance(val, (int, float)):
                        cell["userEnteredValue"]["numberValue"] = val
                    elif isinstance(val, str) and val.startswith("="):
                        cell["userEnteredValue"]["formulaValue"] = val
                    else:
                        cell["userEnteredValue"]["stringValue"] = str(val) if val is not None else ""
                    cells.append(cell)
                rows.append({"values": cells})
            return rows

        if not folder_id:
            # OPTIMIZATION: Use Sheets API create() - significantly faster than Drive API 
            # and allows including initial data in the same call.
            spreadsheet_body = {"properties": {"title": title}}
            
            if initial_data:
                sheet_name = params.get("sheet") or "Sheet1"
                spreadsheet_body["sheets"] = [{
                    "properties": {"title": sheet_name},
                    "data": [{
                        "startRow": 0,
                        "startColumn": 0,
                        "rowData": list_to_grid_data(initial_data)
                    }]
                }]
            
            result = client._service.spreadsheets().create(body=spreadsheet_body).execute()
            spreadsheet_id = result.get("spreadsheetId")
            
            # If we still have separate ops (other than just the initial data), run them now
            if ops_payload:
                ops = _coerce_ops(ops_payload)
                interpreter = SheetOpsInterpreter(client, spreadsheet_id, variables={}, task_id=task_id, agent_id=agent_id)
                interpreter.run(ops)
        else:
            # Folder specified - need Drive API (using cache)
            global _DRIVE_SERVICE_CACHE
            if '_DRIVE_SERVICE_CACHE' not in globals():
                _DRIVE_SERVICE_CACHE = {}
                
            cache_key = id(client._credentials)
            if cache_key in _DRIVE_SERVICE_CACHE:
                drive_service = _DRIVE_SERVICE_CACHE[cache_key]
            else:
                from googleapiclient.discovery import build as build_service
                drive_service = build_service("drive", "v3", credentials=client._credentials, cache_discovery=False)
                _DRIVE_SERVICE_CACHE[cache_key] = drive_service
            
            file_metadata = {"name": title, "mimeType": "application/vnd.google-apps.spreadsheet", "parents": [folder_id]}
            file = drive_service.files().create(body=file_metadata, fields="id").execute()
            spreadsheet_id = file.get("id")
            
            # Initialize data if provided
            if initial_data or ops_payload:
                ops = []
                if ops_payload:
                    ops = _coerce_ops(ops_payload)
                elif initial_data:
                    sheet_name = params.get("sheet") or "Sheet1"
                    ops = [f"@{sheet_name}", f"w A1 | $data"]
                
                interpreter = SheetOpsInterpreter(
                    client,
                    spreadsheet_id,
                    variables={"data": initial_data} if initial_data else {},
                    task_id=task_id,
                    agent_id=agent_id,
                    default_sheet=params.get("sheet")
                )
                interpreter.run(ops)
        
        console.tool(f"[SHEETS CREATE] Created spreadsheet: {title} (ID: {spreadsheet_id})", task_id=task_id, agent_id=agent_id)
        return {
            "message": f"Spreadsheet '{title}' created successfully",
            "spreadsheet_id": spreadsheet_id,
            "title": title,
        }

    if action == "READ":
        range_name = params.get("range") or params.get("range_name")
        if not range_name:
            raise ToolExecutionError(tool_name="gsheets", detail="sheets READ requires params.range.")
        render_option = params.get("value_render_option", "UNFORMATTED_VALUE")
        date_option = params.get("date_time_render_option", "SERIAL_NUMBER")
        result = client.read_values(spreadsheet_id, range_name, value_render_option=render_option, date_time_render_option=date_option)
        values = result.get("values", [])
        summary = f"Read {len(values)} row(s) from {range_name}"
        console.tool(f"[GSHEETS READ] {summary}", task_id=task_id, agent_id=agent_id)
        return {
            "message": summary,
            "values": values,
            "range": range_name,
            "spreadsheet_id": spreadsheet_id,
        }

    if action == "BATCH":
        ops_payload = params.get("ops")
        ops = _coerce_ops(ops_payload)
        if not ops or (isinstance(ops, (list, tuple)) and len(ops) == 0):
            raise ToolExecutionError(tool_name="gsheets", detail="Google Sheets BATCH requires at least one operation in 'ops'. Received empty or invalid ops.")
        interpreter = SheetOpsInterpreter(
            client,
            spreadsheet_id,
            variables,
            task_id=task_id,
            agent_id=agent_id,
            default_sheet=default_sheet,
        )
        result = interpreter.run(ops)
        summary_lines = "\n".join(f"- {entry}" for entry in result["operations"])
        message = f"Google Sheets batch completed ({len(result['operations'])} ops):\n{summary_lines}"
        console.tool("[GSHEETS BATCH] Completed batch operations", task_id=task_id, agent_id=agent_id)
        return {
            "message": message,
            "operations": result["operations"],
            "active_sheet": result["active_sheet"],
            "spreadsheet_id": spreadsheet_id,
        }

    raise ToolExecutionError(tool_name="gsheets", detail=f"Unsupported sheets action '{action}'".join(["\n\n📋 Available Google Sheets actions:\n    • CREATE - Create a new sheet/spreadsheet\n    • READ - Read sheet data\n    • WRITE - Write data to cells\n    • UPDATE - Update existing data\n    • DELETE - Delete sheets or ranges\n\nUse one of these actions in your next request."]))

