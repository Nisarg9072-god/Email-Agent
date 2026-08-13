"""Company data repository - reads from JSON files.

This layer has access to ALL company data (public + restricted).
Authorization filtering happens in the service layer, NOT here.
The LLM never receives this repository directly.
"""

import json
from pathlib import Path


class CompanyRepository:
    """Data access for company knowledge base (JSON files)."""

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._products: list[dict] | None = None
        self._services: list[dict] | None = None
        self._policy: dict | None = None

    def _load_products(self) -> list[dict]:
        if self._products is None:
            with open(self._data_dir / "products.json") as f:
                self._products = json.load(f)["products"]
        return self._products

    def _load_services(self) -> list[dict]:
        if self._services is None:
            with open(self._data_dir / "services.json") as f:
                self._services = json.load(f)["services"]
        return self._services

    def load_policy(self) -> dict:
        if self._policy is None:
            with open(self._data_dir / "authorization_policy.json") as f:
                self._policy = json.load(f)
        return self._policy

    def get_product_by_name(self, name: str) -> dict | None:
        name_lower = name.lower()
        for product in self._load_products():
            if product["name"].lower() == name_lower:
                return product
        return None

    def get_service_by_name(self, name: str) -> dict | None:
        name_lower = name.lower()
        for service in self._load_services():
            if service["name"].lower() == name_lower:
                return service
        return None

    def list_product_names(self) -> list[str]:
        return [p["name"] for p in self._load_products()]

    def list_service_names(self) -> list[str]:
        return [s["name"] for s in self._load_services()]
