"""Agent harness — deterministic control layer around the probabilistic agent loop."""

import logging
from typing import Any

from app.agent.schemas import AgentDecision, AgentFinalOutput
from app.agent.state import AgentState
from app.company.authorization import AuthorizationService
from app.harness.read_policy import normalize_skip_reason
from app.tools.registry import TOOL_NAMES, tools_for_llm_prompt

logger = logging.getLogger(__name__)


class HarnessValidationError(Exception):
    """Raised when an agent decision violates harness policy."""


class AgentHarness:
    """
    Deterministic runtime controls: tool auth, limits, validation gates.
    Does NOT choose business actions — only permits or denies LLM decisions.
    """

    def __init__(
        self,
        authorization: AuthorizationService,
        max_turns_per_email: int = 15,
        max_tool_calls_per_email: int = 10,
        max_emails_per_run: int = 50,
    ):
        self._auth = authorization
        self._max_turns = max_turns_per_email
        self._max_tool_calls = max_tool_calls_per_email
        self._max_emails = max_emails_per_run
        self._emails_processed_count = 0

    def reset_run(self) -> None:
        self._emails_processed_count = 0

    def increment_email_slot(self) -> bool:
        self._emails_processed_count += 1
        if self._emails_processed_count > self._max_emails:
            logger.error("Max emails per run exceeded: %d", self._max_emails)
            return False
        return True

    @staticmethod
    def tool_catalog_for_prompt() -> str:
        return tools_for_llm_prompt()

    def validate_decision(
        self, decision: AgentDecision, state: AgentState
    ) -> None:
        """Raise HarnessValidationError if decision is not allowed."""
        if state.turn >= self._max_turns:
            raise HarnessValidationError("max_turns_exceeded")

        if decision.action == "FINAL":
            if decision.final_output is None:
                raise HarnessValidationError("final_output_required")
            return

        if decision.action != "CALL_TOOL":
            raise HarnessValidationError(f"invalid_action:{decision.action}")

        if not decision.tool_name:
            raise HarnessValidationError("tool_name_required")

        if state.tool_call_count >= self._max_tool_calls:
            raise HarnessValidationError("max_tool_calls_exceeded")

        if decision.tool_name not in TOOL_NAMES:
            raise HarnessValidationError(f"tool_not_registered:{decision.tool_name}")

        if self._auth.is_tool_forbidden(decision.tool_name):
            raise HarnessValidationError(f"tool_forbidden:{decision.tool_name}")

        if not self._auth.is_tool_allowed(decision.tool_name):
            # company policy allowlist uses get_product/service names
            if decision.tool_name not in {
                "get_email",
                "send_reply",
                "get_product_information",
                "get_service_information",
            }:
                raise HarnessValidationError(f"tool_not_allowed:{decision.tool_name}")

        self._validate_tool_arguments(decision.tool_name, decision.tool_arguments, state)

    def _validate_tool_arguments(
        self, tool_name: str, arguments: dict[str, Any], state: AgentState
    ) -> None:
        if tool_name == "get_email":
            eid = arguments.get("email_id") or state.email_id
            if eid != state.email_id:
                raise HarnessValidationError("email_id_mismatch")
        elif tool_name == "get_product_information":
            if not arguments.get("product_name"):
                raise HarnessValidationError("product_name_required")
        elif tool_name == "get_service_information":
            if not arguments.get("service_name"):
                raise HarnessValidationError("service_name_required")
        elif tool_name == "send_reply":
            if not (arguments.get("body") or "").strip():
                raise HarnessValidationError("reply_body_required")

    @staticmethod
    def interpret_final(final_output: AgentFinalOutput, state: AgentState) -> tuple[str, str | None]:
        """Map FINAL decision to step status and optional skip reason."""
        if final_output.outcome == "skip":
            raw = final_output.skip_reason or final_output.message or "agent_skip"
            return "skipped", normalize_skip_reason(raw)
        if final_output.outcome == "no_action":
            raw = final_output.skip_reason or "no_action"
            return "skipped", normalize_skip_reason(raw)
        if final_output.outcome == "completed":
            if state.reply_sent:
                return "processed", None
            return "skipped", "completed_without_reply"
        return "failed", f"unknown_final_outcome:{final_output.outcome}"
