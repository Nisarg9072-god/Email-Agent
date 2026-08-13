"""Authorization policy enforcement - DETERMINISTIC guardrail.

The LLM does NOT decide what information is authorized.
These rules are enforced in application code before any data reaches the LLM.
"""

import logging
from typing import Any

from app.company.repository import CompanyRepository

logger = logging.getLogger(__name__)


class AuthorizationService:
    """Filters company data to only authorized (public) fields."""

    def __init__(self, repository: CompanyRepository):
        self._repo = repository
        self._policy = repository.load_policy()
        self._public_fields: set[str] = set(self._policy["public_fields"])
        self._restricted_fields: set[str] = set(self._policy["restricted_fields"])
        self._must_not_include: set[str] = set(
            self._policy["response_rules"]["must_not_include"]
        )

    def filter_public_fields(self, data: dict) -> dict:
        """Return only fields the agent is authorized to use in customer responses."""
        return {
            key: value
            for key, value in data.items()
            if key in self._public_fields or key == "name"
        }

    def get_authorized_product(self, product_name: str) -> dict | None:
        product = self._repo.get_product_by_name(product_name)
        if product is None:
            logger.info("Product not found: %s", product_name)
            return None
        authorized = self.filter_public_fields(product)
        logger.info("Authorized product info retrieved: %s", product_name)
        return authorized

    def get_authorized_service(self, service_name: str) -> dict | None:
        service = self._repo.get_service_by_name(service_name)
        if service is None:
            logger.info("Service not found: %s", service_name)
            return None
        authorized = self.filter_public_fields(service)
        logger.info("Authorized service info retrieved: %s", service_name)
        return authorized

    def contains_restricted_content(self, text: str) -> tuple[bool, str | None]:
        """DETERMINISTIC: Check if text contains restricted information patterns."""
        text_lower = text.lower()
        restricted_patterns = {
            "internal_cost": ["development cost", "monthly infra", "infra:"],
            "customer_list": ["acme corp", "techstart inc", "globalretail", "datadriven co"],
            "employee_data": ["jane smith", "day rate", "consultant rate"],
            "confidential_roadmap": ["q3 2026:", "q4 2026:", "q2 2026:", "h2 2026", "planned for h2"],
            "internal_strategy": ["mid-market companies", "focus on mid-market"],
            "profit_margins": ["gross margin", "net margin", "profit margin"],
            "unreleased_features": ["auto-integration toolkit", "voice-enabled chatbots planned"],
            "salary": ["salary", "compensation package"],
            "revenue breakdown": ["revenue breakdown", "revenue split"],
        }

        for category, patterns in restricted_patterns.items():
            if category in self._must_not_include:
                for pattern in patterns:
                    if pattern in text_lower:
                        return True, f"restricted_content:{category}:{pattern}"

        return False, None

    def get_max_response_length(self) -> int:
        return self._policy["response_rules"]["max_response_length"]

    def get_allowed_tools(self) -> list[str]:
        return self._policy["allowed_tools"]

    def is_tool_allowed(self, tool_name: str) -> bool:
        return tool_name in self._policy["allowed_tools"]

    def is_tool_forbidden(self, tool_name: str) -> bool:
        return tool_name in self._policy.get("forbidden_tools", [])
