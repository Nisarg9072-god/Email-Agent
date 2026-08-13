"""Registered tools the LLM may request via AgentDecision."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, str]
    handler_key: str


REGISTERED_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="get_email",
        description="Fetch full email content (sender, subject, body, thread_id) for the current email_id.",
        input_schema={"email_id": "string (must match current email)"},
        handler_key="get_email",
    ),
    ToolSpec(
        name="get_product_information",
        description="Retrieve authorized public information about a NovaAI product by name.",
        input_schema={"product_name": "string e.g. NovaSupport AI, NovaAnalytics"},
        handler_key="get_product_information",
    ),
    ToolSpec(
        name="get_service_information",
        description="Retrieve authorized public information about a NovaAI service by name.",
        input_schema={"service_name": "string e.g. AI consulting"},
        handler_key="get_service_information",
    ),
    ToolSpec(
        name="send_reply",
        description="Send a reply email to the customer. Only call after gathering authorized company info.",
        input_schema={
            "recipient": "string email address",
            "subject": "string reply subject",
            "body": "string reply body",
            "thread_id": "optional string for threading",
        },
        handler_key="send_reply",
    ),
]

TOOL_NAMES = frozenset(t.name for t in REGISTERED_TOOLS)


def tools_for_llm_prompt() -> str:
    """Human-readable tool catalog for agent decision prompts."""
    lines = []
    for spec in REGISTERED_TOOLS:
        args = ", ".join(f"{k}: {v}" for k, v in spec.input_schema.items())
        lines.append(f"- {spec.name}: {spec.description} Args: {args}")
    return "\n".join(lines)
