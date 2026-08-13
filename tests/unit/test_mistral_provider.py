"""Tests for Mistral provider with mocked client (no real API key required)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.agent.schemas import EmailClassification, GeneratedReply
from app.llm.exceptions import (
    MistralAuthError,
    MistralInvalidResponseError,
    MistralRateLimitError,
)
from app.llm.mistral_provider import MistralProvider


def _make_parsed_response(parsed_obj):
    message = MagicMock()
    message.parsed = parsed_obj
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


class TestMistralProvider:
    def test_classify_email_success(self):
        mock_client = MagicMock()
        expected = EmailClassification(
            requires_action=True,
            is_product_or_service_inquiry=True,
            category="product_pricing",
            product_names=["NovaSupport AI"],
            reasoning="Pricing question",
        )
        mock_client.chat.parse.return_value = _make_parsed_response(expected)

        provider = MistralProvider(
            api_key="test-key",
            model="mistral-small-latest",
            client=mock_client,
        )
        result = provider.classify_email(
            "alice@test.com", "Pricing", "What does NovaSupport AI cost?"
        )

        assert result.requires_action is True
        assert result.category == "product_pricing"
        mock_client.chat.parse.assert_called_once()

    def test_generate_reply_success(self):
        mock_client = MagicMock()
        expected = GeneratedReply(
            subject="Re: Pricing",
            body="Thank you for your inquiry.",
            information_used=["NovaSupport AI"],
        )
        mock_client.chat.parse.return_value = _make_parsed_response(expected)

        provider = MistralProvider(
            api_key="test-key",
            model="mistral-small-latest",
            client=mock_client,
        )
        result = provider.generate_reply(
            "alice@test.com",
            "Pricing",
            "What does it cost?",
            "Product: NovaSupport AI - $99/month",
        )

        assert result.subject == "Re: Pricing"
        assert "Thank you" in result.body

    def test_missing_api_key_raises(self):
        with pytest.raises(MistralAuthError):
            MistralProvider(api_key="", model="mistral-small-latest")

    def test_auth_failure_not_retried(self):
        mock_client = MagicMock()
        try:
            from mistralai.client.errors import MistralError
        except ImportError:
            pytest.skip("mistralai not installed")

        raw = httpx.Response(401, request=httpx.Request("POST", "https://api.mistral.ai"))
        mock_client.chat.parse.side_effect = MistralError(
            "Unauthorized", raw_response=raw
        )

        provider = MistralProvider(
            api_key="bad-key",
            model="mistral-small-latest",
            max_retries=3,
            client=mock_client,
        )

        with pytest.raises(MistralAuthError):
            provider.classify_email("a@b.com", "Hi", "Hello")

        assert mock_client.chat.parse.call_count == 1

    def test_rate_limit_retried(self):
        mock_client = MagicMock()
        try:
            from mistralai.client.errors import MistralError
        except ImportError:
            pytest.skip("mistralai not installed")

        raw = httpx.Response(429, request=httpx.Request("POST", "https://api.mistral.ai"))
        rate_error = MistralError("Rate limited", raw_response=raw)
        expected = EmailClassification(
            requires_action=False,
            is_product_or_service_inquiry=False,
            category="spam",
            reasoning="spam",
        )

        mock_client.chat.parse.side_effect = [
            rate_error,
            _make_parsed_response(expected),
        ]

        provider = MistralProvider(
            api_key="test-key",
            model="mistral-small-latest",
            max_retries=3,
            retry_delay=0.01,
            client=mock_client,
        )
        result = provider.classify_email("a@b.com", "Spam", "You won!")
        assert result.category == "spam"
        assert mock_client.chat.parse.call_count == 2

    def test_empty_parsed_response_raises(self):
        mock_client = MagicMock()
        mock_client.chat.parse.return_value = _make_parsed_response(None)

        provider = MistralProvider(
            api_key="test-key",
            model="mistral-small-latest",
            max_retries=1,
            client=mock_client,
        )

        with pytest.raises(MistralInvalidResponseError):
            provider.classify_email("a@b.com", "Hi", "Hello")

    def test_create_llm_provider_mistral(self):
        from app.llm.provider import create_llm_provider

        with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
            create_llm_provider("mistral", api_key="", model="mistral-small-latest")

        provider = create_llm_provider(
            "mistral",
            api_key="test-key",
            model="mistral-small-latest",
            client=MagicMock(),
        )
        assert isinstance(provider, MistralProvider)

    def test_create_llm_provider_mock(self):
        from app.llm.mock_provider import MockLLMProvider
        from app.llm.provider import create_llm_provider

        provider = create_llm_provider("mock")
        assert isinstance(provider, MockLLMProvider)
