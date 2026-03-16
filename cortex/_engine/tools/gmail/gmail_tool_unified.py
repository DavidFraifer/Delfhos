"""
Unified Gmail Tool - Direct DSL execution without internal parsing
Accepts action/params from orchestrator's unified DSL
"""

import re
import json
from datetime import datetime, timedelta
from email.utils import parseaddr
from typing import Dict, Any, List, Optional

from ...utils.console import console
from ...connection import get_connection_manager, Connection
from .gmail_client import GmailClient, GmailToolError


def _clean_email_content(body_text: str = "", body_html: str = "", snippet: str = "") -> str:
    """
    Strip HTML/CSS from email bodies and clean up special characters.
    Prefer HTML when present (Gmail often provides richer/cleaner HTML than text parts).
    """
    import html
    
    candidate = ""

    # Prefer HTML if available; fall back to plain text, then snippet
    if body_html and body_html.strip():
        text = body_html
        text = re.sub(r"(?is)<(script|style).*?>.*?(</\1>)", "", text)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</p>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        candidate = text
    elif body_text and body_text.strip():
        candidate = body_text
    elif snippet and snippet.strip():
        candidate = snippet
    else:
        return ""

    # Decode HTML entities (&amp; → &, etc.)
    candidate = html.unescape(candidate)
    
    # Remove zero-width and invisible characters (often used by LinkedIn, marketing emails)
    # U+034F Combining Grapheme Joiner, U+200B-U+200F, U+2028-U+202F, U+FEFF BOM
    candidate = re.sub(r'[\u034f\u200b-\u200f\u2028-\u202f\ufeff]', '', candidate)
    
    # Replace non-breaking spaces with regular spaces
    candidate = candidate.replace('\xa0', ' ')
    
    # Normalize whitespace: multiple spaces → single space
    candidate = re.sub(r"[ \t]+", " ", candidate)
    
    # Normalize newlines: multiple empty lines → double newline
    candidate = re.sub(r"\n\s*\n+", "\n\n", candidate)
    
    # Clean up lines with only spaces
    candidate = re.sub(r"\n +\n", "\n\n", candidate)
    
    return candidate.strip()


