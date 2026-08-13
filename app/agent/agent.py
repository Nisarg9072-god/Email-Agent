"""Agent factory - wires dependencies for the agentic runtime."""

import logging

from app.agent.runtime import AgentRuntime
from app.company.authorization import AuthorizationService
from app.company.repository import CompanyRepository
from app.company.service import CompanyDataService
from app.config import Settings
from app.db.database import Database
from app.db.repositories import AgentRunRepository, ProcessedEmailRepository, ReplyRepository
from app.email.base import EmailProvider
from app.email.gmail_provider import GmailEmailProvider
from app.email.mock_provider import MockEmailProvider
from app.harness.runtime import AgentHarness
from app.harness.state import ProcessingStateManager
from app.harness.validator import ResponseValidator
from app.llm.provider import create_llm_provider
from app.tools.agent_toolkit import AgentToolKit

logger = logging.getLogger(__name__)


def create_email_provider(settings: Settings) -> EmailProvider:
    if settings.email_provider == "gmail":
        return GmailEmailProvider(
            credentials_path=settings.gmail_credentials_path,
            token_path=settings.gmail_token_path,
        )
    return MockEmailProvider(settings.mock_emails_path)


def create_agent(settings: Settings, db: Database) -> AgentRuntime:
    """Build the agentic runtime with harness, tools, and LLM."""
    session = db.get_session()

    company_repo = CompanyRepository(settings.company_data_dir)
    authorization = AuthorizationService(company_repo)
    company_service = CompanyDataService(company_repo, authorization)

    email_provider = create_email_provider(settings)
    llm = create_llm_provider(
        settings.llm_provider,
        api_key=settings.mistral_api_key,
        model=settings.mistral_model,
        max_retries=settings.mistral_max_retries,
    )

    processed_repo = ProcessedEmailRepository(session)
    reply_repo = ReplyRepository(session)
    agent_run_repo = AgentRunRepository(session)

    state_manager = ProcessingStateManager(processed_repo)
    validator = ResponseValidator(authorization)
    toolkit = AgentToolKit(email_provider, company_service, authorization, validator)
    harness = AgentHarness(
        authorization,
        max_turns_per_email=settings.max_agent_turns_per_email,
        max_tool_calls_per_email=settings.max_tool_calls,
        max_emails_per_run=settings.max_agent_steps,
    )

    return AgentRuntime(
        email_provider=email_provider,
        llm=llm,
        toolkit=toolkit,
        harness=harness,
        state_manager=state_manager,
        processed_repo=processed_repo,
        reply_repo=reply_repo,
        agent_run_repo=agent_run_repo,
    )
