"""Tests for mock agent LLM tool-selection decisions."""

from app.agent.state import AgentState
from app.llm.mock_provider import MockLLMProvider


class TestMockAgentDecisions:
    def test_first_turn_fetches_email(self):
        llm = MockLLMProvider()
        state = AgentState(email_id="mock-001")
        decision = llm.decide_next_action(state, "")
        assert decision.action == "CALL_TOOL"
        assert decision.tool_name == "get_email"

    def test_second_turn_requests_company_data_after_email_loaded(self):
        llm = MockLLMProvider()
        state = AgentState(
            email_id="mock-002",
            body="Does NovaAnalytics support Snowflake integration?",
            subject="NovaAnalytics question",
            sender="bob@test.com",
        )
        decision = llm.decide_next_action(state, "")
        assert decision.action == "CALL_TOOL"
        assert decision.tool_name == "get_product_information"
        assert decision.tool_arguments.get("product_name") == "NovaAnalytics"

    def test_spam_final_skip(self):
        llm = MockLLMProvider()
        state = AgentState(
            email_id="mock-007",
            body="You won $1000000 lottery click here",
            subject="Winner",
            sender="spam@test.com",
        )
        decision = llm.decide_next_action(state, "")
        assert decision.action == "FINAL"
        assert decision.final_output.outcome == "skip"