async def gmail_tool_unified(
    user_input: str = "",
    task_id: str = None,
    light_llm: str = None,
    heavy_llm: str = None,
    agent_id: str = None,
    validation_mode: bool = False,
    credentials: dict = None,
    connection: Connection = None,
    logger: Any = None,
    **kwargs: Any,
):
    """
    Unified Gmail tool that executes actions directly from orchestrator DSL.
    
    Expected input format (dict):
    {
        "action": "READ" | "SEND",
        "params": {...},
        "message": "original user message",
        "current_date": "YYYY-MM-DD",
        "current_time": "HH:MM TZ"
    }
    """
    
    # Extract unified DSL parameters
    action = None
    params = {}
    current_date = None
    current_time = None
    
    if isinstance(user_input, dict):
        action = user_input.get("action")
        params = user_input.get("params", {})
        current_date = user_input.get("current_date")
        current_time = user_input.get("current_time")
        message = user_input.get("message", "")
    else:
        message = str(user_input or "")
    
    # Get connection and permissions
    permissions = set()
    selected_conn = None
    credentials_payload = None
    
    if connection:
        selected_conn = connection
        if connection.is_action_allowed("read"):
            permissions.add("READ")
        if connection.is_action_allowed("send"):
            permissions.add("SEND")
    
    if credentials:
        credentials_payload = credentials
        permissions.add("READ")
        scopes = credentials.get("scopes") if isinstance(credentials, dict) else None
        if scopes:
            scope_set = {scope.lower() for scope in scopes} if isinstance(scopes, list) else {scopes.lower()}
            if any("gmail.send" in scope or "gmail.modify" in scope for scope in scope_set):
                permissions.add("SEND")
    
    # Get available connections if not provided
    if not selected_conn and not credentials_payload:
        try:
            manager = get_connection_manager()
            connections = manager.get_connections_by_tool("gmail")
            for conn in connections:
                if conn.is_active():
                    if conn.is_action_allowed("read"):
                        permissions.add("READ")
                        if not selected_conn:
                            selected_conn = conn
                            credentials_payload = conn.get_credentials()
                    if conn.is_action_allowed("send"):
                        permissions.add("SEND")
        except Exception:
            pass
    
    if not permissions:
        return "No Gmail connection with required permissions. Please connect a Gmail account."
    
    # Validate action permission
    if action and action.upper() not in permissions:
        return f"Action '{action}' not allowed. Available actions: {', '.join(permissions)}"
    
    # [SANDBOX INTERCEPTOR]
    if selected_conn and getattr(selected_conn, "is_sandbox", False):
        if not action:
            return "No action specified. Use 'action' parameter (e.g., action:\"READ\")"
        action = action.upper()
        if action == "READ":
            messages = selected_conn.mock_search_emails(params.get("query", ""), params.get("max", 10))
            if params.get("return_structured", False):
                return messages
            if not messages:
                return "No emails found in INBOX."
            return f"Gmail results ({len(messages)} found):\\n" + "\\n".join([f"- {m['payload']['headers'][2]['value']} • {m['snippet'][:100]}..." for m in messages])
        elif action == "SEND":
            return selected_conn.mock_send_email(params.get("to", ""), params.get("subject", ""), params.get("body", ""))
        else:
            return f"Unknown action: {action}. Available actions: READ, SEND"

    # Initialize Gmail client
    try:
        if not credentials_payload and selected_conn:
            credentials_payload = selected_conn.get_credentials()
        
        if not credentials_payload:
            return "No Gmail credentials available. Please authenticate."
        
        # Extract scopes for client
        conn_scopes = None
        if selected_conn:
            conn_scopes = selected_conn.metadata.get("scopes")
        elif isinstance(credentials_payload, dict):
            conn_scopes = credentials_payload.get("scopes")
        
        gmail_client = GmailClient(credentials_payload, scopes=conn_scopes)
    except Exception as e:
        return f"Failed to initialize Gmail client: {str(e)}"
    
    # Execute action
    try:
        if not action:
            return "No action specified. Use 'action' parameter (e.g., action:\"READ\")"
        
        action = action.upper()
        
        if action == "READ":
            return await _execute_read(gmail_client, params, task_id, agent_id, credentials_payload, logger=logger)
        elif action == "SEND":
            return await _execute_send(gmail_client, params, task_id, agent_id)
        else:
            # Format beautiful error with available actions
            error_msg = (
                f"❌ Unknown Gmail action: '{action}'\n\n"
                f"📋 Available actions for Gmail:\n"
                f"    • READ - Fetch emails from inbox/sent/drafts/spam/trash\n"
                f"    • SEND - Send an email\n\n"
                f"💡 Use one of these actions in your next request."
            )
            console.error(f"[GMAIL ERROR]", error_msg, task_id=task_id, agent_id=agent_id)
            return error_msg
    
    except Exception as e:
        error_msg = f"Gmail {action} failed: {str(e)}"
        console.error(f"[GMAIL ERROR]", error_msg, task_id=task_id, agent_id=agent_id)
        return error_msg


