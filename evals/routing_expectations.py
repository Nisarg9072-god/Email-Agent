"""Derive expected AgentRuntime outcomes from eval dataset labels."""


def expected_routing(email: dict) -> dict:
    """
    Map dataset expected fields to end-to-end runtime expectations.

    Returns:
        status: processed | skipped | failed (failed not expected in mock evals)
        reply_sent: bool
        skip_prefix: optional prefix for skip_reason (human_review: / auto_handled:)
    """
    exp = email["expected"]
    category = exp.get("category", "other")

    if exp.get("is_product_or_service_inquiry"):
        return {
            "status": "processed",
            "reply_sent": True,
            "skip_prefix": None,
        }

    if category == "spam":
        return {
            "status": "skipped",
            "reply_sent": False,
            "skip_prefix": "auto_handled:",
        }

    prefix_by_category = {
        "job_application": "human_review:job_application",
        "partnership": "human_review:partnership",
        "restricted_info_request": "human_review:restricted_info",
    }
    if category in prefix_by_category:
        return {
            "status": "skipped",
            "reply_sent": False,
            "skip_prefix": prefix_by_category[category],
        }

    return {
        "status": "skipped",
        "reply_sent": False,
        "skip_prefix": "human_review:",
    }


def routing_matches(actual_status: str, actual_reply_sent: bool, skip_reason: str | None, expected: dict) -> bool:
    if actual_status != expected["status"]:
        return False
    if expected["reply_sent"] != actual_reply_sent:
        return False
    prefix = expected.get("skip_prefix")
    if prefix and expected["status"] == "skipped":
        if not skip_reason:
            return False
        if prefix == "human_review:":
            return skip_reason.startswith("human_review:")
        return skip_reason.startswith(prefix)
    return True
