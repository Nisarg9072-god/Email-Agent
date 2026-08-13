"""Gmail mark-as-read policy — avoid hiding emails that need human attention."""

from __future__ import annotations

# Skip reasons the agent handled safely; OK to remove UNREAD in Gmail.
AUTO_HANDLED_SKIP_PREFIX = "auto_handled:"
AUTO_HANDLED_SKIP_REASONS = frozenset(
    {
        "auto_handled:spam",
        "category_spam_no_auto_reply",
        "spam",
    }
)

# Unrelated / sensitive topics — keep UNREAD so staff can review in Gmail.
HUMAN_REVIEW_SKIP_PREFIX = "human_review:"
HUMAN_REVIEW_SKIP_REASONS = frozenset(
    {
        "human_review:unrelated",
        "human_review:job_application",
        "human_review:partnership",
        "human_review:restricted_info",
        "human_review:other",
        "no_action",
        "not_product_or_service_inquiry",
        "category_job_application_no_auto_reply",
        "category_partnership_no_auto_reply",
        "restricted_info_request_declined",
    }
)

# Agent should retry (e.g. finished without sending when it should have).
RETRYABLE_SKIP_REASONS = frozenset(
    {
        "completed_without_reply",
        "agent_final_skip",
    }
)


def normalize_skip_reason(skip_reason: str | None) -> str | None:
    """Map legacy skip reason strings to human_review / auto_handled prefixes."""
    if not skip_reason:
        return skip_reason
    reason = skip_reason.strip()
    if reason.startswith(AUTO_HANDLED_SKIP_PREFIX) or reason.startswith(
        HUMAN_REVIEW_SKIP_PREFIX
    ):
        return reason
    lower = reason.lower()
    if "spam" in lower:
        return "auto_handled:spam"
    if "job" in lower and "application" in lower:
        return "human_review:job_application"
    if "partnership" in lower:
        return "human_review:partnership"
    if "restricted" in lower:
        return "human_review:restricted_info"
    if reason in {"no_action", "not_product_or_service_inquiry"} or "not_product" in lower:
        return "human_review:unrelated"
    if reason == "completed_without_reply":
        return reason
    if lower.startswith("already_"):
        return reason
    return reason


def requires_human_review(skip_reason: str | None) -> bool:
    """True when the message should stay UNREAD for a human to see."""
    reason = normalize_skip_reason(skip_reason)
    if not reason:
        return False
    if reason.startswith(HUMAN_REVIEW_SKIP_PREFIX):
        return True
    return reason in HUMAN_REVIEW_SKIP_REASONS


def is_auto_handled_skip(skip_reason: str | None) -> bool:
    reason = normalize_skip_reason(skip_reason)
    if not reason:
        return False
    if reason.startswith(AUTO_HANDLED_SKIP_PREFIX):
        return True
    return reason in AUTO_HANDLED_SKIP_REASONS


def should_retry_skipped(skip_reason: str | None, *, has_reply: bool) -> bool:
    """Only retry skips where the agent likely failed to complete an inquiry."""
    if has_reply:
        return False
    if requires_human_review(skip_reason):
        return False
    if is_auto_handled_skip(skip_reason):
        return False
    reason = normalize_skip_reason(skip_reason)
    if reason in RETRYABLE_SKIP_REASONS:
        return True
    return False


def should_mark_gmail_read(
    *,
    status: str,
    skip_reason: str | None = None,
    reply_sent: bool = False,
    mark_read_enabled: bool = True,
) -> bool:
    """
    Decide whether to remove Gmail UNREAD label.

    Default policy (when mark_read_enabled):
    - Mark read after successful reply (processed + reply_sent)
    - Mark read for auto-handled spam skips
    - Keep UNREAD for unrelated topics, job apps, partnerships, failures, etc.
    """
    if not mark_read_enabled:
        return False
    if skip_reason == "already_processing":
        return False

    if status == "processed" and reply_sent:
        return True

    if status == "skipped":
        if requires_human_review(skip_reason):
            return False
        if is_auto_handled_skip(skip_reason):
            return True
        # Unknown skip — stay unread so nothing important is hidden
        return False

    if status == "failed":
        return False

    return False
