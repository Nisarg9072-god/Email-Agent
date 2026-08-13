"""Tests for failure retry policy."""

from app.db.repositories import failure_attempt_count, is_retryable_failure


class TestFailureRetryPolicy:
    def test_attempt_count_from_tagged_message(self):
        assert failure_attempt_count("attempts=2|tool_failed:get_email") == 2

    def test_legacy_message_counts_as_exhausted(self):
        assert failure_attempt_count("tool_failed:get_email:invalid_email_missing_fields") == 2

    def test_retry_allowed_under_max(self):
        assert is_retryable_failure("attempts=1|tool_failed:get_email")

    def test_retry_blocked_at_max(self):
        assert not is_retryable_failure("attempts=2|tool_failed:get_email")

    def test_legacy_untagged_not_retried(self):
        assert not is_retryable_failure("tool_failed:get_email:invalid_email_missing_fields")

    def test_non_retryable_errors(self):
        assert not is_retryable_failure("attempts=1|email_not_found")
