"""In-memory email provider for eval runs (dataset-driven, no Gmail)."""

from app.email.base import EmailMessage, EmailProvider, EmailSummary


class DatasetEmailProvider(EmailProvider):
    """Serves emails from evals/dataset.json for isolated AgentRuntime evals."""

    def __init__(self, emails: list[dict]):
        self._messages: dict[str, EmailMessage] = {}
        for row in emails:
            email_id = row["id"]
            self._messages[email_id] = EmailMessage(
                email_id=email_id,
                sender=row["sender"],
                recipient=row.get("recipient", "support@novaai.com"),
                subject=row["subject"],
                body=row["body"],
                thread_id=row.get("thread_id"),
                received_at=row.get("received_at"),
            )
        self._sent: list[dict] = []
        self._marked_read: list[str] = []

    def get_email_count(self) -> int:
        return len(self._messages)

    def list_emails(self) -> list[EmailSummary]:
        return [
            EmailSummary(
                email_id=m.email_id,
                sender=m.sender,
                subject=m.subject,
                received_at=m.received_at,
            )
            for m in self._messages.values()
        ]

    def get_email(self, email_id: str) -> EmailMessage | None:
        return self._messages.get(email_id)

    def send_email(
        self, to: str, subject: str, body: str, thread_id: str | None = None
    ) -> bool:
        self._sent.append(
            {"to": to, "subject": subject, "body": body, "thread_id": thread_id}
        )
        return True

    def mark_as_read(self, email_id: str) -> bool:
        self._marked_read.append(email_id)
        return True

    @property
    def sent_emails(self) -> list[dict]:
        return list(self._sent)

    @property
    def marked_read_ids(self) -> list[str]:
        return list(self._marked_read)
