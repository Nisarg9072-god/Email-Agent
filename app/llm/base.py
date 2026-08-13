"""LLM provider abstraction."""

from abc import ABC, abstractmethod

from app.agent.schemas import EmailClassification, GeneratedReply


class LLMProvider(ABC):
    """Interface for LLM operations. Supports mock (tests) and Mistral AI (production)."""

    @abstractmethod
    def classify_email(
        self, sender: str, subject: str, body: str
    ) -> EmailClassification:
        """PROBABILISTIC: Classify email intent."""
        pass

    @abstractmethod
    def generate_reply(
        self,
        sender: str,
        subject: str,
        body: str,
        company_info: str,
    ) -> GeneratedReply:
        """PROBABILISTIC: Generate a grounded reply."""
        pass
