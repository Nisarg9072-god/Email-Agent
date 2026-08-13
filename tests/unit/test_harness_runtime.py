"""Tests for agent harness runtime controls."""

import pytest

from app.agent.schemas import AgentDecision, AgentFinalOutput
from app.agent.state import AgentState
from app.harness.runtime import AgentHarness, HarnessValidationError


class TestAgentHarness:
    def test_allows_registered_tool(self, authorization):
        harness = AgentHarness(authorization)
        state = AgentState(email_id="e1", turn=1)
        decision = AgentDecision(
            action="CALL_TOOL",
            tool_name="get_email",
            tool_arguments={"email_id": "e1"},
        )
        harness.validate_decision(decision, state)

    def test_blocks_unregistered_tool(self, authorization):
        harness = AgentHarness(authorization)
        state = AgentState(email_id="e1", turn=1)
        decision = AgentDecision(
            action="CALL_TOOL",
            tool_name="execute_sql",
            tool_arguments={"query": "SELECT 1"},
        )
        with pytest.raises(HarnessValidationError, match="tool_not_registered|tool_forbidden"):
            harness.validate_decision(decision, state)

    def test_blocks_max_tool_calls(self, authorization):
        harness = AgentHarness(authorization, max_tool_calls_per_email=2)
        state = AgentState(email_id="e1", turn=1, tool_call_count=2)
        decision = AgentDecision(
            action="CALL_TOOL",
            tool_name="get_email",
            tool_arguments={"email_id": "e1"},
        )
        with pytest.raises(HarnessValidationError, match="max_tool_calls"):
            harness.validate_decision(decision, state)

    def test_blocks_max_turns(self, authorization):
        harness = AgentHarness(authorization, max_turns_per_email=3)
        state = AgentState(email_id="e1", turn=3)
        decision = AgentDecision(
            action="FINAL",
            final_output=AgentFinalOutput(outcome="skip"),
        )
        with pytest.raises(HarnessValidationError, match="max_turns"):
            harness.validate_decision(decision, state)

    def test_final_requires_output(self, authorization):
        harness = AgentHarness(authorization)
        state = AgentState(email_id="e1", turn=1)
        decision = AgentDecision(action="FINAL")
        with pytest.raises(HarnessValidationError, match="final_output"):
            harness.validate_decision(decision, state)

    def test_email_id_mismatch_blocked(self, authorization):
        harness = AgentHarness(authorization)
        state = AgentState(email_id="e1", turn=1)
        decision = AgentDecision(
            action="CALL_TOOL",
            tool_name="get_email",
            tool_arguments={"email_id": "other"},
        )
        with pytest.raises(HarnessValidationError, match="email_id_mismatch"):
            harness.validate_decision(decision, state)
