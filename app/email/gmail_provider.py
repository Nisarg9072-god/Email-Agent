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

# Default: inbox unread only. Override via GMAIL_QUERY in .env.
DEFAULT_GMAIL_QUERY = "in:inbox is:unread"


class GmailEmailProvider(EmailProvider):
    """Gmail API integration. Falls back gracefully if credentials unavailable."""

    def __init__(
        self,
        credentials_path: str,
        token_path: str,
        query: str = DEFAULT_GMAIL_QUERY,
        max_messages_per_run: int = 50,
        unread_scan_limit: int = 100,
        mark_read_after_processing: bool = True,
    ):
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._query = query or DEFAULT_GMAIL_QUERY
        self._max_messages = max(1, max_messages_per_run)
        self._scan_limit = max(self._max_messages, unread_scan_limit)
        self._mark_read_after_processing = mark_read_after_processing
        self._service = None
        self._unread_refs_cache: list[dict] | None = None
        self._has_more_unread = False

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

    def _list_matching_message_refs(
        self, *, max_fetch: int | None = None, refresh: bool = False
    ) -> list[dict]:
        """Paginate Gmail messages.list up to max_fetch IDs (accurate, not estimate)."""
        fetch_limit = max_fetch if max_fetch is not None else self._scan_limit
        if self._unread_refs_cache is not None and not refresh and max_fetch is None:
            return self._unread_refs_cache

        service = self._get_service()
        refs: list[dict] = []
        page_token: str | None = None
        self._has_more_unread = False

        while len(refs) < fetch_limit:
            kwargs: dict = {"userId": "me", "q": self._query, "maxResults": 500}
            if page_token:
                kwargs["pageToken"] = page_token
            try:
                result = service.users().messages().list(**kwargs).execute()
            except Exception as exc:
                logger.exception("Gmail messages.list failed for query=%r", self._query)
                raise RuntimeError(f"Gmail list failed: {exc}") from exc
            batch = result.get("messages", [])
            refs.extend(batch)
            page_token = result.get("nextPageToken")
            if len(refs) >= fetch_limit:
                refs = refs[:fetch_limit]
                self._has_more_unread = bool(page_token) or len(batch) > fetch_limit
                break
            if not page_token:
                break

        self._unread_refs_cache = refs
        if self._has_more_unread:
            logger.warning(
                "Gmail query=%r has MORE than %d unread match(es) in this scan "
                "(increase GMAIL_UNREAD_SCAN_LIMIT or mark mail read in Gmail)",
                self._query,
                fetch_limit,
            )
        else:
            logger.info(
                "Gmail query=%r scanned %d unread message(s)",
                self._query,
                len(refs),
            )
        return refs

    def get_email_count(self) -> int:
        return len(self._list_matching_message_refs(max_fetch=self._scan_limit, refresh=True))

    def list_emails(self) -> list[EmailSummary]:
        """Return unread IDs from a wide scan — runtime filters/prioritizes new mail."""
        summaries: list[EmailSummary] = []

        for msg in self._list_matching_message_refs(max_fetch=self._scan_limit, refresh=True):
            summaries.append(
                EmailSummary(
                    email_id=msg["id"],
                    sender="",
                    subject="",
                )
            )

        logger.info("Gmail: prepared %d message(s) for agent processing", len(summaries))
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

    def mark_as_read(self, email_id: str) -> bool:
        """Remove UNREAD label in Gmail so the message is not picked up on the next run."""
        if not self._mark_read_after_processing:
            return True
        try:
            service = self._get_service()
            service.users().messages().modify(
                userId="me",
                id=email_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
            logger.info("Gmail: marked message %s as read", email_id)
            return True
        except Exception:
            logger.exception("Failed to mark Gmail message %s as read", email_id)
            return False

    def mark_many_as_read(self, email_ids: list[str]) -> int:
        """Batch-remove UNREAD label (Gmail allows up to 1000 IDs per call)."""
        if not email_ids or not self._mark_read_after_processing:
            return 0
        service = self._get_service()
        marked = 0
        for i in range(0, len(email_ids), 1000):
            chunk = email_ids[i : i + 1000]
            try:
                service.users().messages().batchModify(
                    userId="me",
                    body={"ids": chunk, "removeLabelIds": ["UNREAD"]},
                ).execute()
                marked += len(chunk)
            except Exception:
                logger.exception(
                    "Gmail batchModify failed for %d message(s)", len(chunk)
                )
                for email_id in chunk:
                    if self.mark_as_read(email_id):
                        marked += 1
        if marked:
            logger.info("Gmail: batch marked %d message(s) as read", marked)
        return marked

    @staticmethod
    def _decode_body_data(data: str) -> str:
        import base64

        return base64.urlsafe_b64decode(data).decode(errors="replace")

    @staticmethod
    def _html_to_text(html: str) -> str:
        import re

        text = re.sub(
            r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE
        )
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @classmethod
    def _collect_text_parts(cls, payload: dict) -> tuple[str, str]:
        """Return (plain_text, html_text) from a Gmail message payload (recursive)."""
        plain_parts: list[str] = []
        html_parts: list[str] = []

        mime = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")
        if body_data:
            decoded = cls._decode_body_data(body_data)
            if mime == "text/plain":
                plain_parts.append(decoded)
            elif mime == "text/html":
                html_parts.append(decoded)

        for part in payload.get("parts", []):
            p, h = cls._collect_text_parts(part)
            if p:
                plain_parts.append(p)
            if h:
                html_parts.append(h)

        return "\n".join(plain_parts), "\n".join(html_parts)

    @classmethod
    def _extract_body(cls, payload: dict) -> str:
        plain, html = cls._collect_text_parts(payload)
        if plain.strip():
            return plain.strip()
        if html.strip():
            return cls._html_to_text(html)
        return ""
