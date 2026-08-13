"""Shared test fixtures."""

import pytest
from pathlib import Path

from app.company.authorization import AuthorizationService
from app.company.repository import CompanyRepository
from app.company.service import CompanyDataService
from app.config import Settings
from app.db.database import Database
from app.db.repositories import ProcessedEmailRepository, ReplyRepository
from app.email.mock_provider import MockEmailProvider
from app.harness.guardrails import AgentGuardrails
from app.harness.state import ProcessingStateManager
from app.harness.validator import ResponseValidator
from app.llm.provider import MockLLMProvider
from app.tools.company_data_tools import CompanyDataTools

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


@pytest.fixture
def settings(tmp_path):
    db_path = tmp_path / "test.db"
    return Settings(
        database_url=f"sqlite:///{db_path}",
        email_provider="mock",
        llm_provider="mock",
    )


@pytest.fixture
def db(settings):
    return Database(settings.database_url)


@pytest.fixture
def session(db):
    with db.session() as s:
        yield s


@pytest.fixture
def company_repo():
    return CompanyRepository(DATA_DIR / "company")


@pytest.fixture
def authorization(company_repo):
    return AuthorizationService(company_repo)


@pytest.fixture
def company_service(company_repo, authorization):
    return CompanyDataService(company_repo, authorization)


@pytest.fixture
def company_tools(company_service, authorization):
    return CompanyDataTools(company_service, authorization)


@pytest.fixture
def mock_email_provider():
    return MockEmailProvider(DATA_DIR / "emails" / "mock_emails.json")


@pytest.fixture
def mock_llm():
    return MockLLMProvider()


@pytest.fixture
def processed_repo(session):
    return ProcessedEmailRepository(session)


@pytest.fixture
def reply_repo(session):
    return ReplyRepository(session)


@pytest.fixture
def state_manager(processed_repo):
    return ProcessingStateManager(processed_repo)


@pytest.fixture
def guardrails(authorization):
    return AgentGuardrails(authorization, max_steps=50, max_tool_calls=10)


@pytest.fixture
def validator(authorization):
    return ResponseValidator(authorization)
