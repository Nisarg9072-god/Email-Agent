"""LLM provider implementations: Mock (tests/demo) and Mistral AI (production)."""

import logging

from app.llm.base import LLMProvider
from app.llm.mistral_provider import MistralProvider

logger = logging.getLogger(__name__)

# Re-export MockLLMProvider from this module for backward compatibility
from app.llm.mock_provider import MockLLMProvider  # noqa: E402


def create_llm_provider(
    provider_name: str,
    *,
    api_key: str = "",
    model: str = "",
    max_retries: int = 3,
    client=None,
) -> LLMProvider:
    """Factory for LLM providers. Application code depends on LLMProvider, not Mistral."""
    if provider_name == "mistral":
        if not api_key:
            raise ValueError("MISTRAL_API_KEY required when LLM_PROVIDER=mistral")
        if not model:
            raise ValueError("MISTRAL_MODEL required when LLM_PROVIDER=mistral")
        return MistralProvider(
            api_key=api_key,
            model=model,
            max_retries=max_retries,
            client=client,
        )

    if provider_name == "mock":
        return MockLLMProvider()

    raise ValueError(
        f"Unknown LLM provider: {provider_name}. Use 'mock' or 'mistral'."
    )
