"""Integration tests for the agentic runtime."""

from app.agent.runtime import AgentRuntime
from app.db.repositories import AgentRunRepository
from app.harness.runtime import AgentHarness
from app.tools.agent_toolkit import AgentToolKit


class TestAgentRuntime:
    def _build_agent(
        self,
        session,
        mock_email_provider,
        mock_llm,
        authorization,
        validator,
        state_manager,
        processed_repo,
        reply_repo,
        company_service,
    ):
        toolkit = AgentToolKit(
            mock_email_provider, company_service, authorization, validator
        )
        harness = AgentHarness(authorization, max_turns_per_email=20, max_tool_calls_per_email=15)
        return AgentRuntime(
            email_provider=mock_email_provider,
            llm=mock_llm,
            toolkit=toolkit,
            harness=harness,
            state_manager=state_manager,
            processed_repo=processed_repo,
            reply_repo=reply_repo,
            agent_run_repo=AgentRunRepository(session),
        )

    def test_full_run_processes_emails(
        self, session, mock_email_provider, mock_llm, authorization, validator,
        state_manager, processed_repo, reply_repo, company_service,
    ):
        agent = self._build_agent(
            session, mock_email_provider, mock_llm, authorization, validator,
            state_manager, processed_repo, reply_repo, company_service,
        )
        mock_email_provider.reset_sent()
        result = agent.run()
        assert result.emails_found >= 10
        assert result.emails_processed > 0
        assert len(result.steps) >= 10

    def test_agent_uses_multiple_turns_for_inquiry(
        self, session, mock_email_provider, mock_llm, authorization, validator,
        state_manager, processed_repo, reply_repo, company_service,
    ):
        agent = self._build_agent(
            session, mock_email_provider, mock_llm, authorization, validator,
            state_manager, processed_repo, reply_repo, company_service,
        )
        mock_email_provider.reset_sent()
        result = agent.run()
        processed = [s for s in result.steps if s.status == "processed"]
        assert processed
        assert processed[0].agent_turns >= 3
        assert "get_email" in processed[0].tool_calls

    def test_duplicate_email_skipped_on_second_run(
        self, session, mock_email_provider, mock_llm, authorization, validator,
        state_manager, processed_repo, reply_repo, company_service,
    ):
        agent = self._build_agent(
            session, mock_email_provider, mock_llm, authorization, validator,
            state_manager, processed_repo, reply_repo, company_service,
        )
        result1 = agent.run()
        processed_first = result1.emails_processed
        result2 = agent.run()
        assert result2.emails_skipped >= processed_first

    def test_spam_email_skipped(
        self, session, mock_email_provider, mock_llm, authorization, validator,
        state_manager, processed_repo, reply_repo, company_service,
    ):
        agent = self._build_agent(
            session, mock_email_provider, mock_llm, authorization, validator,
            state_manager, processed_repo, reply_repo, company_service,
        )
        result = agent.run()
        spam = [s for s in result.steps if s.email_id == "mock-007"]
        assert spam[0].status == "skipped"

    def test_restricted_info_request_skipped(
        self, session, mock_email_provider, mock_llm, authorization, validator,
        state_manager, processed_repo, reply_repo, company_service,
    ):
        agent = self._build_agent(
            session, mock_email_provider, mock_llm, authorization, validator,
            state_manager, processed_repo, reply_repo, company_service,
        )
        result = agent.run()
        restricted = [s for s in result.steps if s.email_id == "mock-008"]
        assert restricted[0].status == "skipped"

    def test_successful_send_creates_reply_record(
        self, session, mock_email_provider, mock_llm, authorization, validator,
        state_manager, processed_repo, reply_repo, company_service,
    ):
        agent = self._build_agent(
            session, mock_email_provider, mock_llm, authorization, validator,
            state_manager, processed_repo, reply_repo, company_service,
        )
        mock_email_provider.reset_sent()
        result = agent.run()
        assert any(s.reply_sent for s in result.steps)
        assert len(mock_email_provider.sent_emails) > 0

    def test_invalid_email_handled(
        self, session, mock_email_provider, mock_llm, authorization, validator,
        state_manager, processed_repo, reply_repo, company_service,
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
            session, mock_email_provider, mock_llm, authorization, validator,
            state_manager, processed_repo, reply_repo, company_service,
        )
        result = agent.run()
        failed = [s for s in result.steps if s.email_id == "mock-001"]
        assert failed[0].status == "failed"

    def test_spam_marked_read_job_application_left_unread(
        self, session, mock_email_provider, mock_llm, authorization, validator,
        state_manager, processed_repo, reply_repo, company_service,
    ):
        agent = self._build_agent(
            session, mock_email_provider, mock_llm, authorization, validator,
            state_manager, processed_repo, reply_repo, company_service,
        )
        mock_email_provider.reset_sent()
        mock_email_provider.reset_marked_read()
        result = agent.run()
        spam = [s for s in result.steps if s.email_id == "mock-007"]
        job = [s for s in result.steps if s.email_id == "mock-005"]
        assert spam[0].status == "skipped"
        assert job[0].status == "skipped"
        assert "mock-007" in mock_email_provider.marked_read_ids
        assert "mock-005" not in mock_email_provider.marked_read_ids
        processed_ids = {s.email_id for s in result.steps if s.status == "processed"}
        assert processed_ids.issubset(set(mock_email_provider.marked_read_ids))
