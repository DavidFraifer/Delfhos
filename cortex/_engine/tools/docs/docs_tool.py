from __future__ import annotations

from typing import Any, Dict
from typing import Optional, Callable
from delfhos.errors import ToolExecutionError
import sys
import os
import asyncio
import json
import re

from ...utils.console import console
from .docs_client import GoogleDocsClient, GoogleDocsError

# Try to import API manager for automatic API enabling
_api_manager = None
_has_api_manager = False
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '../..'))
    api_path = os.path.join(project_root, 'api')
    if os.path.exists(api_path):
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from api.utils.google_api_manager import get_api_manager
        _has_api_manager = True
except (ImportError, Exception):
    _has_api_manager = False


def _hex_to_rgb(hex_color: str) -> Dict[str, float]:
    """Convert hex color to RGB dict"""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r = int(hex_color[0:2], 16) / 255.0
        g = int(hex_color[2:4], 16) / 255.0
        b = int(hex_color[4:6], 16) / 255.0
        return {"red": r, "green": g, "blue": b}
    return {"red": 0.0, "green": 0.0, "blue": 0.0}


def _parse_color(color: Any) -> Optional[Dict[str, float]]:
    """Parse color from string (hex) or dict"""
    if color is None:
        return None
    if isinstance(color, dict):
        return color
    if isinstance(color, str):
        if color.startswith('#'):
            return _hex_to_rgb(color)
        # Try named colors
        color_map = {
            "black": {"red": 0.0, "green": 0.0, "blue": 0.0},
            "white": {"red": 1.0, "green": 1.0, "blue": 1.0},
            "red": {"red": 0.91, "green": 0.34, "blue": 0.22},
            "green": {"red": 0.18, "green": 0.63, "blue": 0.38},
            "blue": {"red": 0.11, "green": 0.53, "blue": 0.98},
            "yellow": {"red": 0.99, "green": 0.84, "blue": 0.0},
            "orange": {"red": 0.98, "green": 0.60, "blue": 0.08},
            "purple": {"red": 0.60, "green": 0.35, "blue": 0.71},
            "gray": {"red": 0.6, "green": 0.6, "blue": 0.6},
        }
        return color_map.get(color.lower())
    return None


async def _auto_enable_docs_api() -> bool:
    """Try to auto-enable the Docs API using the configured GoogleAPIManager."""
    if not _has_api_manager:
        return False

    try:
        api_manager = get_api_manager()
        if not api_manager:
            return False

        enabled = api_manager.ensure_api_enabled("docs")
        if enabled:
            # Allow short propagation time before retrying the Docs request
            await asyncio.sleep(0.5)
        return enabled
    except Exception:
        return False


async def _execute_docs_call(operation: Callable[[], Any]):
    """Execute a docs client call, auto-enabling the API and retrying if required."""
    try:
        return operation()
    except (GoogleDocsError, Exception) as exc:
        error_text = str(exc)
        # Check for various API disabled error messages
        api_disabled_indicators = [
            "API has not been used",
            "SERVICE_DISABLED",
            "is disabled",
            "accessNotConfigured",
            "403",
            "has not been used in project",
        ]
        if any(indicator in error_text for indicator in api_disabled_indicators):
            enabled = await _auto_enable_docs_api()
            if enabled:
                return operation()
            raise GoogleDocsError(
                "Google Docs API is not enabled and automatic activation failed. "
                "Configure GOOGLE_CLOUD_PROJECT_ID together with "
                "GOOGLE_SERVICE_ACCOUNT_PATH or GOOGLE_SERVICE_ACCOUNT_JSON/GOOGLE_SERVICE_ACCOUNT_JSON_B64 "
                "so Delfhos can enable the API without manual console steps."
            ) from exc
        # Re-raise as GoogleDocsError if it's not already
        if isinstance(exc, GoogleDocsError):
            raise
        raise GoogleDocsError(f"Docs operation failed: {exc}") from exc


