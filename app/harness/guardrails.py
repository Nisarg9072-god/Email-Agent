"""Agent guardrails - enforces architectural constraints in code."""

import logging

from app.company.authorization import AuthorizationService
from app.tools.company_data_tools import ALLOWED_TOOLS

logger = logging.getLogger(__name__)


class AgentGuardrails:
    """Deterministic guardrail enforcement."""

    def __init__(self, authorization: AuthorizationService, max_steps: int = 50, max_tool_calls: int = 10):
        self._auth = authorization
        self._max_steps = max_steps
        self._max_tool_calls = max_tool_calls
        self._step_count = 0
        self._tool_call_count = 0

    def reset(self) -> None:
        self._step_count = 0
        self._tool_call_count = 0

    def increment_step(self) -> bool:
        """Returns False if max steps exceeded."""
        self._step_count += 1
        if self._step_count > self._max_steps:
            logger.error("Max agent steps exceeded: %d", self._max_steps)
            return False
        return True

    def record_tool_call(self) -> bool:
        """Returns False if max tool calls exceeded."""
        self._tool_call_count += 1
        if self._tool_call_count > self._max_tool_calls:
            logger.error("Max tool calls exceeded: %d", self._max_tool_calls)
            return False
        return True

    def is_tool_permitted(self, tool_name: str) -> bool:
        """DETERMINISTIC: Only explicitly allowed tools can be called."""
        if self._auth.is_tool_forbidden(tool_name):
            logger.warning("Blocked forbidden tool: %s", tool_name)
            return False
        if tool_name not in ALLOWED_TOOLS:
            logger.warning("Blocked unknown tool: %s", tool_name)
            return False
        return True

    def should_respond_to_classification(self, classification) -> tuple[bool, str | None]:
        """DETERMINISTIC: Decide whether to generate a reply based on classification."""
        if not classification.requires_action:
            return False, "no_action_required"

        if not classification.is_product_or_service_inquiry:
            if classification.category == "restricted_info_request":
                return False, "restricted_info_request_declined"
            return False, "not_product_or_service_inquiry"

        if classification.category in {"spam", "job_application", "partnership"}:
            return False, f"category_{classification.category}_no_auto_reply"

        return True, None

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def tool_call_count(self) -> int:
        return self._tool_call_count
