"""Mistral AI LLM provider with structured outputs and retry handling.

The Mistral model never receives database connections or credentials.
It only produces classification and reply text for the agent loop.
"""

import logging
import time
from typing import Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.agent.prompts import (
    CLASSIFICATION_SYSTEM_PROMPT,
    CLASSIFICATION_USER_PROMPT,
    REPLY_SYSTEM_PROMPT,
    REPLY_USER_PROMPT,
)
from app.agent.schemas import EmailClassification, GeneratedReply
from app.llm.base import LLMProvider
from app.llm.exceptions import (
    MistralAPIError,
    MistralAuthError,
    MistralInvalidResponseError,
    MistralRateLimitError,
    MistralTimeoutError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class MistralProvider(LLMProvider):
    """Mistral AI provider using structured Pydantic outputs via chat.parse."""

    def __init__(
        self,
        api_key: str,
        model: str,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        timeout: float = 30.0,
        client=None,
    ):
        if not api_key:
            raise MistralAuthError("MISTRAL_API_KEY is required for Mistral provider")

        self._api_key = api_key
        self._model = model
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._timeout = timeout
        self._client = client  # injectable for unit tests

    def _get_client(self):
        if self._client is not None:
            return self._client

        try:
            from mistralai.client import Mistral
        except ImportError as exc:
            raise RuntimeError(
                "mistralai package not installed. Run: pip install mistralai"
            ) from exc

        return Mistral(api_key=self._api_key, timeout_ms=int(self._timeout * 1000))

    def _parse_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
    ) -> T:
        """Call Mistral chat.parse with retries and Pydantic validation."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                client = self._get_client()
                response = client.chat.parse(
                    model=self._model,
                    messages=messages,
                    response_format=response_model,
                    temperature=0.3,
                )

                if not response.choices:
                    raise MistralInvalidResponseError("Mistral returned no choices")

                message = response.choices[0].message
                if message is None or message.parsed is None:
                    raise MistralInvalidResponseError(
                        "Mistral returned empty or unparseable structured response"
                    )

                return response_model.model_validate(message.parsed)

            except ValidationError as exc:
                raise MistralInvalidResponseError(
                    f"Response failed Pydantic validation: {exc}"
                ) from exc

            except httpx.TimeoutException as exc:
                last_error = MistralTimeoutError(f"Mistral API timeout: {exc}")
                logger.warning(
                    "Mistral timeout (attempt %d/%d)", attempt + 1, self._max_retries
                )

            except Exception as exc:
                mapped = self._map_exception(exc)
                if isinstance(mapped, MistralAuthError):
                    raise mapped

                if isinstance(mapped, (MistralRateLimitError, MistralTimeoutError)):
                    last_error = mapped
                elif isinstance(mapped, MistralAPIError) and self._is_retryable(exc):
                    last_error = mapped
                else:
                    raise mapped

                logger.warning(
                    "Mistral API error (attempt %d/%d): %s",
                    attempt + 1,
                    self._max_retries,
                    mapped,
                )

            if attempt < self._max_retries - 1:
                delay = self._retry_delay * (2 ** attempt)
                time.sleep(delay)

        raise last_error or MistralAPIError("Mistral API call failed after retries")

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        try:
            from mistralai.client.errors import MistralError

            if isinstance(exc, MistralError):
                return exc.status_code in RETRYABLE_STATUS_CODES
        except ImportError:
            pass
        return False

    @staticmethod
    def _map_exception(exc: Exception) -> MistralAPIError:
        try:
            from mistralai.client.errors import MistralError
        except ImportError:
            return MistralAPIError(str(exc))

        if isinstance(exc, MistralError):
            if exc.status_code == 401:
                return MistralAuthError(f"Mistral authentication failed: {exc.message}")
            if exc.status_code == 429:
                return MistralRateLimitError(f"Mistral rate limit exceeded: {exc.message}")
            if exc.status_code in RETRYABLE_STATUS_CODES:
                return MistralAPIError(
                    f"Mistral temporary failure ({exc.status_code}): {exc.message}"
                )
            return MistralAPIError(f"Mistral API error ({exc.status_code}): {exc.message}")

        if isinstance(exc, MistralInvalidResponseError):
            return exc

        return MistralAPIError(str(exc))

    def classify_email(
        self, sender: str, subject: str, body: str
    ) -> EmailClassification:
        user_prompt = CLASSIFICATION_USER_PROMPT.format(
            sender=sender, subject=subject, body=body
        )
        return self._parse_structured(
            CLASSIFICATION_SYSTEM_PROMPT, user_prompt, EmailClassification
        )

    def generate_reply(
        self,
        sender: str,
        subject: str,
        body: str,
        company_info: str,
    ) -> GeneratedReply:
        user_prompt = REPLY_USER_PROMPT.format(
            sender=sender,
            subject=subject,
            body=body,
            company_info=company_info,
        )
        return self._parse_structured(
            REPLY_SYSTEM_PROMPT, user_prompt, GeneratedReply
        )