def _normalize_operation(op: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize an operation object to the expected format."""
    if not isinstance(op, dict):
        return None
    
    # If it already has a "type" field, it's likely in the correct format
    if "type" in op:
        return op
    
    # Check for Google Docs API format: {insertText: {location: {index: X}, text: "..."}}
    if "insertText" in op:
        insert_data = op["insertText"]
        if isinstance(insert_data, dict):
            location = insert_data.get("location", {})
            index = location.get("index", 1) if isinstance(location, dict) else 1
            text = insert_data.get("text", "")
            return {"type": "INSERT_TEXT", "text": text, "index": index}
    
    # Check for simplified format: {insertText: {text: "...", index: X}}
    if "insertText" in op:
        insert_data = op["insertText"]
        if isinstance(insert_data, dict):
            text = insert_data.get("text", "")
            index = insert_data.get("index", 1)
            return {"type": "INSERT_TEXT", "text": text, "index": index}
    
    # Check for deleteContentRange format
    if "deleteContentRange" in op:
        delete_data = op["deleteContentRange"]
        if isinstance(delete_data, dict):
            range_data = delete_data.get("range", {})
            if isinstance(range_data, dict):
                start_index = range_data.get("startIndex")
                end_index = range_data.get("endIndex")
                if start_index is not None and end_index is not None:
                    return {"type": "DELETE_TEXT", "startIndex": start_index, "endIndex": end_index}
    
    # Check for simplified delete format: {deleteContentRange: {startIndex: X, endIndex: Y}}
    if "deleteContentRange" in op:
        delete_data = op["deleteContentRange"]
        if isinstance(delete_data, dict):
            start_index = delete_data.get("startIndex")
            end_index = delete_data.get("endIndex")
            if start_index is not None and end_index is not None:
                return {"type": "DELETE_TEXT", "startIndex": start_index, "endIndex": end_index}
    
    # Check for insertParagraphBreak format
    if "insertParagraphBreak" in op:
        break_data = op["insertParagraphBreak"]
        if isinstance(break_data, dict):
            location = break_data.get("location", {})
            index = location.get("index", 1) if isinstance(location, dict) else 1
            return {"type": "INSERT_PARAGRAPH_BREAK", "index": index}
    
    # If it has common fields, try to infer the type
    if "text" in op or "content" in op:
        text = op.get("text") or op.get("content", "")
        index = op.get("index", 1)
        return {"type": "INSERT_TEXT", "text": text, "index": index}
    
    if "startIndex" in op and "endIndex" in op:
        return {"type": "DELETE_TEXT", "startIndex": op["startIndex"], "endIndex": op["endIndex"]}
    
    # Return as-is if we can't normalize it (might be in correct format already)
    return op


def _parse_operations(operations: Any) -> list:
    """Parse operations parameter - can be array, string, or JSON string."""
    if not operations:
        return []
    
    parsed_ops = []
    
    # Already a list
    if isinstance(operations, list):
        parsed_ops = operations
    
    # String - try to parse as JSON
    elif isinstance(operations, str):
        ops_str = operations.strip()
        
        # Remove markdown code blocks if present
        if ops_str.startswith("```"):
            # Try to extract JSON from markdown code block
            match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', ops_str, re.DOTALL)
            if match:
                ops_str = match.group(1)
            else:
                # Remove the code block markers
                ops_str = re.sub(r'^```[a-z]*\s*', '', ops_str, flags=re.MULTILINE)
                ops_str = re.sub(r'\s*```$', '', ops_str, flags=re.MULTILINE)
        
        # Try parsing as JSON array
        try:
            parsed = json.loads(ops_str)
            if isinstance(parsed, list):
                parsed_ops = parsed
            elif isinstance(parsed, dict):
                parsed_ops = [parsed]
        except (json.JSONDecodeError, ValueError):
            # Try to find array in the string
            start_idx = ops_str.find("[")
            end_idx = ops_str.rfind("]")
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                try:
                    array_str = ops_str[start_idx:end_idx + 1]
                    parsed = json.loads(array_str)
                    if isinstance(parsed, list):
                        parsed_ops = parsed
                    elif isinstance(parsed, dict):
                        parsed_ops = [parsed]
                except (json.JSONDecodeError, ValueError):
                    pass
    
    # Try to convert to list if it's a dict (single operation)
    elif isinstance(operations, dict):
        parsed_ops = [operations]
    
    # Normalize all operations
    normalized_ops = []
    for op in parsed_ops:
        normalized = _normalize_operation(op)
        if normalized:
            normalized_ops.append(normalized)
    
    return normalized_ops


async def gdocs_tool(
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
    """
    Google Docs tool - Unified DSL wrapper.
    Handles document operations: create, read, update, format, and delete.
    """
    context = user_input if isinstance(user_input, dict) else {}
    action = (context.get("action") or "").upper()
    params = context.get("params") or {}

    if not action:
        raise ToolExecutionError(tool_name="docs", detail="Google Docs tool requires an action (CREATE, READ, UPDATE, FORMAT, DELETE).")

    creds_payload = credentials or {}
    if not creds_payload and connection is not None:
        try:
            creds_payload = connection.get_credentials()
        except Exception:
            creds_payload = {}

    # Try to ensure Docs API is enabled automatically
    if _has_api_manager:
        try:
            api_manager = get_api_manager()
            if api_manager:
                enabled = api_manager.ensure_api_enabled("docs")
                if enabled:
                    await asyncio.sleep(0.5)
        except Exception:
            # Non-fatal - continue even if API enabling fails
            pass

    client = GoogleDocsClient(creds_payload)

    if action == "CREATE":
        title = params.get("title") or params.get("name")
        if not title:
            raise ToolExecutionError(tool_name="docs", detail="docs CREATE requires params.title or params.name.")
        folder_id = params.get("folderId") or params.get("folder_id")
        result = await _execute_docs_call(lambda: client.create_document(title, folder_id))
        document_id = result.get("documentId")
        
        # Instantly batch update any operations if supplied
        operations_raw = params.get("operations")
        if document_id and operations_raw:
            await _execute_docs_call(lambda: client.batch_update(document_id, operations_raw))

        console.tool(f"[DOCS CREATE] Created document: {title} (ID: {document_id})", task_id=task_id, agent_id=agent_id)
        return {
            "message": f"Document '{title}' created successfully",
            "document_id": document_id,
            "title": title,
        }

    if action == "READ":
        document_id = params.get("documentId") or params.get("document_id") or params.get("id")
        if not document_id:
            raise ToolExecutionError(tool_name="docs", detail="docs READ requires params.documentId.")
        doc = await _execute_docs_call(lambda: client.get_document(document_id))
        title = doc.get("title", "")
        body = doc.get("body", {})
        
        # Extract text content
        def extract_text(element):
            if "paragraph" in element:
                para = element["paragraph"]
                text = ""
                for elem in para.get("elements", []):
                    if "textRun" in elem:
                        text += elem["textRun"].get("content", "")
                return text
            elif "table" in element:
                # Extract table content
                table_text = ""
                for row in element["table"].get("tableRows", []):
                    row_text = ""
                    for cell in row.get("tableCells", []):
                        cell_text = ""
                        for elem in cell.get("content", []):
                            if "paragraph" in elem:
                                for para_elem in elem["paragraph"].get("elements", []):
                                    if "textRun" in para_elem:
                                        cell_text += para_elem["textRun"].get("content", "")
                        row_text += cell_text + "\t"
                    table_text += row_text.rstrip("\t") + "\n"
                return table_text
            return ""
        
        content_text = ""
        for element in body.get("content", []):
            content_text += extract_text(element)
        
        console.tool(f"[DOCS READ] Read document: {title}", task_id=task_id, agent_id=agent_id)
        return {
            "message": f"Read document '{title}'",
            "document_id": document_id,
            "title": title,
            "content": content_text.strip(),
            "full_document": doc,
        }

    if action == "UPDATE":
        document_id = params.get("documentId") or params.get("document_id") or params.get("id")
        if not document_id:
            raise ToolExecutionError(tool_name="docs", detail="docs UPDATE requires params.documentId.")
        
        operations_raw = params.get("operations") or params.get("ops") or []
        
        # Check if operations are already in native Google Docs API format
        # (e.g., from DocsLibrary._markdown_to_ops which generates insertText,
        # updateTextStyle, updateParagraphStyle, createParagraphBullets directly)
        NATIVE_API_KEYS = {
            "insertText", "updateTextStyle", "updateParagraphStyle",
            "createParagraphBullets", "deleteContentRange",
            "insertParagraphBreak", "insertInlineImage",
            "insertTable", "insertTableRow", "insertTableColumn",
            "deleteTableRow", "deleteTableColumn", "mergeTableCells",
            "unmergeTableCells", "updateTableCellStyle",
            "updateTableColumnProperties", "updateTableRowStyle",
            "replaceAllText", "updateDocumentStyle",
        }
        
        is_native = False
        if isinstance(operations_raw, list) and operations_raw:
            first_op = operations_raw[0]
            if isinstance(first_op, dict):
                is_native = bool(set(first_op.keys()) & NATIVE_API_KEYS)
        
        if is_native:
            # Ops are already valid Google Docs API requests — send directly
            requests = operations_raw
        else:
            # Legacy path: normalize simplified ops into API format
            operations = _parse_operations(operations_raw)
            
            if not operations:
                raise ToolExecutionError(tool_name="docs", detail="docs UPDATE requires params.operations (array of operation objects).")
            
            requests = []
            for op in operations:
                op_type = op.get("type") or op.get("action", "").upper()
                
                if op_type == "INSERT_TEXT":
                    text = op.get("text") or op.get("content", "")
                    index = op.get("index")
                    requests.append({
                        "insertText": {
                            "location": {"index": index if index is not None else 1},
                            "text": text,
                        }
                    })
                
                elif op_type == "DELETE_TEXT":
                    start_index = op.get("startIndex")
                    end_index = op.get("endIndex")
                    if start_index is None or end_index is None:
                        raise ToolExecutionError(tool_name="docs", detail="DELETE_TEXT requires startIndex and endIndex.")
                    requests.append({
                        "deleteContentRange": {
                            "range": {
                                "startIndex": start_index,
                                "endIndex": end_index,
                            }
                        }
                    })
                
                elif op_type == "INSERT_PARAGRAPH_BREAK":
                    index = op.get("index", 1)
                    requests.append({
                        "insertParagraphBreak": {
                            "location": {"index": index},
                        }
                    })
        
        if requests:
            result = await _execute_docs_call(lambda: client.batch_update(document_id, requests))
            console.tool(f"[DOCS UPDATE] Applied {len(requests)} operation(s)", task_id=task_id, agent_id=agent_id)
            return {
                "message": f"Applied {len(requests)} operation(s) to document",
                "document_id": document_id,
                "operations_applied": len(requests),
            }
        else:
            raise ToolExecutionError(tool_name="docs", detail="No valid operations provided.")

    if action == "FORMAT":
        document_id = params.get("documentId") or params.get("document_id") or params.get("id")
        if not document_id:
            raise ToolExecutionError(tool_name="docs", detail="docs FORMAT requires params.documentId.")
        
        start_index = params.get("startIndex") or params.get("start_index")
        end_index = params.get("endIndex") or params.get("end_index")
        if start_index is None or end_index is None:
            raise ToolExecutionError(tool_name="docs", detail="docs FORMAT requires params.startIndex and params.endIndex.")
        
        # Text formatting
        bold = params.get("bold")
        italic = params.get("italic")
        underline = params.get("underline")
        strikethrough = params.get("strikethrough")
        font_size = params.get("fontSize") or params.get("font_size")
        foreground_color = _parse_color(params.get("foregroundColor") or params.get("foreground_color") or params.get("color"))
        background_color = _parse_color(params.get("backgroundColor") or params.get("background_color"))
        font_family = params.get("fontFamily") or params.get("font_family")
        
        # Paragraph formatting
        named_style = params.get("namedStyle") or params.get("named_style") or params.get("style")
        alignment = params.get("alignment")
        line_spacing = params.get("lineSpacing") or params.get("line_spacing")
        space_above = params.get("spaceAbove") or params.get("space_above")
        space_below = params.get("spaceBelow") or params.get("space_below")
        
        requests = []
        
        # Text style update
        if any([bold is not None, italic is not None, underline is not None, strikethrough is not None,
                font_size is not None, foreground_color is not None, background_color is not None, font_family is not None]):
            text_style = {}
            if bold is not None:
                text_style["bold"] = bool(bold)
            if italic is not None:
                text_style["italic"] = bool(italic)
            if underline is not None:
                text_style["underline"] = bool(underline)
            if strikethrough is not None:
                text_style["strikethrough"] = bool(strikethrough)
            if font_size is not None:
                text_style["fontSize"] = {"magnitude": float(font_size), "unit": "PT"}
            if foreground_color is not None:
                text_style["foregroundColor"] = {"color": {"rgbColor": foreground_color}}
            if background_color is not None:
                text_style["backgroundColor"] = {"color": {"rgbColor": background_color}}
            if font_family is not None:
                text_style["weightedFontFamily"] = {"fontFamily": font_family}
            
            requests.append({
                "updateTextStyle": {
                    "range": {
                        "startIndex": start_index,
                        "endIndex": end_index,
                    },
                    "textStyle": text_style,
                    "fields": ",".join(text_style.keys()),
                }
            })
        
        # Paragraph style update
        if any([named_style is not None, alignment is not None, line_spacing is not None,
                space_above is not None, space_below is not None]):
            paragraph_style = {}
            if named_style is not None:
                paragraph_style["namedStyleType"] = str(named_style).upper()
            if alignment is not None:
                paragraph_style["alignment"] = str(alignment).upper()
            if line_spacing is not None:
                paragraph_style["lineSpacing"] = float(line_spacing)
            if space_above is not None:
                paragraph_style["spaceAbove"] = {"magnitude": float(space_above), "unit": "PT"}
            if space_below is not None:
                paragraph_style["spaceBelow"] = {"magnitude": float(space_below), "unit": "PT"}
            
            requests.append({
                "updateParagraphStyle": {
                    "range": {
                        "startIndex": start_index,
                        "endIndex": end_index,
                    },
                    "paragraphStyle": paragraph_style,
                    "fields": ",".join(paragraph_style.keys()),
                }
            })
        
        if requests:
            result = await _execute_docs_call(lambda: client.batch_update(document_id, requests))
            console.tool(f"[DOCS FORMAT] Applied formatting", task_id=task_id, agent_id=agent_id)
            return {
                "message": "Formatting applied successfully",
                "document_id": document_id,
            }
        else:
            raise ToolExecutionError(tool_name="docs", detail="No formatting options provided.")

    if action == "DELETE":
        document_id = params.get("documentId") or params.get("document_id") or params.get("id")
        if not document_id:
            raise ToolExecutionError(tool_name="docs", detail="docs DELETE requires params.documentId.")
        
        # Use Drive API to delete
        try:
            client.drive_service.files().delete(fileId=document_id).execute()
            console.tool(f"[DOCS DELETE] Deleted document: {document_id}", task_id=task_id, agent_id=agent_id)
            return {
                "message": "Document deleted successfully",
                "document_id": document_id,
            }
        except Exception as e:
            raise GoogleDocsError(f"Failed to delete document: {e}")

    raise ToolExecutionError(tool_name="docs", detail=f"Unsupported docs action '{action}'.")

