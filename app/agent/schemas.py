"""Pydantic schemas for agent inputs/outputs."""

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


class AgentStepResult(BaseModel):
    """Result of processing a single email."""

    email_id: str
    status: str
    classification: EmailClassification | None = None
    reply_sent: bool = False
    skip_reason: str | None = None
    error_message: str | None = None
    tool_calls: list[str] = Field(default_factory=list)
