"""Data access layer for processed emails, replies, and agent runs.

All database access goes through this repository layer.
The LLM never receives these objects or database connections.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AgentRun, ProcessedEmail, Reply

logger = logging.getLogger(__name__)

# Valid state transitions for processed emails (Guardrail #1)
VALID_STATES = {"pending", "processing", "processed", "failed", "skipped"}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"processing", "skipped"},
    "processing": {"processed", "failed", "skipped"},
    "processed": set(),  # terminal
    "failed": set(),  # terminal
    "skipped": set(),  # terminal
}


class ProcessedEmailRepository:
    """Manages email processing state with duplicate protection."""

    def __init__(self, session: Session):
        self._session = session

    def get(self, email_id: str) -> ProcessedEmail | None:
        return self._session.get(ProcessedEmail, email_id)

    def is_terminal(self, email_id: str) -> bool:
        """DETERMINISTIC: Check if email is already in a terminal state."""
        record = self.get(email_id)
        if record is None:
            return False
        return record.status in {"processed", "failed", "skipped"}

    def clear_failed_for_retry(self, email_id: str) -> bool:
        """Remove a failed record so the agent can process the email again."""
        record = self.get(email_id)
        if record is None or record.status != "failed":
            return False
        self._session.delete(record)
        self._session.flush()
        return True

    def clear_skipped_for_retry(self, email_id: str) -> bool:
        """Remove a skipped record so the agent can retry (e.g. reply never sent)."""
        record = self.get(email_id)
        if record is None or record.status != "skipped":
            return False
        self._session.delete(record)
        self._session.flush()
        return True

    def claim_for_processing(self, email_id: str) -> tuple[bool, str]:
        """Atomically claim an email for processing.

        Returns (success, reason). Uses database UNIQUE constraint to prevent
        duplicate processing even under race conditions.

        State transition: (new) -> processing
        """
        existing = self.get(email_id)
        if existing is not None:
            if existing.status in {"processed", "failed", "skipped"}:
                return False, f"already_{existing.status}"
            if existing.status == "processing":
                return False, "already_processing"

        try:
            if existing is None:
                record = ProcessedEmail(email_id=email_id, status="processing")
                self._session.add(record)
            else:
                existing.status = "processing"
                existing.updated_at = datetime.now(timezone.utc)
            with self._session.begin_nested():
                self._session.flush()
            return True, "claimed"
        except IntegrityError:
            logger.warning("Race condition detected for email_id=%s", email_id)
            return False, "race_condition_duplicate"

    def mark_processed(
        self, email_id: str, classification: str | None = None
    ) -> None:
        self._transition(email_id, "processed", classification=classification)

    def mark_failed(self, email_id: str, error_message: str) -> None:
        self._transition(email_id, "failed", error_message=error_message)

    def mark_skipped(self, email_id: str, skip_reason: str) -> None:
        self._transition(email_id, "skipped", skip_reason=skip_reason)

    def _transition(
        self,
        email_id: str,
        new_status: str,
        classification: str | None = None,
        error_message: str | None = None,
        skip_reason: str | None = None,
    ) -> None:
        record = self.get(email_id)
        if record is None:
            raise ValueError(f"No record for email_id={email_id}")

        allowed = ALLOWED_TRANSITIONS.get(record.status, set())
        if new_status not in allowed and record.status != new_status:
            raise ValueError(
                f"Invalid transition {record.status} -> {new_status} for {email_id}"
            )

        record.status = new_status
        record.updated_at = datetime.now(timezone.utc)
        if new_status in {"processed", "failed", "skipped"}:
            record.processed_at = datetime.now(timezone.utc)
        if classification is not None:
            record.classification = classification
        if error_message is not None:
            record.error_message = error_message
        if skip_reason is not None:
            record.skip_reason = skip_reason
        self._session.flush()


class ReplyRepository:
    def __init__(self, session: Session):
        self._session = session

    def create(
        self,
        email_id: str,
        recipient: str,
        subject: str,
        body: str,
        status: str = "pending",
    ) -> Reply:
        reply = Reply(
            email_id=email_id,
            recipient=recipient,
            subject=subject,
            body=body,
            status=status,
        )
        self._session.add(reply)
        self._session.flush()
        return reply

    def mark_sent(self, reply_id: int) -> None:
        reply = self._session.get(Reply, reply_id)
        if reply:
            reply.status = "sent"
            reply.sent_at = datetime.now(timezone.utc)

    def mark_failed(self, reply_id: int, error_message: str) -> None:
        reply = self._session.get(Reply, reply_id)
        if reply:
            reply.status = "failed"
            reply.error_message = error_message

    def has_reply_for_email(self, email_id: str) -> bool:
        from sqlalchemy import select

        row = self._session.execute(
            select(Reply.id).where(Reply.email_id == email_id).limit(1)
        ).first()
        return row is not None


class AgentRunRepository:
    def __init__(self, session: Session):
        self._session = session

    def start_run(self) -> AgentRun:
        run = AgentRun(status="running")
        self._session.add(run)
        self._session.flush()
        return run

    def complete_run(
        self,
        run_id: int,
        emails_found: int,
        emails_processed: int,
        emails_skipped: int,
        emails_failed: int,
        status: str = "completed",
        error_message: str | None = None,
    ) -> None:
        run = self._session.get(AgentRun, run_id)
        if run:
            run.completed_at = datetime.now(timezone.utc)
            run.emails_found = emails_found
            run.emails_processed = emails_processed
            run.emails_skipped = emails_skipped
            run.emails_failed = emails_failed
            run.status = status
            run.error_message = error_message
