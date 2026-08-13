"""Tests for company data authorization (Guardrail #2)."""

from app.tools.company_data_tools import ALLOWED_TOOLS, CompanyDataTools


class TestAuthorization:
    def test_authorized_product_info(self, company_tools):
        info = company_tools.call_tool(
            "get_product_information", product_name="NovaSupport AI"
        )
        assert info is not None
        assert info["name"] == "NovaSupport AI"
        assert "public_pricing" in info
        assert "internal_cost" not in info
        assert "customer_list" not in info
        assert "profit_margins" not in info

    def test_authorized_service_info(self, company_tools):
        info = company_tools.call_tool(
            "get_service_information", service_name="AI consulting"
        )
        assert info is not None
        assert "public_pricing" in info
        assert "internal_cost" not in info
        assert "employee_data" not in info

    def test_restricted_fields_not_returned(self, company_tools, company_repo):
        raw = company_repo.get_product_by_name("NovaSupport AI")
        assert "internal_cost" in raw

        authorized = company_tools.call_tool(
            "get_product_information", product_name="NovaSupport AI"
        )
        assert "internal_cost" not in authorized

    def test_forbidden_tool_blocked(self, company_tools):
        result = company_tools.call_tool("execute_sql", query="SELECT * FROM products")
        assert result is None

        result = company_tools.call_tool("query_database", table="customers")
        assert result is None

    def test_unknown_tool_rejected(self, company_tools):
        result = company_tools.call_tool("list_all_products")
        assert result is None

    def test_only_allowed_tools_exist(self, company_tools):
        available = company_tools.get_available_tools()
        assert available == list(ALLOWED_TOOLS)
        assert "execute_sql" not in available
        assert "query_database" not in available

    def test_nonexistent_product_returns_none(self, company_tools):
        result = company_tools.call_tool(
            "get_product_information", product_name="NonExistent Product"
        )
        assert result is None
