"""Tests for email processing state management (Guardrail #1)."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import ProcessedEmail


class TestProcessingState:
    def test_new_email_can_be_claimed(self, processed_repo, state_manager):
        claimed, reason = state_manager.claim("new-email-001")
        assert claimed is True
        assert reason == "claimed"

    def test_already_processed_email_is_skipped(self, processed_repo, state_manager):
        state_manager.claim("email-001")
        state_manager.mark_processed("email-001")

        should_skip, reason = state_manager.should_skip("email-001")
        assert should_skip is True
        assert "processed" in reason

    def test_duplicate_claim_rejected(self, processed_repo, state_manager):
        state_manager.claim("email-dup")
        state_manager.mark_processed("email-dup")

        claimed, reason = state_manager.claim("email-dup")
        assert claimed is False

    def test_database_unique_constraint(self, session):
        session.add(ProcessedEmail(email_id="unique-test", status="processing"))
        session.flush()
        session.add(ProcessedEmail(email_id="unique-test", status="processing"))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    def test_failed_processing_logged(self, processed_repo, state_manager):
        state_manager.claim("email-fail")
        state_manager.mark_failed("email-fail", "llm_timeout")

        record = processed_repo.get("email-fail")
        assert record.status == "failed"
        assert record.error_message == "attempts=1|llm_timeout"

    def test_skipped_with_reason(self, processed_repo, state_manager):
        state_manager.claim("email-skip")
        state_manager.mark_skipped("email-skip", "not_product_inquiry")

        record = processed_repo.get("email-skip")
        assert record.status == "skipped"
        assert record.skip_reason == "not_product_inquiry"

    def test_state_transitions_invalid(self, processed_repo, state_manager):
        state_manager.claim("email-trans")
        state_manager.mark_processed("email-trans")

        with pytest.raises(ValueError):
            processed_repo.mark_failed("email-trans", "too late")
