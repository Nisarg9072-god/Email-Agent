"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    email_provider: str = "mock"
    llm_provider: str = "mock"
    mistral_api_key: str = ""
    mistral_model: str = "mistral-small-latest"
    mistral_max_retries: int = 3
    database_url: str = f"sqlite:///{DATA_DIR / 'agent.db'}"
    gmail_credentials_path: str = "credentials.json"
    gmail_token_path: str = "token.json"
    # Gmail search query for messages to process (must match Gmail search syntax)
    gmail_query: str = "in:inbox is:unread"
    # Max new unread emails to agent-process per run
    gmail_max_messages_per_run: int = 50
    # How many unread Gmail IDs to scan per run (must be >= max_messages) to find NEW mail
    gmail_unread_scan_limit: int = 100
    gmail_mark_read_after_processing: bool = True
    max_agent_steps: int = 50
    max_tool_calls: int = 10
    max_agent_turns_per_email: int = 15
    log_level: str = "INFO"
    # When true, agent re-runs after each cycle until Ctrl+C
    agent_continuous_mode: bool = False
    # Seconds to wait between cycles in continuous mode
    agent_poll_interval_seconds: int = 10

    @property
    def company_data_dir(self) -> Path:
        return DATA_DIR / "company"

    @property
    def mock_emails_path(self) -> Path:
        return DATA_DIR / "emails" / "mock_emails.json"


def get_settings() -> Settings:
    return Settings()
