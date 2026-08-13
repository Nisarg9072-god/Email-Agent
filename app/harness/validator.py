"""Response validation - DETERMINISTIC guardrails before sending."""

import logging

from app.company.authorization import AuthorizationService

logger = logging.getLogger(__name__)


class ResponseValidator:
    """Validates AI-generated responses before sending."""

    def __init__(self, authorization: AuthorizationService):
        self._auth = authorization

    def validate(
        self,
        recipient: str,
        subject: str,
        body: str,
    ) -> tuple[bool, str | None]:
        """Returns (is_valid, error_reason)."""

        if not recipient or not recipient.strip():
            return False, "empty_recipient"

        if not subject or not subject.strip():
            return False, "empty_subject"

        if not body or not body.strip():
            return False, "empty_body"

        max_len = self._auth.get_max_response_length()
        if len(body) > max_len:
            return False, f"response_too_long:{len(body)}>{max_len}"

        has_restricted, reason = self._auth.contains_restricted_content(body)
        if has_restricted:
            logger.warning("Response contains restricted content: %s", reason)
            return False, reason

        return True, None
