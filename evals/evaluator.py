"""Evaluation framework for probabilistic LLM behavior.

Separate from unit tests. Measures classification accuracy and reply quality.
Uses MockLLM for offline runs; prefers Mistral AI when MISTRAL_API_KEY is set.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.agent.schemas import EmailClassification
from app.company.authorization import AuthorizationService
from app.company.repository import CompanyRepository
from app.company.service import CompanyDataService
from app.config import get_settings
from app.harness.validator import ResponseValidator
from app.llm.provider import create_llm_provider
from app.tools.company_data_tools import CompanyDataTools

logger = logging.getLogger(__name__)

EVALS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EVALS_DIR.parent


@dataclass
class ClassificationEvalResult:
    email_id: str
    expected: dict
    actual: EmailClassification
    requires_action_match: bool
    inquiry_match: bool
    category_match: bool


@dataclass
class ReplyEvalResult:
    email_id: str
    reply_subject: str
    reply_body: str
    is_grounded: bool
    no_restricted_content: bool
    not_empty: bool
    issues: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    total: int = 0
    classification_results: list[ClassificationEvalResult] = field(default_factory=list)
    reply_results: list[ReplyEvalResult] = field(default_factory=list)

    @property
    def requires_action_accuracy(self) -> float:
        if not self.classification_results:
            return 0.0
        matches = sum(1 for r in self.classification_results if r.requires_action_match)
        return matches / len(self.classification_results)

    @property
    def inquiry_detection_accuracy(self) -> float:
        if not self.classification_results:
            return 0.0
        matches = sum(1 for r in self.classification_results if r.inquiry_match)
        return matches / len(self.classification_results)

    @property
    def category_accuracy(self) -> float:
        if not self.classification_results:
            return 0.0
        matches = sum(1 for r in self.classification_results if r.category_match)
        return matches / len(self.classification_results)

    @property
    def reply_groundedness_rate(self) -> float:
        if not self.reply_results:
            return 0.0
        grounded = sum(1 for r in self.reply_results if r.is_grounded and r.no_restricted_content)
        return grounded / len(self.reply_results)


class Evaluator:
    def __init__(self, llm_provider=None):
        settings = get_settings()
        provider_name = settings.llm_provider
        # Evals prefer Mistral when an API key is available
        if provider_name == "mock" and settings.mistral_api_key:
            provider_name = "mistral"
            logger.info("Evals using Mistral AI (API key detected)")

        self._llm = llm_provider or create_llm_provider(
            provider_name,
            api_key=settings.mistral_api_key,
            model=settings.mistral_model,
            max_retries=settings.mistral_max_retries,
        )

        company_repo = CompanyRepository(settings.company_data_dir)
        authorization = AuthorizationService(company_repo)
        company_service = CompanyDataService(company_repo, authorization)
        self._tools = CompanyDataTools(company_service, authorization)
        self._validator = ResponseValidator(authorization)

    def load_dataset(self) -> list[dict]:
        with open(EVALS_DIR / "dataset.json") as f:
            return json.load(f)["emails"]

    def evaluate_classification(self, emails: list[dict]) -> list[ClassificationEvalResult]:
        results = []
        for email in emails:
            actual = self._llm.classify_email(
                email["sender"], email["subject"], email["body"]
            )
            expected = email["expected"]
            results.append(
                ClassificationEvalResult(
                    email_id=email["id"],
                    expected=expected,
                    actual=actual,
                    requires_action_match=actual.requires_action == expected["requires_action"],
                    inquiry_match=actual.is_product_or_service_inquiry
                    == expected["is_product_or_service_inquiry"],
                    category_match=actual.category == expected["category"],
                )
            )
        return results

    def evaluate_replies(self, emails: list[dict]) -> list[ReplyEvalResult]:
        results = []
        for email in emails:
            expected = email["expected"]
            if not expected.get("is_product_or_service_inquiry"):
                continue

            classification = self._llm.classify_email(
                email["sender"], email["subject"], email["body"]
            )
            self._tools.reset_log()
            company_info = self._tools.gather_information_for_classification(
                classification.product_names, classification.service_names
            )
            reply = self._llm.generate_reply(
                email["sender"], email["subject"], email["body"], company_info
            )

            is_valid, val_error = self._validator.validate(
                email["sender"], reply.subject, reply.body
            )

            has_restricted, _ = self._validator._auth.contains_restricted_content(reply.body)
            issues = []
            if val_error:
                issues.append(val_error)
            if not reply.body.strip():
                issues.append("empty_reply")

            is_grounded = bool(company_info) and "No authorized" not in company_info

            results.append(
                ReplyEvalResult(
                    email_id=email["id"],
                    reply_subject=reply.subject,
                    reply_body=reply.body[:200] + "..." if len(reply.body) > 200 else reply.body,
                    is_grounded=is_grounded,
                    no_restricted_content=not has_restricted,
                    not_empty=bool(reply.body.strip()),
                    issues=issues,
                )
            )
        return results

    def run(self) -> EvalReport:
        emails = self.load_dataset()
        report = EvalReport(total=len(emails))
        report.classification_results = self.evaluate_classification(emails)
        report.reply_results = self.evaluate_replies(emails)
        return report

    def print_report(self, report: EvalReport) -> None:
        print("\n" + "=" * 60)
        print("EVALUATION REPORT")
        print("=" * 60)
        print(f"Total emails evaluated: {report.total}")
        print(f"Requires action accuracy:  {report.requires_action_accuracy:.1%}")
        print(f"Inquiry detection accuracy:{report.inquiry_detection_accuracy:.1%}")
        print(f"Category accuracy:         {report.category_accuracy:.1%}")
        print(f"Reply groundedness rate:   {report.reply_groundedness_rate:.1%}")
        print("-" * 60)

        print("\nClassification mismatches:")
        for r in report.classification_results:
            if not (r.requires_action_match and r.inquiry_match and r.category_match):
                print(f"  {r.email_id}: expected={r.expected['category']} "
                      f"actual={r.actual.category} "
                      f"(action:{r.requires_action_match} inquiry:{r.inquiry_match})")

        print("\nReply issues:")
        for r in report.reply_results:
            if r.issues:
                print(f"  {r.email_id}: {r.issues}")

        print("=" * 60)
