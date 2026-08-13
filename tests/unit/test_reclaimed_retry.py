"""Tests for reclaimed email retry flow."""

from app.db.repositories import ProcessedEmailRepository, is_reclaimed_for_retry
from app.harness.state import ProcessingStateManager


class TestReclaimedRetry:
    def test_reclaim_stub_detected(self):
        assert is_reclaimed_for_retry("attempts=1")
        assert not is_reclaimed_for_retry("attempts=1|tool_failed:x")

    def test_should_not_skip_reclaimed_processing(self, session):
        repo = ProcessedEmailRepository(session)
        repo.claim_for_processing("email-1")
        record = repo.get("email-1")
        record.error_message = "attempts=1"
        session.flush()

        manager = ProcessingStateManager(repo)
        should_skip, reason = manager.should_skip("email-1")
        assert should_skip is False
        assert reason is None

    def test_claim_allows_reclaimed_processing(self, session):
        repo = ProcessedEmailRepository(session)
        repo.claim_for_processing("email-1")
        record = repo.get("email-1")
        record.error_message = "attempts=1"
        session.flush()

        ok, reason = repo.claim_for_processing("email-1")
        assert ok is True
        assert reason == "reclaimed"
