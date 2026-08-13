"""Processing state management - Guardrail #1 implementation."""

import logging

from app.db.repositories import ProcessedEmailRepository

logger = logging.getLogger(__name__)


class ProcessingStateManager:
    """Manages email processing state with duplicate protection."""

    def __init__(self, repo: ProcessedEmailRepository):
        self._repo = repo

    def should_skip(self, email_id: str) -> tuple[bool, str | None]:
        """DETERMINISTIC: Check if email should be skipped."""
        record = self._repo.get(email_id)
        if record is None:
            return False, None

        if record.status in {"processed", "failed", "skipped"}:
            reason = f"already_{record.status}"
            if record.skip_reason:
                reason = record.skip_reason
            elif record.error_message:
                reason = record.error_message
            logger.info("Skipping email %s: %s", email_id, reason)
            return True, reason

        if record.status == "processing":
            return True, "already_processing"

        return False, None

    def claim(self, email_id: str) -> tuple[bool, str]:
        """Attempt to claim email for processing."""
        return self._repo.claim_for_processing(email_id)

    def mark_processed(self, email_id: str, classification: str | None = None) -> None:
        self._repo.mark_processed(email_id, classification=classification)

    def mark_failed(self, email_id: str, error: str) -> None:
        self._repo.mark_failed(email_id, error_message=error)

    def mark_skipped(self, email_id: str, reason: str) -> None:
        self._repo.mark_skipped(email_id, skip_reason=reason)
