"""Integration tests for the agent loop."""

from app.agent.loop import AgentLoop
from app.db.repositories import AgentRunRepository
from app.harness.guardrails import AgentGuardrails


class TestAgentLoop:
    def _build_agent(
        self,
        session,
        mock_email_provider,
        mock_llm,
        company_tools,
        state_manager,
        guardrails,
        validator,
        processed_repo,
        reply_repo,
    ):
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

    def test_full_run_processes_emails(
        self, session, mock_email_provider, mock_llm, company_tools,
        state_manager, guardrails, validator, processed_repo, reply_repo,
    ):
        agent = self._build_agent(
            session, mock_email_provider, mock_llm, company_tools,
            state_manager, guardrails, validator, processed_repo, reply_repo,
        )
        mock_email_provider.reset_sent()
        result = agent.run()

        assert result.emails_found == 10
        assert result.emails_processed > 0
        assert len(result.steps) == 10

    def test_duplicate_email_skipped_on_second_run(
        self, session, mock_email_provider, mock_llm, company_tools,
        state_manager, guardrails, validator, processed_repo, reply_repo,
    ):
        agent = self._build_agent(
            session, mock_email_provider, mock_llm, company_tools,
            state_manager, guardrails, validator, processed_repo, reply_repo,
        )

        result1 = agent.run()
        processed_first = result1.emails_processed

        result2 = agent.run()
        assert result2.emails_skipped >= processed_first

    def test_spam_email_skipped(
        self, session, mock_email_provider, mock_llm, company_tools,
        state_manager, guardrails, validator, processed_repo, reply_repo,
    ):
        agent = self._build_agent(
            session, mock_email_provider, mock_llm, company_tools,
            state_manager, guardrails, validator, processed_repo, reply_repo,
        )
        result = agent.run()

        spam_steps = [s for s in result.steps if s.email_id == "mock-007"]
        assert len(spam_steps) == 1
        assert spam_steps[0].status == "skipped"

    def test_restricted_info_request_skipped(
        self, session, mock_email_provider, mock_llm, company_tools,
        state_manager, guardrails, validator, processed_repo, reply_repo,
    ):
        agent = self._build_agent(
            session, mock_email_provider, mock_llm, company_tools,
            state_manager, guardrails, validator, processed_repo, reply_repo,
        )
        result = agent.run()

        restricted = [s for s in result.steps if s.email_id == "mock-008"]
        assert len(restricted) == 1
        assert restricted[0].status == "skipped"

    def test_successful_send_creates_reply_record(
        self, session, mock_email_provider, mock_llm, company_tools,
        state_manager, guardrails, validator, processed_repo, reply_repo,
    ):
        agent = self._build_agent(
            session, mock_email_provider, mock_llm, company_tools,
            state_manager, guardrails, validator, processed_repo, reply_repo,
        )
        mock_email_provider.reset_sent()
        result = agent.run()

        processed = [s for s in result.steps if s.reply_sent]
        assert len(processed) > 0
        assert len(mock_email_provider.sent_emails) > 0

    def test_invalid_email_handled(
        self, session, mock_email_provider, mock_llm, company_tools,
        state_manager, guardrails, validator, processed_repo, reply_repo,
    ):
        from app.email.base import EmailMessage

        original_get = mock_email_provider.get_email

        def get_empty(email_id):
            if email_id == "mock-001":
                return EmailMessage(
                    email_id="mock-001", sender="", recipient="", subject="", body=""
                )
            return original_get(email_id)

        mock_email_provider.get_email = get_empty

        agent = self._build_agent(
            session, mock_email_provider, mock_llm, company_tools,
            state_manager, guardrails, validator, processed_repo, reply_repo,
        )
        result = agent.run()

        failed = [s for s in result.steps if s.email_id == "mock-001"]
        assert failed[0].status == "failed"

    def test_guardrails_block_forbidden_categories(self, authorization):
        from app.agent.schemas import EmailClassification

        g = AgentGuardrails(authorization)
        classification = EmailClassification(
            requires_action=False,
            is_product_or_service_inquiry=False,
            category="spam",
            reasoning="spam",
        )
        should, reason = g.should_respond_to_classification(classification)
        assert should is False
