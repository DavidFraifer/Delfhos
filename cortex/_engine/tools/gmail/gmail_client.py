"""
Utility helpers for interacting with the Gmail API from CORTEX agents.

This module mirrors the configuration used by the FastAPI Gmail service but adds
support for reading email content so agents can reason over real inbox data.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime, getaddresses
from typing import Dict, Iterable, List, Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import mimetypes
from pathlib import Path
from delfhos.errors import ToolExecutionError

DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
]


class GmailToolError(ToolExecutionError):
    """Raised when the Gmail tool cannot execute as requested."""

    def __init__(self, message: str):
        super().__init__(tool_name="gmail", detail=message)


@dataclass
class GmailMessage:
    """Light-weight representation of a Gmail message returned to the agent."""

    id: str
    thread_id: str
    subject: str
    sender: str
    snippet: str
    date: datetime
    body_text: str = ""
    body_html: str = ""
    to: List[str] = field(default_factory=list)
    cc: List[str] = field(default_factory=list)
    attachments: List[Dict[str, str]] = field(default_factory=list)  # attachment_id, filename, mime_type, size

    def permalink(self) -> str:
        # Direct link the user can click inside Gmail
        return f"https://mail.google.com/mail/u/0/#all/{self.id}"


def _normalise_scopes(scopes: Optional[Iterable[str]]) -> List[str]:
    if not scopes:
        return DEFAULT_SCOPES
    if isinstance(scopes, str):
        return [scope.strip() for scope in scopes.split() if scope.strip()]
    return list(scopes) or DEFAULT_SCOPES



_GMAIL_CLIENT_CACHE = {}

class GmailClient:
    """
    Minimal Gmail client wrapper that can be initialised either from a saved Connection
    (preferred) or from environment variables configured for the platform-wide Gmail integration.
    """

    def __init__(
        self,
        credentials_payload: Optional[Dict[str, str]] = None,
        scopes: Optional[Iterable[str]] = None,
    ):
        self._credentials_payload = credentials_payload or {}
        self._scopes_override = scopes
        self._service = None
        self._credentials = None

    def _build_credentials(self):
        payload = self._credentials_payload

        client_id = (
            payload.get("client_id")
            or os.getenv("GMAIL_CLIENT_ID")
        )
        client_secret = (
            payload.get("client_secret")
            or os.getenv("GMAIL_CLIENT_SECRET")
        )
        refresh_token = (
            payload.get("refresh_token")
            or os.getenv("GMAIL_REFRESH_TOKEN")
        )
        access_token = payload.get("access_token")

        cache_key = f"{client_id}:{refresh_token}:{access_token}"
        if cache_key in _GMAIL_CLIENT_CACHE:
            self._credentials, self._service = _GMAIL_CLIENT_CACHE[cache_key]
            return

        token_uri = payload.get("token_uri") or "https://oauth2.googleapis.com/token"
        scopes_source = self._scopes_override or payload.get("scopes")
        scopes = _normalise_scopes(scopes_source)

        if not all([client_id, client_secret, refresh_token]):
            raise GmailToolError(
                "Gmail credentials not configured. Connect a Gmail account first."
            )

        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
        )

        if not credentials.valid:
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())

        self._credentials = credentials
        # Disable the discovery cache to avoid file system writes in serverless envs
        self._service = build(
            "gmail",
            "v1",
            credentials=self._credentials,
            cache_discovery=False,
        )
        _GMAIL_CLIENT_CACHE[cache_key] = (self._credentials, self._service)

    def _ensure_service(self):
        if not self._service:
            self._build_credentials()
        elif self._credentials and self._credentials.expired and self._credentials.refresh_token:
            self._credentials.refresh(Request())

    def _fetch_thread_id(self, message_id: str) -> Optional[str]:
        """Fetch threadId for a message, returning None if lookup fails."""
        if not message_id:
            return None
        try:
            self._ensure_service()
            # Use minimal format to reduce payload size and speed up the request
            message = (
                self._service.users()
                .messages()
                .get(userId="me", id=message_id, format="minimal", fields="threadId")
                .execute()
            )
            return message.get("threadId")
        except Exception:
            return None

    def send_message(
        self,
        to: List[str],
        subject: str,
        body: str,
        *,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        email_format: str = "plain",
        in_reply_to: Optional[str] = None,
        draft: bool = False,
        send_at: Optional[str] = None,
        attachments: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """
        Send (or save draft of) an email using the authenticated account.

        Args:
            to: List of recipient email addresses.
            subject: Email subject.
            body: Email body content.
            cc: Optional CC recipients.
            bcc: Optional BCC recipients.
            email_format: "plain" or "html".
            in_reply_to: Optional Gmail message ID to reply to.
            draft: If True, save as draft instead of sending immediately.
            send_at: Future send scheduling timestamp (ISO-8601). Not currently supported.
            attachments: Optional list of file paths to attach to the email.
        """
        if not to:
            raise GmailToolError("No recipients provided for email send.")

        if send_at:
            raise GmailToolError("Scheduled sends are not yet supported.")

        lower_format = (email_format or "plain").strip().lower()
        if lower_format not in {"plain", "html"}:
            raise GmailToolError(f"Unsupported email format '{email_format}'. Use 'plain' or 'html'.")

        self._ensure_service()

        normalized_subject = (subject or "").replace("\\n", " ").replace("/n", " ")
        normalized_subject = normalized_subject.replace("\r\n", " ").strip()

        normalized_body = body or ""
        normalized_body = (
            normalized_body.replace("\r\n", "\n")
            .replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("/n", "\n")
        )
        if lower_format == "html":
            normalized_body = normalized_body.replace("\n", "<br>")

        if lower_format == "html":
            mime_body = MIMEText(normalized_body, "html", "utf-8")
        else:
            mime_body = MIMEText(normalized_body, "plain", "utf-8")

        message = MIMEMultipart()
        message.attach(mime_body)

        message["To"] = ", ".join(to)
        message["Subject"] = normalized_subject
        if cc:
            message["Cc"] = ", ".join(cc)
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
            message["References"] = in_reply_to

        # Gmail automatically strips Bcc headers before delivery, but we include them for completeness
        if bcc:
            message["Bcc"] = ", ".join(bcc)

        # Attach files if provided
        if attachments:
            for file_path in attachments:
                try:
                    path = Path(file_path)
                    if not path.exists():
                        raise GmailToolError(f"Attachment file not found: {file_path}")
                    
                    # Guess MIME type
                    mime_type, _ = mimetypes.guess_type(file_path)
                    if mime_type is None:
                        mime_type = 'application/octet-stream'
                    
                    main_type, sub_type = mime_type.split('/', 1)
                    
                    # Read file and create attachment
                    with open(file_path, 'rb') as f:
                        attachment_data = f.read()
                    
                    mime_attachment = MIMEBase(main_type, sub_type)
                    mime_attachment.set_payload(attachment_data)
                    encoders.encode_base64(mime_attachment)
                    mime_attachment.add_header(
                        'Content-Disposition',
                        f'attachment; filename="{path.name}"'
                    )
                    message.attach(mime_attachment)
                except Exception as e:
                    raise GmailToolError(f"Failed to attach file {file_path}: {str(e)}")

        # When replying, include threadId if possible for proper threading
        thread_id = None
        if in_reply_to:
            thread_id = self._fetch_thread_id(in_reply_to)

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        message_payload: Dict[str, str] = {"raw": raw_message}
        if thread_id:
            message_payload["threadId"] = thread_id

        try:
            if draft:
                result = (
                    self._service.users()
                    .drafts()
                    .create(userId="me", body={"message": message_payload})
                    .execute()
                )
                return {
                    "status": "draft",
                    "id": result.get("id", ""),
                    "message_id": result.get("message", {}).get("id", ""),
                }

            result = (
                self._service.users()
                .messages()
                .send(userId="me", body=message_payload)
                .execute()
            )
            return {
                "status": "sent",
                "id": result.get("id", ""),
                "threadId": result.get("threadId", ""),
            }
        except HttpError as exc:
            raise GmailToolError(f"Gmail API error while sending message: {exc}") from exc
        except Exception as exc:
            raise GmailToolError(str(exc)) from exc

    def _extract_bodies(self, payload: Optional[dict]) -> (str, str):
        """Extract plain-text and HTML bodies from a Gmail message payload."""
        if not payload:
            return "", ""

        mime_type = payload.get("mimeType", "")
        body = payload.get("body", {})
        data = body.get("data")
        if data:
            padded = data + "=" * (-len(data) % 4)
            decoded_bytes = base64.urlsafe_b64decode(padded.encode("utf-8"))
            
            # Try multiple encodings to handle emails properly
            decoded_text = None
            for encoding in ['utf-8', 'iso-8859-1', 'windows-1252', 'latin1']:
                try:
                    decoded_text = decoded_bytes.decode(encoding)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            
            # Fallback if all encodings fail
            if decoded_text is None:
                decoded_text = decoded_bytes.decode('utf-8', errors='replace')
            
            if mime_type == "text/html":
                return "", decoded_text
            if mime_type == "text/plain":
                return decoded_text, ""
            # Fallback: treat as plain text
            return decoded_text, ""

        parts = payload.get("parts", []) or []
        text_result = ""
        html_result = ""
        for part in parts:
            part_text, part_html = self._extract_bodies(part)
            if part_text and not text_result:
                text_result = part_text
            if part_html and not html_result:
                html_result = part_html
            if text_result and html_result:
                break

        return text_result, html_result

    def _extract_attachments(self, payload: Optional[dict], message_id: str) -> List[Dict[str, str]]:
        """
        Extract attachment metadata from a Gmail message payload.
        
        Returns:
            List of dicts with keys: attachment_id, filename, mime_type, size
            
        NOTE:
        - Gmail can represent inline images (embedded in the HTML body) as parts with an
          attachmentId but sometimes with an empty filename.
        - Previously we only kept parts that had BOTH attachmentId and filename, which meant
          some inline image invoices were invisible to the agent.
        - We now also treat image/* parts with an attachmentId as attachments, even if the
          filename is empty, by synthesising a reasonable filename.
        """
        if not payload:
            return []
        
        attachments: List[Dict[str, str]] = []
        parts = payload.get("parts", []) or []
        
        def _scan_parts(parts_list, msg_id: str):
            from pathlib import Path  # local import to avoid top‑level dependency for simple usage
            
            for part in parts_list:
                # Check if this part has attachment-like data
                body = part.get("body", {}) or {}
                attachment_id = body.get("attachmentId")
                filename = part.get("filename", "") or ""
                mime_type = part.get("mimeType", "application/octet-stream") or "application/octet-stream"
                
                # Decide if this part should be treated as an attachment:
                # - Standard attachments: have attachmentId AND non-empty filename
                # - Inline images: have attachmentId, mime_type starts with image/*, but filename may be empty
                is_image_inline = bool(attachment_id and mime_type.lower().startswith("image/") and not filename)
                is_regular_attachment = bool(attachment_id and filename)
                
                if is_regular_attachment or is_image_inline:
                    # Synthesize filename for inline images without one
                    final_filename = filename
                    if not final_filename:
                        # Derive extension from MIME type (e.g., image/png -> .png)
                        ext = ""
                        try:
                            main_type, sub_type = mime_type.split("/", 1)
                            if sub_type:
                                # Avoid things like "jpeg; charset=binary"
                                clean_sub = sub_type.split(";", 1)[0].strip()
                                ext = f".{clean_sub}" if clean_sub else ""
                        except Exception:
                            ext = ""
                        # Use a stable synthetic name including message id and current index
                        index = len(attachments) + 1
                        final_filename = f"inline_image_{msg_id}_{index}{ext}"
                    
                    attachments.append(
                        {
                            "attachment_id": attachment_id,
                            "filename": final_filename,
                            "mime_type": mime_type,
                            "size": body.get("size", 0),
                            "message_id": msg_id,
                        }
                    )
                
                # Recursively check nested parts
                nested_parts = part.get("parts", []) or []
                if nested_parts:
                    _scan_parts(nested_parts, msg_id)
        
        _scan_parts(parts, message_id)
        return attachments

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """
        Download an attachment from a Gmail message.
        
        Args:
            message_id: Gmail message ID
            attachment_id: Attachment ID from the message
            
        Returns:
            bytes: Raw attachment data
        """
        try:
            self._ensure_service()
        except Exception as exc:
            raise GmailToolError(str(exc)) from exc
        
        try:
            attachment = (
                self._service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )
            
            data = attachment.get("data", "")
            if not data:
                raise GmailToolError(f"No data found for attachment {attachment_id}")
            
            # Decode base64url
            padded = data + "=" * (-len(data) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("utf-8"))
            return decoded
        except HttpError as exc:
            raise GmailToolError(f"Gmail API error downloading attachment: {exc}") from exc
        except Exception as exc:
            raise GmailToolError(f"Error downloading attachment: {str(exc)}") from exc

    def search_messages(self, query: str, max_results: int = 5, include_body: bool = False, include_attachments: bool = False) -> List[GmailMessage]:
        """
        Search the inbox using Gmail search syntax.

        Args:
            query: Gmail search query (e.g. "subject:report newer_than:7d")
            max_results: limit number of emails returned
            include_body: when True, fetch message bodies (plain text & HTML)
        """
        try:
            self._ensure_service()
        except Exception as exc:
            raise GmailToolError(str(exc)) from exc

        try:
            response = (
                self._service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
        except HttpError as exc:
            raise GmailToolError(f"Gmail API error: {exc}") from exc

        messages_meta = response.get("messages", [])
        results: List[GmailMessage] = []

        if not messages_meta:
            return results

        # Use BatchHttpRequest to fetch all messages in a single HTTP request
        # This reduces N sequential requests to 1 batched request
        message_ids = [meta.get("id") for meta in messages_meta if meta.get("id")]
        if not message_ids:
            return results

        # Store raw message data from batch response
        raw_messages: Dict[str, dict] = {}

        def batch_callback(request_id: str, response: dict, exception):
            """Callback for each individual request in the batch."""
            if exception is not None:
                # Skip failed requests (same as original behavior)
                return
            if response:
                msg_id = response.get("id")
                if msg_id:
                    raw_messages[msg_id] = response

        # Create batch request
        batch = self._service.new_batch_http_request(callback=batch_callback)
        
        for msg_id in message_ids:
            request = (
                self._service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg_id,
                    format="full" if include_body else "metadata",
                    metadataHeaders=["Subject", "From", "To", "Cc", "Date"],
                )
            )
            batch.add(request, request_id=msg_id)

        try:
            batch.execute()
        except HttpError as exc:
            raise GmailToolError(f"Gmail batch API error: {exc}") from exc

        # Process messages in original order
        for msg_id in message_ids:
            message = raw_messages.get(msg_id)
            if not message:
                continue

            payload = message.get("payload", {}) or {}
            headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
            subject = headers.get("Subject", "(no subject)")
            sender = headers.get("From", "Unknown sender")
            snippet = message.get("snippet", "").strip()
            raw_to = headers.get("To", "")
            raw_cc = headers.get("Cc", "")
            to_addresses = [addr for _, addr in getaddresses([raw_to])] if raw_to else []
            cc_addresses = [addr for _, addr in getaddresses([raw_cc])] if raw_cc else []
            raw_date = headers.get("Date")
            try:
                date = parsedate_to_datetime(raw_date) if raw_date else datetime.utcnow()
                if date.tzinfo:
                    date = date.astimezone().replace(tzinfo=None)
            except Exception:
                date = datetime.utcnow()

            body_text = ""
            body_html = ""
            if include_body:
                body_text, body_html = self._extract_bodies(payload)
            
            # Extract attachment metadata if requested
            attachment_info = []
            if include_attachments:
                attachment_info = self._extract_attachments(payload, msg_id)

            results.append(
                GmailMessage(
                    id=msg_id,
                    thread_id=message.get("threadId", ""),
                    subject=subject,
                    sender=sender,
                    snippet=snippet,
                    date=date,
                    body_text=body_text,
                    body_html=body_html,
                    to=to_addresses,
                    cc=cc_addresses,
                )
            )
            
            # Store attachment info in a custom attribute (GmailMessage doesn't have this field)
            if attachment_info:
                results[-1].attachments = attachment_info  # type: ignore

        return results


