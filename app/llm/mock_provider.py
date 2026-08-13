"""Rule-based LLM mock for unit tests and $0 demo.

Uses keyword matching for classification and template-based replies.
No API key required. Used when LLM_PROVIDER=mock.
"""

import logging

from app.agent.schemas import EmailClassification, GeneratedReply
from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class MockLLMProvider(LLMProvider):
    """Deterministic mock — not Mistral. For tests and offline demo only."""

    PRODUCT_KEYWORDS = {
        "novasupport ai": "NovaSupport AI",
        "novasupport": "NovaSupport AI",
        "novaanalytics": "NovaAnalytics",
        "nova analytics": "NovaAnalytics",
    }

    SERVICE_KEYWORDS = {
        "ai consulting": "AI consulting",
        "consulting services": "AI consulting",
        "custom ai integration": "Custom AI integration",
        "chatbot implementation": "AI chatbot implementation",
        "chatbot": "AI chatbot implementation",
    }

    def classify_email(
        self, sender: str, subject: str, body: str
    ) -> EmailClassification:
        text = f"{subject} {body}".lower()

        if any(kw in text for kw in ["won $", "lottery", "click here to claim"]):
            return EmailClassification(
                requires_action=False,
                is_product_or_service_inquiry=False,
                category="spam",
                reasoning="Detected spam/lottery content",
            )

        if "ml engineer" in text or "job" in text and "application" in text or "resume" in text:
            return EmailClassification(
                requires_action=False,
                is_product_or_service_inquiry=False,
                category="job_application",
                reasoning="Job application detected",
            )

        if "partnership" in text or "resell" in text:
            return EmailClassification(
                requires_action=False,
                is_product_or_service_inquiry=False,
                category="partnership",
                reasoning="Partnership inquiry - routed to partnerships team",
            )

        restricted_kw = [
            "internal cost", "profit margin", "confidential roadmap",
            "current customers", "internal pricing", "confidential product roadmap",
            "day rate",
        ]
        if any(kw in text for kw in restricted_kw):
            return EmailClassification(
                requires_action=True,
                is_product_or_service_inquiry=False,
                category="restricted_info_request",
                reasoning="Request for restricted/confidential information",
            )

        product_names = []
        for kw, name in self.PRODUCT_KEYWORDS.items():
            if kw in text and name not in product_names:
                product_names.append(name)

        service_names = []
        for kw, name in self.SERVICE_KEYWORDS.items():
            if kw in text and name not in service_names:
                service_names.append(name)

        is_inquiry = bool(product_names or service_names)

        if "demo" in text:
            return EmailClassification(
                requires_action=True,
                is_product_or_service_inquiry=True,
                category="demo_request",
                product_names=product_names or ["NovaSupport AI"],
                service_names=service_names,
                reasoning="Demo request for product",
            )

        if "pricing" in text or "price" in text or "cost" in text and "month" in text:
            return EmailClassification(
                requires_action=True,
                is_product_or_service_inquiry=True,
                category="product_pricing",
                product_names=product_names,
                service_names=service_names,
                reasoning="Pricing inquiry detected",
            )

        if "feature" in text or "integration" in text or "support" in text and product_names:
            return EmailClassification(
                requires_action=True,
                is_product_or_service_inquiry=True,
                category="product_features",
                product_names=product_names,
                service_names=service_names,
                reasoning="Feature/integration inquiry detected",
            )

        if service_names and "custom ai" in text:
            return EmailClassification(
                requires_action=True,
                is_product_or_service_inquiry=True,
                category="service_inquiry",
                product_names=product_names,
                service_names=service_names,
                reasoning="Custom AI integration service inquiry",
            )

        if service_names:
            return EmailClassification(
                requires_action=True,
                is_product_or_service_inquiry=True,
                category="service_inquiry",
                product_names=product_names,
                service_names=service_names,
                reasoning="Service inquiry detected",
            )

        if is_inquiry:
            return EmailClassification(
                requires_action=True,
                is_product_or_service_inquiry=True,
                category="other",
                product_names=product_names,
                service_names=service_names,
                reasoning="General product/service inquiry",
            )

        if "novaai" in text:
            return EmailClassification(
                requires_action=True,
                is_product_or_service_inquiry=True,
                category="other",
                reasoning="General NovaAI inquiry",
            )

        return EmailClassification(
            requires_action=False,
            is_product_or_service_inquiry=False,
            category="other",
            reasoning="No product/service inquiry detected",
        )

    def generate_reply(
        self,
        sender: str,
        subject: str,
        body: str,
        company_info: str,
    ) -> GeneratedReply:
        reply_subject = f"Re: {subject}"
        info_used = []

        for name in [
            "NovaSupport AI", "NovaAnalytics", "AI consulting",
            "Custom AI integration", "AI chatbot implementation",
        ]:
            if name in company_info:
                info_used.append(name)

        reply_body = (
            f"Dear {sender.split('@')[0].split('<')[-1].title()},\n\n"
            f"Thank you for reaching out to NovaAI.\n\n"
            f"Based on your inquiry, here is the information I can share:\n\n"
            f"{company_info}\n\n"
            f"Please note that I can only share publicly available information. "
            f"If you need further assistance or would like to discuss enterprise options, "
            f"our sales team would be happy to help.\n\n"
            f"Best regards,\n"
            f"NovaAI Support Team"
        )

        return GeneratedReply(
            subject=reply_subject,
            body=reply_body,
            information_used=info_used,
        )
