"""Mistral AI API error types."""


class MistralAPIError(Exception):
    """Base exception for Mistral API failures."""


class MistralAuthError(MistralAPIError):
    """Authentication failure (invalid or missing API key)."""


class MistralRateLimitError(MistralAPIError):
    """Rate limit exceeded."""


class MistralTimeoutError(MistralAPIError):
    """API request timed out."""


class MistralInvalidResponseError(MistralAPIError):
    """Response could not be parsed or validated."""
