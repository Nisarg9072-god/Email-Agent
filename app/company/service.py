"""Company data service - application layer between tools and repository.

Enforces authorization before returning data to the agent/LLM.
"""

import logging

from app.company.authorization import AuthorizationService
from app.company.repository import CompanyRepository

logger = logging.getLogger(__name__)


class CompanyDataService:
    """Controlled access to company information."""

    def __init__(self, repository: CompanyRepository, authorization: AuthorizationService):
        self._repo = repository
        self._auth = authorization

    def get_product_information(self, product_name: str) -> dict | None:
        """Return authorized product information only."""
        return self._auth.get_authorized_product(product_name)

    def get_service_information(self, service_name: str) -> dict | None:
        """Return authorized service information only."""
        return self._auth.get_authorized_service(service_name)

    def get_available_products(self) -> list[str]:
        """Return product names only (no detailed data)."""
        return self._repo.list_product_names()

    def get_available_services(self) -> list[str]:
        """Return service names only (no detailed data)."""
        return self._repo.list_service_names()
