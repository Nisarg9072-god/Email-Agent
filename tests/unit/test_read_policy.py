"""Tests for Gmail mark-as-read policy."""

from app.harness.read_policy import (
    normalize_skip_reason,
    requires_human_review,
    should_mark_gmail_read,
    should_retry_skipped,
)


class TestReadPolicy:
    def test_reply_sent_is_marked_read(self):
        assert should_mark_gmail_read(status="processed", reply_sent=True) is True

    def test_spam_skip_marked_read(self):
        assert should_mark_gmail_read(status="skipped", skip_reason="auto_handled:spam") is True
        assert should_mark_gmail_read(status="skipped", skip_reason="category_spam_no_auto_reply") is True

    def test_human_review_stays_unread(self):
        for reason in (
            "human_review:unrelated",
            "human_review:job_application",
            "no_action",
            "category_job_application_no_auto_reply",
        ):
            assert should_mark_gmail_read(status="skipped", skip_reason=reason) is False

    def test_failed_stays_unread(self):
        assert should_mark_gmail_read(status="failed", skip_reason="tool_failed") is False

    def test_mark_read_disabled(self):
        assert (
            should_mark_gmail_read(
                status="processed",
                reply_sent=True,
                mark_read_enabled=False,
            )
            is False
        )

    def test_normalize_legacy_spam(self):
        assert normalize_skip_reason("category_spam_no_auto_reply") == "auto_handled:spam"

    def test_normalize_legacy_job(self):
        assert normalize_skip_reason("category_job_application_no_auto_reply") == (
            "human_review:job_application"
        )

    def test_human_review_not_retried(self):
        assert should_retry_skipped("human_review:unrelated", has_reply=False) is False

    def test_completed_without_reply_retried(self):
        assert should_retry_skipped("completed_without_reply", has_reply=False) is True

    def test_requires_human_review_prefix(self):
        assert requires_human_review("human_review:partnership") is True
