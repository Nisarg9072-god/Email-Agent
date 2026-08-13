"""Test that failed email send does not mark email as processed."""

from app.agent.loop import AgentLoop
from app.db.repositories import AgentRunRepository


class TestSendFailure:
    def _build_agent(self, session, mock_email_provider, mock_llm, company_tools,
                     state_manager, guardrails, validator, processed_repo, reply_repo):
        return AgentLoop(
            email_provider=mock_email_provider,
            llm=mock_llm,
            company_tools=company_tools,
            state_manager=state_manager,
            guardrails=guardrails,
            validator=validator,
            processed_repo=processed_repo,
            reply_repo=reply_repo,
            agent_run_repo=AgentRunRepository(session),
        )

    def test_failed_send_not_marked_processed(
        self, session, mock_email_provider, mock_llm, company_tools,
        state_manager, guardrails, validator, processed_repo, reply_repo,
    ):
        original_send = mock_email_provider.send_email
        mock_email_provider.send_email = lambda *a, **kw: False

        agent = self._build_agent(
            session, mock_email_provider, mock_llm, company_tools,
            state_manager, guardrails, validator, processed_repo, reply_repo,
        )
        result = agent.run()

        failed = [s for s in result.steps if s.status == "failed"]
        assert len(failed) > 0

        for step in failed:
            record = processed_repo.get(step.email_id)
            assert record.status == "failed"
            assert record.status != "processed"

        mock_email_provider.send_email = original_send
