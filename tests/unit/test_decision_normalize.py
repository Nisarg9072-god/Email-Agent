"""Tests for LLM decision normalization."""

from app.agent.decision_normalize import infer_product_name, normalize_decision
from app.agent.schemas import AgentDecision, AgentFinalOutput
from app.agent.state import AgentState, ToolResultRecord
from app.llm.mock_provider import MockLLMProvider


class TestNormalizeDecision:
    def test_call_tool_without_name_defaults_to_get_email(self):
        state = AgentState(email_id="abc123")
        decision = AgentDecision(action="CALL_TOOL", reasoning="fetch email")
        fixed = normalize_decision(decision, "abc123", state)
        assert fixed.tool_name == "get_email"
        assert fixed.tool_arguments == {"email_id": "abc123"}

    def test_final_without_output_becomes_skip(self):
        state = AgentState(
            email_id="abc123",
            tool_history=[ToolResultRecord(turn=1, tool_name="get_email")],
        )
        decision = AgentDecision(action="FINAL", reasoning="done")
        fixed = normalize_decision(decision, "abc123", state)
        assert fixed.final_output is not None
        assert fixed.final_output.outcome == "skip"

    def test_get_product_information_infers_product_name(self):
        state = AgentState(
            email_id="abc123",
            subject="Pricing for NovaSupport AI",
            body="Hi, I need starter and professional plan pricing.",
        )
        decision = AgentDecision(
            action="CALL_TOOL",
            tool_name="get_product_information",
            reasoning="lookup pricing",
        )
        fixed = normalize_decision(decision, "abc123", state)
        assert fixed.tool_arguments["product_name"] == "NovaSupport AI"

    def test_missing_tool_after_get_email_infers_product_lookup(self):
        state = AgentState(
            email_id="abc123",
            subject="Pricing for NovaSupport AI",
            body="Please share pricing for starter and professional plans.",
            tool_history=[ToolResultRecord(turn=1, tool_name="get_email")],
        )
        decision = AgentDecision(action="CALL_TOOL", reasoning="next step")
        fixed = normalize_decision(decision, "abc123", state)
        assert fixed.tool_name == "get_product_information"
        assert fixed.tool_arguments["product_name"] == "NovaSupport AI"

    def test_missing_tool_after_product_lookup_generates_send_reply(self):
        llm = MockLLMProvider()
        state = AgentState(
            email_id="abc123",
            sender="vijay@example.com",
            subject="Pricing for NovaSupport AI",
            body="Please share pricing for starter and professional plans.",
            thread_id="thread-1",
            company_information=['product: {"public_pricing": {"starter": "$99/month"}}'],
            tool_history=[
                ToolResultRecord(turn=1, tool_name="get_email"),
                ToolResultRecord(turn=2, tool_name="get_product_information"),
            ],
        )
        decision = AgentDecision(action="CALL_TOOL", reasoning="reply")
        fixed = normalize_decision(decision, "abc123", state, llm)
        assert fixed.tool_name == "send_reply"
        assert fixed.tool_arguments["recipient"] == "vijay@example.com"
        assert fixed.tool_arguments["body"]

    def test_final_without_reply_after_product_lookup_forces_send_reply(self):
        llm = MockLLMProvider()
        state = AgentState(
            email_id="abc123",
            sender="vijay@example.com",
            subject="Pricing for NovaSupport AI",
            body="Please share pricing for starter and professional plans.",
            thread_id="thread-1",
            company_information=['product: {"public_pricing": {"starter": "$99/month"}}'],
            tool_history=[
                ToolResultRecord(turn=1, tool_name="get_email"),
                ToolResultRecord(turn=2, tool_name="get_product_information"),
            ],
        )
        decision = AgentDecision(
            action="FINAL",
            final_output=AgentFinalOutput(
                outcome="skip",
                message="Pricing details gathered and a reply will be sent to the customer.",
            ),
            reasoning="done",
        )
        fixed = normalize_decision(decision, "abc123", state, llm)
        assert fixed.action == "CALL_TOOL"
        assert fixed.tool_name == "send_reply"


class TestInferProductName:
    def test_novasupport_from_subject(self):
        state = AgentState(email_id="x", subject="Pricing for NovaSupport AI", body="")
        assert infer_product_name(state) == "NovaSupport AI"
