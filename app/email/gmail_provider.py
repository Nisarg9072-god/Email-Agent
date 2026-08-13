"""Gmail email provider - isolated implementation for Google Workspace integration.

Requires OAuth credentials (credentials.json + token.json).
Not needed for the default mock demo.

Setup:
1. Create a Google Cloud project and enable Gmail API
2. Download OAuth credentials to credentials.json
3. Run OAuth flow once to generate token.json
4. Set EMAIL_PROVIDER=gmail in .env
"""

import logging

from app.email.base import EmailMessage, EmailProvider, EmailSummary

logger = logging.getLogger(__name__)


class GmailEmailProvider(EmailProvider):
    """Gmail API integration. Falls back gracefully if credentials unavailable."""

    def __init__(self, credentials_path: str, token_path: str):
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._service = None

    def _get_service(self):
        if self._service is not None:
            return self._service

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            raise RuntimeError(
                "Gmail dependencies not installed. "
                "Run: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client"
            )

        SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
        creds = None

        import os

        if os.path.exists(self._token_path):
            creds = Credentials.from_authorized_user_file(self._token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self._credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(self._token_path, "w") as token:
                token.write(creds.to_json())

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def get_email_count(self) -> int:
        service = self._get_service()
        result = service.users().messages().list(userId="me", q="is:unread").execute()
        return result.get("resultSizeEstimate", 0)

    def list_emails(self) -> list[EmailSummary]:
        service = self._get_service()
        result = service.users().messages().list(userId="me", q="is:unread").execute()
        messages = result.get("messages", [])
        summaries = []
        for msg in messages:
            detail = (
                service.users()
                .messages()
                .get(userId="me", id=msg["id"], format="metadata")
                .execute()
            )
            headers = {
                h["name"]: h["value"]
                for h in detail.get("payload", {}).get("headers", [])
            }
            summaries.append(
                EmailSummary(
                    email_id=msg["id"],
                    sender=headers.get("From", ""),
                    subject=headers.get("Subject", ""),
                )
            )
        return summaries

    def get_email(self, email_id: str) -> EmailMessage | None:
        service = self._get_service()
        try:
            detail = (
                service.users()
                .messages()
                .get(userId="me", id=email_id, format="full")
                .execute()
            )
        except Exception:
            logger.exception("Failed to fetch email %s", email_id)
            return None

        headers = {
            h["name"]: h["value"]
            for h in detail.get("payload", {}).get("headers", [])
        }
        body = self._extract_body(detail.get("payload", {}))

        return EmailMessage(
            email_id=email_id,
            sender=headers.get("From", ""),
            recipient=headers.get("To", ""),
            subject=headers.get("Subject", ""),
            body=body,
            thread_id=detail.get("threadId"),
        )

    def send_email(
        self, to: str, subject: str, body: str, thread_id: str | None = None
    ) -> bool:
        import base64
        from email.mime.text import MIMEText

        service = self._get_service()
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_body: dict = {"raw": raw}
        if thread_id:
            send_body["threadId"] = thread_id

        try:
            service.users().messages().send(userId="me", body=send_body).execute()
            return True
        except Exception:
            logger.exception("Failed to send email to %s", to)
            return False

    @staticmethod
    def _extract_body(payload: dict) -> str:
        if "body" in payload and payload["body"].get("data"):
            import base64

            return base64.urlsafe_b64decode(payload["body"]["data"]).decode()
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain":
                import base64

                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode()
        return ""
