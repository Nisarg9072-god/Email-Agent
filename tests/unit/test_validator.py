"""Tests for response validation."""

from app.harness.validator import ResponseValidator


class TestResponseValidator:
    def test_valid_response(self, validator):
        valid, reason = validator.validate(
            "alice@test.com", "Re: Pricing", "Thank you for your inquiry about NovaSupport AI."
        )
        assert valid is True
        assert reason is None

    def test_empty_body_rejected(self, validator):
        valid, reason = validator.validate("alice@test.com", "Re: Test", "")
        assert valid is False
        assert reason == "empty_body"

    def test_empty_recipient_rejected(self, validator):
        valid, reason = validator.validate("", "Re: Test", "Hello")
        assert valid is False
        assert reason == "empty_recipient"

    def test_restricted_content_detected(self, validator):
        valid, reason = validator.validate(
            "spy@test.com",
            "Re: Info",
            "Our gross margin is 72% and development cost was $2.1M.",
        )
        assert valid is False
        assert "restricted_content" in reason

    def test_customer_names_blocked(self, validator):
        valid, reason = validator.validate(
            "spy@test.com",
            "Re: Customers",
            "Our customers include Acme Corp and TechStart Inc.",
        )
        assert valid is False

    def test_response_too_long(self, validator):
        valid, reason = validator.validate(
            "test@test.com", "Re: Test", "x" * 6000
        )
        assert valid is False
        assert "response_too_long" in reason
