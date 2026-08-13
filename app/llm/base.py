"""LLM provider abstraction."""

from abc import ABC, abstractmethod

from app.agent.schemas import AgentDecision, EmailClassification, GeneratedReply
from app.agent.state import AgentState


class LLMProvider(ABC):
    """Interface for LLM operations. Supports mock (tests) and Mistral AI (production)."""

    @abstractmethod
    def decide_next_action(self, state: AgentState, tool_catalog: str) -> AgentDecision:
        """PROBABILISTIC: Agent chooses next tool or FINAL based on current state."""
        pass

    @abstractmethod
    def classify_email(
        self, sender: str, subject: str, body: str
    ) -> EmailClassification:
        """PROBABILISTIC: Classify email intent (used by evals)."""
        pass

    @abstractmethod
    def generate_reply(
        self,
        sender: str,
        subject: str,
        body: str,
        company_info: str,
    ) -> GeneratedReply:
        """PROBABILISTIC: Generate a grounded reply (used by evals)."""
        pass
