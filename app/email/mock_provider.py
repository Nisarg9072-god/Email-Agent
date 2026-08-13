"""Mock email provider for development and testing without Gmail credentials."""

import json
import logging
from pathlib import Path

from app.email.base import EmailMessage, EmailProvider, EmailSummary

logger = logging.getLogger(__name__)


class MockEmailProvider(EmailProvider):
    """In-memory email provider backed by mock_emails.json."""

    def __init__(self, emails_path: Path):
        self._emails_path = emails_path
        self._emails: list[dict] = self._load_emails()
        self._sent: list[dict] = []

    def _load_emails(self) -> list[dict]:
        with open(self._emails_path) as f:
            return json.load(f)

    def get_email_count(self) -> int:
        return len(self._emails)

    def list_emails(self) -> list[EmailSummary]:
        return [
            EmailSummary(
                email_id=e["email_id"],
                sender=e["sender"],
                subject=e["subject"],
                received_at=e.get("received_at"),
            )
            for e in self._emails
        ]

    def get_email(self, email_id: str) -> EmailMessage | None:
        for e in self._emails:
            if e["email_id"] == email_id:
                return EmailMessage(
                    email_id=e["email_id"],
                    sender=e["sender"],
                    recipient=e["recipient"],
                    subject=e["subject"],
                    body=e["body"],
                    thread_id=e.get("thread_id"),
                    received_at=e.get("received_at"),
                )
        return None

    def send_email(
        self, to: str, subject: str, body: str, thread_id: str | None = None
    ) -> bool:
        sent = {
            "to": to,
            "subject": subject,
            "body": body,
            "thread_id": thread_id,
        }
        self._sent.append(sent)
        logger.info("Mock email sent to=%s subject=%s", to, subject)
        return True

    @property
    def sent_emails(self) -> list[dict]:
        """For testing: inspect sent emails."""
        return list(self._sent)

    def reset_sent(self) -> None:
        self._sent.clear()
