"""Pydantic schemas for agent inputs/outputs."""

from typing import Literal

from pydantic import BaseModel, Field


class EmailClassification(BaseModel):
    """Structured LLM classification output (probabilistic decision)."""

    requires_action: bool = Field(
        description="Whether this email requires a response from NovaAI"
    )
    is_product_or_service_inquiry: bool = Field(
        description="Whether the email is asking about NovaAI products or services"
    )
    category: str = Field(
        description="Category: product_pricing, product_features, service_inquiry, "
        "demo_request, partnership, job_application, spam, restricted_info_request, other"
    )
    product_names: list[str] = Field(
        default_factory=list,
        description="Product names mentioned or relevant to the inquiry",
    )
    service_names: list[str] = Field(
        default_factory=list,
        description="Service names mentioned or relevant to the inquiry",
    )
    reasoning: str = Field(
        default="", description="Brief explanation of the classification"
    )


class GeneratedReply(BaseModel):
    """Structured LLM reply generation output."""

    subject: str = Field(description="Reply email subject line")
    body: str = Field(description="Reply email body text")
    information_used: list[str] = Field(
        default_factory=list,
        description="Which authorized information sources were used",
    )


class ToolCallRequest(BaseModel):
    """Represents a tool the LLM wants to call."""

    tool_name: str
    arguments: dict = Field(default_factory=dict)


class AgentFinalOutput(BaseModel):
    """Structured outcome when the agent selects action=FINAL."""

    outcome: Literal["completed", "skip", "no_action"] = Field(
        description="completed=done after reply or explicit finish; skip=no reply needed"
    )
    message: str = Field(default="", description="Brief explanation of final decision")
    skip_reason: str | None = Field(default=None)


class AgentDecision(BaseModel):
    """Structured LLM decision for the agentic loop — one step per turn."""

    action: Literal["CALL_TOOL", "FINAL"] = Field(
        description="CALL_TOOL to invoke a registered tool, FINAL to stop the agent loop"
    )
    tool_name: str | None = Field(
        default=None, description="Required when action=CALL_TOOL"
    )
    tool_arguments: dict = Field(
        default_factory=dict, description="Arguments for the selected tool"
    )
    final_output: AgentFinalOutput | None = Field(
        default=None, description="Required when action=FINAL"
    )
    reasoning: str = Field(default="", description="Why this action was chosen")


class AgentStepResult(BaseModel):
    """Result of processing a single email."""

    email_id: str
    status: str
    classification: EmailClassification | None = None
    reply_sent: bool = False
    skip_reason: str | None = None
    error_message: str | None = None
    tool_calls: list[str] = Field(default_factory=list)
    agent_turns: int = 0
    decision_trace: list[str] = Field(default_factory=list)
