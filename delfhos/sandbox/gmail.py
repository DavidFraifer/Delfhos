from typing import List, Dict, Any, Optional
from cortex.connections.base import BaseConnection
from cortex._engine.connection import AuthType

import datetime

# Dummy email database
MOCK_EMAILS = [
    {
        "id": "msg_1001",
        "threadId": "thr_1001",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Hi there, could you please check on ticket TCK-8843 for Alice? The invoice seems to be overdue.",
        "payload": {
            "headers": [
                {"name": "From", "value": "manager@acmecorp.com"},
                {"name": "To", "value": "you@delfhos.sandbox"},
                {"name": "Subject", "value": "Follow up on Acme Corp invoice"},
                {"name": "Date", "value": "Wed, 10 Mar 2026 10:30:00 -0400"}
            ],
            "body": {
                "data": "SGkgdGhlcmUsCgpDb3VsZCB5b3UgcGxlYXNlIGNoZWNrIG9uIHRpY2tldCBUQ0stODg0MyBmb3IgQWxpY2U/IFRoZSBpbnZvaWNlIHNlZW1zIHRvIGJlIG92ZXJkdWUuCgpUaGFua3MsCk1hbmFnZXI=" 
            }
        }
    },
    {
        "id": "msg_1002",
        "threadId": "thr_1002",
        "labelIds": ["INBOX"],
        "snippet": "Your weekly report is ready to view.",
        "payload": {
            "headers": [
                {"name": "From", "value": "reports@system.local"},
                {"name": "To", "value": "you@delfhos.sandbox"},
                {"name": "Subject", "value": "Weekly Report"},
                {"name": "Date", "value": "Tue, 09 Mar 2026 08:00:00 -0400"}
            ],
            "body": {
                "data": "WW91ciB3ZWVrbHkgcmVwb3J0IGlzIHJlYWR5IHRvIHZpZXcu"
            }
        }
    }
]


class MockEmail(BaseConnection):
    """
    Mock Email connection that pretends to be Gmail but uses local dictionaries.
    Requires ZERO configuration. Perfect for testing and tutorials.
    """
    
    TOOL_NAME = "gmail"
    
    def __init__(self, name: str = "gmail"):
        super().__init__(
            credentials={"mock": True},
            actions=["READ", "SEND"], # Allow core actions
            name=name,
            auth_type=AuthType.NONE
        )
        self.is_sandbox = True
        self._sent_emails = []

    def mock_search_emails(self, query: str = "", max_results: int = 10):
        results = []
        q = query.lower()
        for msg in MOCK_EMAILS:
            # Check basic Gmail filters
            is_match = True
            if "is:unread" in q and "UNREAD" not in msg.get("labelIds", []):
                is_match = False
            if "in:inbox" in q and "INBOX" not in msg.get("labelIds", []):
                is_match = False
                
            clean_q = q.replace("is:unread", "").replace("in:inbox", "").strip()
            if clean_q and clean_q not in msg['snippet'].lower() and clean_q not in str(msg).lower():
                is_match = False
                
            if is_match:
                # Format to exactly match the native Gmail Tool structured dictionary
                subject = next((h["value"] for h in msg["payload"]["headers"] if h["name"] == "Subject"), "")
                from_email = next((h["value"] for h in msg["payload"]["headers"] if h["name"] == "From"), "")
                date_str = next((h["value"] for h in msg["payload"]["headers"] if h["name"] == "Date"), "")
                
                # Decode the base64 simulated body data 
                import base64
                body_data = msg["payload"]["body"]["data"]
                try:
                    body_text = base64.b64decode(body_data).decode("utf-8")
                except (ValueError, UnicodeDecodeError, base64.binascii.Error):
                    body_text = "Missing body."

                formatted_msg = {
                    "id": msg["id"],
                    "subject": subject,
                    "from_email": from_email,
                    "to": ["you@delfhos.sandbox"],
                    "date": date_str,
                    "snippet": msg["snippet"],
                    "body": body_text,
                    "body_html": body_text,
                    "is_sent": False,
                    "attachments": [],
                    "payload": msg["payload"] 
                }
                results.append(formatted_msg)
                
        return results[:max_results]
        
    def mock_get_email(self, message_id: str):
        for msg in MOCK_EMAILS:
            if msg["id"] == message_id:
                return msg
        return None
        
    def mock_send_email(self, to: str, subject: str, body: str):
        print(f"\\n[SANDBOX EMAIL] Pretending to send email to {to}...")
        print(f"Subject: {subject}")
        print(f"Body: {body[:100]}...\\n")
        self._sent_emails.append({"to": to, "subject": subject, "body": body})
        return f"Mock email sent to {to} successfully."
