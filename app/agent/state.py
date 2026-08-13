"""Explicit agent state for the agentic runtime loop."""

from pydantic import BaseModel, Field


class ToolResultRecord(BaseModel):
    """One tool execution result appended to agent state."""

    turn: int
    tool_name: str
    arguments: dict = Field(default_factory=dict)
    success: bool = True
    output: str = ""
    error: str | None = None


class AgentState(BaseModel):
    """State passed to the LLM each turn (no secrets or DB handles)."""

    email_id: str
    turn: int = 0
    tool_call_count: int = 0
    status: str = "running"

    sender: str | None = None
    subject: str | None = None
    body: str | None = None
    thread_id: str | None = None

    tool_history: list[ToolResultRecord] = Field(default_factory=list)
    company_information: list[str] = Field(default_factory=list)
    reply_sent: bool = False

    def to_llm_context(self) -> str:
        """Serialize state for the LLM decision prompt."""
        lines = [
            f"email_id: {self.email_id}",
            f"turn: {self.turn}",
            f"tool_call_count: {self.tool_call_count}",
            f"reply_sent: {self.reply_sent}",
        ]
        if self.sender:
            lines.append(f"sender: {self.sender}")
        if self.subject:
            lines.append(f"subject: {self.subject}")
        if self.body:
            lines.append(f"body: {self.body}")
        if self.company_information:
            lines.append("company_information:")
            lines.extend(f"  - {chunk}" for chunk in self.company_information)
        if self.tool_history:
            lines.append("tool_history:")
            for tr in self.tool_history:
                status = "ok" if tr.success else f"error:{tr.error}"
                lines.append(
                    f"  turn {tr.turn}: {tr.tool_name}({tr.arguments}) -> {status}"
                )
        return "\n".join(lines)
