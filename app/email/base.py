"""Email provider abstraction."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EmailMessage:
    email_id: str
    sender: str
    recipient: str
    subject: str
    body: str
    thread_id: str | None = None
    received_at: str | None = None


@dataclass
class EmailSummary:
    email_id: str
    sender: str
    subject: str
    received_at: str | None = None


class EmailProvider(ABC):
    """Interface for email operations. Agent depends on this, not Gmail specifics."""

    @abstractmethod
    def get_email_count(self) -> int:
        pass

    @abstractmethod
    def list_emails(self) -> list[EmailSummary]:
        pass

    @abstractmethod
    def get_email(self, email_id: str) -> EmailMessage | None:
        pass

    @abstractmethod
    def send_email(
        self, to: str, subject: str, body: str, thread_id: str | None = None
    ) -> bool:
        pass