async def _execute_read(
    gmail_client: GmailClient,
    params: Dict[str, Any],
    task_id: str,
    agent_id: str,
    credentials: dict,
    logger: Any = None,
) -> str:
    """
    Execute Gmail READ action.
    
    Params:
    - query: search keywords
    - max: max results (default 20)
    - from: ISO date (after)
    - to: ISO date (before)
    - mailbox: inbox/sent/drafts/spam/trash
    - include_body: true to fetch full content
    """
    
    # Build Gmail search query
    query_parts = []
    
    # Extract mailbox/folder — only add filter if user explicitly requests a specific folder
    mailbox = params.get("mailbox", "").lower()
    if mailbox and mailbox != "inbox":
        mailbox_map = {
            "sent": "in:sent",
            "drafts": "in:drafts",
            "spam": "in:spam",
            "trash": "in:trash",
            "all": "in:anywhere"
        }
        query_parts.append(mailbox_map.get(mailbox, f"in:{mailbox}"))
    # No default "in:inbox" — search all mail by default
    
    # Add date filters
    if "from" in params:
        from_date = params["from"]
        query_parts.append(f"after:{from_date}")
    if "to" in params:
        to_date = params["to"]
        query_parts.append(f"before:{to_date}")
    
    # Add search keywords — pass query as-is (do NOT split/quote, it breaks Gmail operators like from:, after:, newer_than:)
    if "query" in params and params["query"]:
        raw_query = params["query"]
        # Auto-convert newer_than/older_than to after/before if the LLM uses them for dates
        import re
        raw_query = re.sub(r'newer_than:(\d{4}[-/]\d{2}[-/]\d{2})', r'after:\1', raw_query)
        raw_query = re.sub(r'older_than:(\d{4}[-/]\d{2}[-/]\d{2})', r'before:\1', raw_query)
        query_parts.append(raw_query)
    
    # Combine query
    gmail_query = " ".join(query_parts)
    
    # Get max results
    max_results = int(params.get("max", 20))
    include_body = params.get("include_body", False)
    if isinstance(include_body, str):
        include_body = include_body.lower() in ("true", "yes", "1")
    
    include_attachments = params.get("include_attachments", False)
    if isinstance(include_attachments, str):
        include_attachments = include_attachments.lower() in ("true", "yes", "1")
    
    # Helper to strip HTML tags aggressively
    def _strip_html(text: str) -> str:
        import re
        if not text:
            return ""
        # Drop script/style blocks entirely
        text = re.sub(r"(?is)<(script|style).*?>.*?(</\1>)", "", text)
        # Replace breaks and paragraphs with newlines
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</p>", "\n", text)
        # Remove all remaining tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Remove CSS-like declarations that may remain as plain text
        text = re.sub(r"[#.\w][\w\-\s]*\{[^}]*\}", " ", text)  # selectors { ... }
        text = re.sub(r"\{[^}]*\}", " ", text)  # any leftover braces
        # Normalize spaces and newlines
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        return text.strip()

    # Search emails
    try:
        messages = gmail_client.search_messages(
            query=gmail_query,
            max_results=max_results,
            include_body=include_body,
            include_attachments=include_attachments
        )
    except Exception as e:
        raise GmailToolError(f"Gmail API error during search: {str(e)}")
    
    if not messages:
        # Return empty list if structured data requested, otherwise formatted message
        if params.get("return_structured", False):
            return []
        result = f"No emails found in {mailbox}."
        return result
    
    # Determine if emails are "sent" by checking credentials email
    user_email = credentials.get("email", "").lower() if credentials else ""
    
    # Check if caller wants structured data (for Python API) or formatted text (for DSL)
    return_structured = params.get("return_structured", False)
    if isinstance(return_structured, str):
        return_structured = return_structured.lower() in ("true", "yes", "1")
    
    # Format results as structured data (list of dicts) for Python API
    structured_results = []
    formatted_lines = []
    
    for msg in messages:
        # Determine if this is a sent message
        is_sent = False
        if mailbox == "sent":
            is_sent = True
        elif user_email and msg.sender:
            sender_email = parseaddr(msg.sender)[1].lower()
            is_sent = sender_email == user_email
        
        # Clean email body
        clean_body = ""
        if include_body:
            clean_body = _clean_email_content(msg.body_text, msg.body_html, msg.snippet)
            # Extra safety: strip any leftover HTML tags
            clean_body = _strip_html(clean_body or msg.body_html or msg.body_text or msg.snippet)
            body_sample = clean_body[:200] + "..." if len(clean_body) > 200 else clean_body
        else:
            body_sample = msg.snippet[:200] if msg.snippet else ""
        
        # Build structured email dict
        email_dict = {
            "id": msg.id or "",
            "subject": msg.subject or "(no subject)",
            "from_email": msg.sender or "",
            "to": msg.to or [],
            "date": str(msg.date) if msg.date else "",
            "snippet": msg.snippet or "",
            "body": clean_body if include_body else "",
            "body_html": msg.body_html or "",
            "is_sent": is_sent,
            "attachments": msg.attachments if hasattr(msg, 'attachments') and msg.attachments else []
        }
        structured_results.append(email_dict)
        
        # Also build formatted line for backward compatibility
        if is_sent:
            to_display = ", ".join(msg.to) if msg.to else "(no recipient)"
            line = f"- Sent to {to_display} • {msg.subject or '(no subject)'} • {msg.date}"
        else:
            line = f"- {msg.subject or '(no subject)'} • {msg.sender} • {msg.date}"
        
        if body_sample:
            line += f" • {body_sample}"
        
        formatted_lines.append(line)
    
    # Return structured data if requested, otherwise formatted text (for backward compatibility)
    if return_structured:
        return structured_results
    
    result_text = f"Gmail results ({len(messages)} found):\n" + "\n".join(formatted_lines)
    return result_text


