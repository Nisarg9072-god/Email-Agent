"""Repair common malformed LLM agent decisions before harness validation."""

from app.agent.schemas import AgentDecision, AgentFinalOutput
from app.agent.state import AgentState
from app.llm.base import LLMProvider

PRODUCT_KEYWORDS: list[tuple[str, str]] = [
    ("novasupport ai", "NovaSupport AI"),
    ("novasupport", "NovaSupport AI"),
    ("novaanalytics", "NovaAnalytics"),
    ("nova analytics", "NovaAnalytics"),
]

SERVICE_KEYWORDS: list[tuple[str, str]] = [
    ("ai consulting", "AI consulting"),
    ("consulting services", "AI consulting"),
    ("custom ai integration", "Custom AI integration"),
    ("chatbot implementation", "AI chatbot implementation"),
    ("chatbot", "AI chatbot implementation"),
]


def infer_product_name(state: AgentState) -> str | None:
    text = f"{state.subject or ''} {state.body or ''}".lower()
    for keyword, name in PRODUCT_KEYWORDS:
        if keyword in text:
            return name
    return None


def infer_service_name(state: AgentState) -> str | None:
    text = f"{state.subject or ''} {state.body or ''}".lower()
    for keyword, name in SERVICE_KEYWORDS:
        if keyword in text:
            return name
    return None


def _tool_was_called(state: AgentState, tool_name: str) -> bool:
    return any(record.tool_name == tool_name for record in state.tool_history)


def _should_force_reply(agent_state: AgentState) -> bool:
    return bool(
        agent_state.company_information
        and not agent_state.reply_sent
        and agent_state.sender
        and agent_state.body
        and not _tool_was_called(agent_state, "send_reply")
    )


def _build_send_reply_decision(
    agent_state: AgentState, llm: LLMProvider, reasoning: str
) -> AgentDecision:
    company_info = "\n\n".join(agent_state.company_information)
    reply = llm.generate_reply(
        agent_state.sender or "",
        agent_state.subject or "",
        agent_state.body or "",
        company_info,
    )
    return AgentDecision(
        action="CALL_TOOL",
        tool_name="send_reply",
        tool_arguments={
            "recipient": agent_state.sender,
            "subject": reply.subject,
            "body": reply.body,
            "thread_id": agent_state.thread_id,
        },
        reasoning=reasoning,
    )


def normalize_decision(
    decision: AgentDecision,
    email_id: str,
    agent_state: AgentState,
    llm: LLMProvider | None = None,
) -> AgentDecision:
    """Repair common malformed LLM outputs before harness validation."""
    if decision.action == "FINAL":
        if _should_force_reply(agent_state) and llm is not None:
            return _build_send_reply_decision(
                agent_state,
                llm,
                "Product/service info gathered but agent chose FINAL without sending reply.",
            )
        if decision.final_output is None:
            return decision.model_copy(
                update={
                    "final_output": AgentFinalOutput(
                        outcome="skip",
                        message=decision.reasoning or "Agent finished without structured output",
                    )
                }
            )
        return decision

    if decision.action != "CALL_TOOL":
        return decision

    if (
        decision.tool_name == "get_product_information"
        and not decision.tool_arguments.get("product_name")
    ):
        product = infer_product_name(agent_state)
        if product:
            return decision.model_copy(
                update={
                    "tool_arguments": {
                        **decision.tool_arguments,
                        "product_name": product,
                    }
                }
            )

    if (
        decision.tool_name == "get_service_information"
        and not decision.tool_arguments.get("service_name")
    ):
        service = infer_service_name(agent_state)
        if service:
            return decision.model_copy(
                update={
                    "tool_arguments": {
                        **decision.tool_arguments,
                        "service_name": service,
                    }
                }
            )

    if decision.tool_name:
        return decision

    if not agent_state.tool_history:
        return decision.model_copy(
            update={
                "tool_name": "get_email",
                "tool_arguments": {"email_id": email_id},
            }
        )

    if (
        agent_state.company_information
        and not agent_state.reply_sent
        and llm is not None
        and agent_state.sender
        and agent_state.body
    ):
        return _build_send_reply_decision(
            agent_state,
            llm,
            "Missing tool name after company info was loaded; sending reply.",
        )

    if not _tool_was_called(agent_state, "get_product_information"):
        product = infer_product_name(agent_state)
        if product:
            return decision.model_copy(
                update={
                    "tool_name": "get_product_information",
                    "tool_arguments": {"product_name": product},
                }
            )

    if not _tool_was_called(agent_state, "get_service_information"):
        service = infer_service_name(agent_state)
        if service:
            return decision.model_copy(
                update={
                    "tool_name": "get_service_information",
                    "tool_arguments": {"service_name": service},
                }
            )

    return decision
