"""Controlled company data tools for the agent.

These are the ONLY way the LLM accesses company information.
There is NO execute_sql, query_database, or arbitrary data access tool.

Architecture:
  LLM -> CompanyDataTools -> CompanyDataService -> AuthorizationService -> Repository
"""

import json
import logging

from app.company.authorization import AuthorizationService
from app.company.service import CompanyDataService

logger = logging.getLogger(__name__)

ALLOWED_TOOLS = {"get_product_information", "get_service_information"}


class CompanyDataTools:
    """Explicit, authorized tools the agent can use to retrieve company info."""

    def __init__(self, company_service: CompanyDataService, authorization: AuthorizationService):
        self._service = company_service
        self._auth = authorization
        self._call_log: list[dict] = []

    def get_available_tools(self) -> list[str]:
        return list(ALLOWED_TOOLS)

    def call_tool(self, tool_name: str, **kwargs) -> dict | None:
        """DETERMINISTIC: Enforce tool authorization before execution."""
        if self._auth.is_tool_forbidden(tool_name):
            logger.warning("Forbidden tool call blocked: %s", tool_name)
            self._call_log.append({"tool": tool_name, "status": "forbidden"})
            return None

        if tool_name not in ALLOWED_TOOLS:
            logger.warning("Unknown tool call rejected: %s", tool_name)
            self._call_log.append({"tool": tool_name, "status": "rejected"})
            return None

        result = None
        if tool_name == "get_product_information":
            result = self._service.get_product_information(kwargs.get("product_name", ""))
        elif tool_name == "get_service_information":
            result = self._service.get_service_information(kwargs.get("service_name", ""))

        self._call_log.append({
            "tool": tool_name,
            "arguments": kwargs,
            "status": "success" if result else "not_found",
        })
        logger.info("Tool call: %s(%s) -> %s", tool_name, kwargs, "found" if result else "not_found")
        return result

    def gather_information_for_classification(
        self, product_names: list[str], service_names: list[str]
    ) -> str:
        """Retrieve authorized info for all mentioned products/services."""
        sections = []

        for name in product_names:
            info = self.call_tool("get_product_information", product_name=name)
            if info:
                sections.append(f"Product: {json.dumps(info, indent=2)}")

        for name in service_names:
            info = self.call_tool("get_service_information", service_name=name)
            if info:
                sections.append(f"Service: {json.dumps(info, indent=2)}")

        if not sections:
            return "No authorized company information available for this inquiry."

        return "\n\n".join(sections)

    @property
    def call_log(self) -> list[dict]:
        return list(self._call_log)

    def reset_log(self) -> None:
        self._call_log.clear()