async def _execute_send(
    gmail_client: GmailClient,
    params: Dict[str, Any],
    task_id: str,
    agent_id: str,
) -> str:
    """
    Execute Gmail SEND action.
    
    Params:
    - to: recipient(s) - string or list
    - subject: email subject
    - body: email body
    - reply_to: message ID to reply to (optional)
    - attachments: list of file paths to attach (optional)
    - cc: CC recipients (optional)
    - bcc: BCC recipients (optional)
    """
    import time
    
    # Extract parameters
    start_time = time.time()
    to_addrs = params.get("to", [])
    if isinstance(to_addrs, str):
        to_addrs = [addr.strip() for addr in to_addrs.split(",") if addr.strip()]
    elif not isinstance(to_addrs, list):
        to_addrs = [str(to_addrs)]
    
    if not to_addrs:
        return "No recipients specified. Use 'to' parameter."
    
    subject = params.get("subject", "")
    body = params.get("body", "")
    reply_to_id = params.get("reply_to")
    attachments = params.get("attachments")
    cc = params.get("cc")
    bcc = params.get("bcc")
    
    # Process CC/BCC if provided
    if cc and isinstance(cc, str):
        cc = [addr.strip() for addr in cc.split(",") if addr.strip()]
    if bcc and isinstance(bcc, str):
        bcc = [addr.strip() for addr in bcc.split(",") if addr.strip()]
    
    console.debug(f"[GMAIL PERF] Param extraction: {(time.time() - start_time)*1000:.1f}ms", task_id=task_id, agent_id=agent_id)
    
    # Send email
    try:
        send_start = time.time()
        gmail_client.send_message(
            to=to_addrs,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            in_reply_to=reply_to_id,
            attachments=attachments
        )
        send_duration = time.time() - send_start
        console.debug(f"[GMAIL PERF] Gmail API send: {send_duration*1000:.1f}ms", task_id=task_id, agent_id=agent_id)
        
        result = f"✉️ Email sent to {', '.join(to_addrs)}"
        if subject:
            result += f" • Subject: {subject}"
        if attachments:
            attachment_count = len(attachments) if isinstance(attachments, list) else 1
            result += f" • {attachment_count} attachment(s)"
        
        total_duration = time.time() - start_time
        console.debug(f"[GMAIL PERF] Total send time: {total_duration*1000:.1f}ms", task_id=task_id, agent_id=agent_id)
        
        return result
    
    except Exception as e:
        raise GmailToolError(f"Gmail API error while sending: {str(e)}")

