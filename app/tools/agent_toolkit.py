"""Deterministic tool execution layer — LLM requests tools; harness authorizes; this executes."""

import json
import logging
from typing import Any

from app.agent.state import AgentState, ToolResultRecord
from app.company.authorization import AuthorizationService
from app.company.service import CompanyDataService
from app.email.base import EmailProvider
from app.harness.validator import ResponseValidator
from app.tools.registry import REGISTERED_TOOLS, TOOL_NAMES

logger = logging.getLogger(__name__)


class AgentToolKit:
    """Executes registered tools and updates agent state with results."""

    def __init__(
        self,
        email_provider: EmailProvider,
        company_service: CompanyDataService,
        authorization: AuthorizationService,
        validator: ResponseValidator,
    ):
        self._email = email_provider
        self._company = company_service
        self._auth = authorization
        self._validator = validator

    @staticmethod
    def list_tool_names() -> list[str]:
        return sorted(TOOL_NAMES)

    def execute(
        self, tool_name: str, arguments: dict[str, Any], state: AgentState
    ) -> ToolResultRecord:
        """Run one tool deterministically. Caller must authorize via harness first."""
        turn = state.turn
        try:
            if tool_name == "get_email":
                output = self._get_email(arguments, state)
            elif tool_name == "get_product_information":
                output = self._get_product_information(arguments)
            elif tool_name == "get_service_information":
                output = self._get_service_information(arguments)
            elif tool_name == "send_reply":
                output = self._send_reply(arguments, state)
            else:
                return ToolResultRecord(
                    turn=turn,
                    tool_name=tool_name,
                    arguments=arguments,
                    success=False,
                    error=f"unknown_tool:{tool_name}",
                )
            return ToolResultRecord(
                turn=turn,
                tool_name=tool_name,
                arguments=arguments,
                success=True,
                output=output,
            )
        except Exception as exc:
            logger.exception("Tool %s failed", tool_name)
            return ToolResultRecord(
                turn=turn,
                tool_name=tool_name,
                arguments=arguments,
                success=False,
                error=str(exc),
            )

    def _get_email(self, arguments: dict, state: AgentState) -> str:
        email_id = arguments.get("email_id") or state.email_id
        if email_id != state.email_id:
            raise ValueError("email_id_mismatch")
        message = self._email.get_email(email_id)
        if message is None:
            raise ValueError("email_not_found")
        if not message.sender and not message.body:
            raise ValueError("invalid_email_missing_fields")
        if not message.sender:
            raise ValueError("invalid_email_missing_sender")
        if not message.body:
            raise ValueError("invalid_email_missing_body")
        state.sender = message.sender
        state.subject = message.subject
        state.body = message.body
        state.thread_id = message.thread_id
        return json.dumps(
            {
                "email_id": message.email_id,
                "sender": message.sender,
                "subject": message.subject,
                "body": message.body,
                "thread_id": message.thread_id,
            }
        )

    def _get_product_information(self, arguments: dict) -> str:
        name = arguments.get("product_name", "")
        info = self._company.get_product_information(name)
        if info is None:
            return json.dumps({"found": False, "product_name": name})
        chunk = json.dumps(info, indent=2)
        return json.dumps({"found": True, "data": info})

    def _get_service_information(self, arguments: dict) -> str:
        name = arguments.get("service_name", "")
        info = self._company.get_service_information(name)
        if info is None:
            return json.dumps({"found": False, "service_name": name})
        return json.dumps({"found": True, "data": info})

    def _send_reply(self, arguments: dict, state: AgentState) -> str:
        recipient = arguments.get("recipient") or state.sender or ""
        subject = arguments.get("subject", "")
        body = arguments.get("body", "")
        thread_id = arguments.get("thread_id") or state.thread_id

        is_valid, err = self._validator.validate(recipient, subject, body)
        if not is_valid:
            raise ValueError(f"validation_failed:{err}")

        sent = self._email.send_email(
            to=recipient, subject=subject, body=body, thread_id=thread_id
        )
        if not sent:
            raise ValueError("send_failed")
        state.reply_sent = True
        return json.dumps({"sent": True, "recipient": recipient, "subject": subject})

    def apply_tool_result(self, state: AgentState, record: ToolResultRecord) -> None:
        """Append tool result and merge company info into state."""
        state.tool_history.append(record)
        state.tool_call_count += 1
        if record.success and record.tool_name in {
            "get_product_information",
            "get_service_information",
        }:
            try:
                parsed = json.loads(record.output)
                if parsed.get("found") and parsed.get("data"):
                    label = record.tool_name.replace("get_", "").replace("_information", "")
                    state.company_information.append(
                        f"{label}: {json.dumps(parsed['data'], indent=2)}"
                    )
            except json.JSONDecodeError:
                pass
