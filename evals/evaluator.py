"""Evaluation framework for probabilistic LLM behavior.

Supports mock-only offline runs (default) and optional Mistral via --mistral.

Metrics:
- Classification accuracy (classify_email — reference / legacy path)
- Agent decision accuracy (decide_next_action on dataset-derived states)
- Runtime routing accuracy (full AgentRuntime end-to-end per eval email)
- Reply groundedness (generate_reply + validation on inquiry cases)
"""

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.agent.agent import create_agent
from app.agent.schemas import AgentDecision, EmailClassification
from app.agent.state import AgentState
from app.company.authorization import AuthorizationService
from app.company.repository import CompanyRepository
from app.company.service import CompanyDataService
from app.config import Settings, get_settings
from app.db.database import Database
from app.harness.validator import ResponseValidator
from app.llm.provider import create_llm_provider
from app.tools.agent_toolkit import AgentToolKit
from app.tools.registry import tools_for_llm_prompt
from evals.eval_email_provider import DatasetEmailProvider
from evals.routing_expectations import expected_routing, routing_matches

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
class AgentDecisionEvalResult:
    case_id: str
    state_description: str
    expected_tool: str | None
    expected_action: str
    actual: AgentDecision
    match: bool


@dataclass
class RuntimeEvalResult:
    email_id: str
    expected: dict
    actual_status: str
    actual_reply_sent: bool
    actual_skip_reason: str | None
    tool_calls: list[str]
    agent_turns: int
    match: bool
    error_message: str | None = None


@dataclass
class EvalReport:
    total: int = 0
    provider: str = "mock"
    classification_results: list[ClassificationEvalResult] = field(default_factory=list)
    reply_results: list[ReplyEvalResult] = field(default_factory=list)
    agent_decision_results: list[AgentDecisionEvalResult] = field(default_factory=list)
    runtime_results: list[RuntimeEvalResult] = field(default_factory=list)

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
    def agent_decision_accuracy(self) -> float:
        if not self.agent_decision_results:
            return 0.0
        return sum(1 for r in self.agent_decision_results if r.match) / len(
            self.agent_decision_results
        )

    @property
    def runtime_routing_accuracy(self) -> float:
        if not self.runtime_results:
            return 0.0
        return sum(1 for r in self.runtime_results if r.match) / len(self.runtime_results)

    @property
    def reply_groundedness_rate(self) -> float:
        if not self.reply_results:
            return 0.0
        grounded = sum(1 for r in self.reply_results if r.is_grounded and r.no_restricted_content)
        return grounded / len(self.reply_results)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "provider": self.provider,
            "requires_action_accuracy": round(self.requires_action_accuracy, 4),
            "inquiry_detection_accuracy": round(self.inquiry_detection_accuracy, 4),
            "category_accuracy": round(self.category_accuracy, 4),
            "agent_decision_accuracy": round(self.agent_decision_accuracy, 4),
            "runtime_routing_accuracy": round(self.runtime_routing_accuracy, 4),
            "reply_groundedness_rate": round(self.reply_groundedness_rate, 4),
            "runtime_mismatches": [
                {
                    "email_id": r.email_id,
                    "expected": r.expected,
                    "actual_status": r.actual_status,
                    "reply_sent": r.actual_reply_sent,
                    "skip_reason": r.actual_skip_reason,
                    "tool_calls": r.tool_calls,
                }
                for r in self.runtime_results
                if not r.match
            ],
            "classification_mismatches": [
                r.email_id
                for r in self.classification_results
                if not (r.requires_action_match and r.inquiry_match and r.category_match)
            ],
        }


class Evaluator:
    def __init__(self, llm_provider=None, *, force_mock: bool | None = None):
        settings = get_settings()
        if force_mock is None:
            force_mock = os.getenv("EVAL_FORCE_MOCK", "true").lower() in {"1", "true", "yes"}

        if force_mock:
            provider_name = "mock"
            logger.info("Evals using MockLLM (offline, no API calls)")
        else:
            provider_name = settings.llm_provider
            if provider_name == "mock" and settings.mistral_api_key:
                provider_name = "mistral"
                logger.info("Evals using Mistral AI (API key detected)")

        self._provider_name = provider_name
        self._llm = llm_provider or create_llm_provider(
            provider_name,
            api_key=settings.mistral_api_key,
            model=settings.mistral_model,
            max_retries=settings.mistral_max_retries,
        )

        company_repo = CompanyRepository(settings.company_data_dir)
        authorization = AuthorizationService(company_repo)
        company_service = CompanyDataService(company_repo, authorization)
        self._authorization = authorization
        self._company_service = company_service
        self._validator = ResponseValidator(authorization)
        self._settings = settings

    def load_dataset(self) -> list[dict]:
        with open(EVALS_DIR / "dataset.json", encoding="utf-8") as f:
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
        """Reply quality using AgentToolKit gather path (aligned with runtime tools)."""
        results = []
        toolkit = AgentToolKit(
            DatasetEmailProvider([]),
            self._company_service,
            self._authorization,
            self._validator,
        )

        for email in emails:
            expected = email["expected"]
            if not expected.get("is_product_or_service_inquiry"):
                continue

            classification = self._llm.classify_email(
                email["sender"], email["subject"], email["body"]
            )
            company_chunks: list[str] = []
            for product in classification.product_names:
                raw = toolkit.execute(
                    "get_product_information",
                    {"product_name": product},
                    AgentState(email_id=email["id"]),
                )
                if raw.success:
                    company_chunks.append(raw.output)
            for service in classification.service_names:
                raw = toolkit.execute(
                    "get_service_information",
                    {"service_name": service},
                    AgentState(email_id=email["id"]),
                )
                if raw.success:
                    company_chunks.append(raw.output)

            company_info = "\n\n".join(company_chunks) if company_chunks else ""
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

    def evaluate_agent_decisions(self, emails: list[dict]) -> list[AgentDecisionEvalResult]:
        """decide_next_action accuracy on dataset-derived agent states."""
        catalog = tools_for_llm_prompt()
        results: list[AgentDecisionEvalResult] = []

        # Universal first turn: no body loaded yet
        empty = AgentState(email_id="dec-empty")
        actual = self._llm.decide_next_action(empty, catalog)
        results.append(
            AgentDecisionEvalResult(
                "dec-empty",
                "no body",
                "get_email",
                "CALL_TOOL",
                actual,
                actual.action == "CALL_TOOL" and actual.tool_name == "get_email",
            )
        )

        for email in emails:
            eid = email["id"]
            state = AgentState(
                email_id=eid,
                sender=email["sender"],
                subject=email["subject"],
                body=email["body"],
            )
            exp = expected_routing(email)
            actual = self._llm.decide_next_action(state, catalog)

            if exp["status"] == "processed":
                exp_action, exp_tool = "CALL_TOOL", None
                if actual.action == "CALL_TOOL":
                    exp_tool = actual.tool_name  # accept any authorized gather tool
                    match = actual.tool_name in {
                        "get_product_information",
                        "get_service_information",
                    }
                else:
                    match = False
            elif exp.get("skip_prefix", "").startswith("auto_handled"):
                exp_action, exp_tool = "FINAL", None
                match = actual.action == "FINAL"
            else:
                exp_action, exp_tool = "FINAL", None
                match = actual.action == "FINAL"

            results.append(
                AgentDecisionEvalResult(
                    f"{eid}-route",
                    f"{email['subject'][:40]}",
                    exp_tool,
                    exp_action,
                    actual,
                    match,
                )
            )

        return results

    def evaluate_runtime(self, emails: list[dict]) -> list[RuntimeEvalResult]:
        """Full AgentRuntime end-to-end — one isolated run per eval email."""
        results: list[RuntimeEvalResult] = []

        for email in emails:
            exp = expected_routing(email)
            provider = DatasetEmailProvider([email])
            fd, db_path = tempfile.mkstemp(suffix=".db")
            os.close(fd)

            try:
                eval_settings = Settings(
                    database_url=f"sqlite:///{db_path}",
                    email_provider="mock",
                    llm_provider=self._provider_name,
                    mistral_api_key=self._settings.mistral_api_key,
                    mistral_model=self._settings.mistral_model,
                    mistral_max_retries=self._settings.mistral_max_retries,
                    max_agent_steps=5,
                    max_agent_turns_per_email=20,
                    max_tool_calls=15,
                    gmail_mark_read_after_processing=True,
                )
                db = Database(eval_settings.database_url)
                agent = create_agent(
                    eval_settings,
                    db,
                    email_provider=provider,
                    llm=self._llm,
                )
                try:
                    run_result = agent.run()
                    agent._processed_repo._session.commit()
                except Exception as exc:
                    agent._processed_repo._session.rollback()
                    results.append(
                        RuntimeEvalResult(
                            email_id=email["id"],
                            expected=exp,
                            actual_status="failed",
                            actual_reply_sent=False,
                            actual_skip_reason=None,
                            tool_calls=[],
                            agent_turns=0,
                            match=False,
                            error_message=str(exc),
                        )
                    )
                    continue
                finally:
                    agent._processed_repo._session.close()

                step = next(
                    (s for s in run_result.steps if s.email_id == email["id"]),
                    None,
                )
                if step is None:
                    results.append(
                        RuntimeEvalResult(
                            email_id=email["id"],
                            expected=exp,
                            actual_status="missing",
                            actual_reply_sent=False,
                            actual_skip_reason=None,
                            tool_calls=[],
                            agent_turns=0,
                            match=False,
                            error_message="no step for email",
                        )
                    )
                    continue

                match = routing_matches(
                    step.status,
                    step.reply_sent,
                    step.skip_reason,
                    exp,
                )
                results.append(
                    RuntimeEvalResult(
                        email_id=email["id"],
                        expected=exp,
                        actual_status=step.status,
                        actual_reply_sent=step.reply_sent,
                        actual_skip_reason=step.skip_reason,
                        tool_calls=list(step.tool_calls),
                        agent_turns=step.agent_turns,
                        match=match,
                        error_message=step.error_message,
                    )
                )
            finally:
                try:
                    os.remove(db_path)
                except OSError:
                    pass

        return results

    def run(self) -> EvalReport:
        emails = self.load_dataset()
        report = EvalReport(total=len(emails), provider=self._provider_name)
        report.classification_results = self.evaluate_classification(emails)
        report.reply_results = self.evaluate_replies(emails)
        report.agent_decision_results = self.evaluate_agent_decisions(emails)
        report.runtime_results = self.evaluate_runtime(emails)
        return report

    def print_report(self, report: EvalReport) -> None:
        print("\n" + "=" * 60)
        print("EVALUATION REPORT")
        print("=" * 60)
        print(f"LLM provider:              {report.provider}")
        print(f"Total emails evaluated:    {report.total}")
        print(f"Requires action accuracy:  {report.requires_action_accuracy:.1%}")
        print(f"Inquiry detection accuracy:{report.inquiry_detection_accuracy:.1%}")
        print(f"Category accuracy:         {report.category_accuracy:.1%}")
        print(f"Agent decision accuracy:   {report.agent_decision_accuracy:.1%}")
        print(f"Runtime routing accuracy:  {report.runtime_routing_accuracy:.1%}")
        print(f"Reply groundedness rate:   {report.reply_groundedness_rate:.1%}")
        print("-" * 60)

        print("\nClassification mismatches:")
        any_cls = False
        for r in report.classification_results:
            if not (r.requires_action_match and r.inquiry_match and r.category_match):
                any_cls = True
                print(
                    f"  {r.email_id}: expected={r.expected['category']} "
                    f"actual={r.actual.category} "
                    f"(action:{r.requires_action_match} inquiry:{r.inquiry_match} "
                    f"category:{r.category_match})"
                )
        if not any_cls:
            print("  (none)")

        print("\nRuntime routing mismatches:")
        any_rt = False
        for r in report.runtime_results:
            if not r.match:
                any_rt = True
                print(
                    f"  {r.email_id}: expected={r.expected} "
                    f"actual status={r.actual_status} reply_sent={r.actual_reply_sent} "
                    f"skip={r.actual_skip_reason} tools={r.tool_calls}"
                )
                if r.error_message:
                    print(f"    error: {r.error_message}")
        if not any_rt:
            print("  (none)")

        print("\nAgent decision mismatches:")
        any_dec = False
        for r in report.agent_decision_results:
            if not r.match:
                any_dec = True
                print(
                    f"  {r.case_id}: expected action={r.expected_action} tool={r.expected_tool} "
                    f"actual action={r.actual.action} tool={r.actual.tool_name}"
                )
        if not any_dec:
            print("  (none)")

        print("\nReply issues:")
        any_reply = False
        for r in report.reply_results:
            if r.issues:
                any_reply = True
                print(f"  {r.email_id}: {r.issues}")
        if not any_reply:
            print("  (none)")

        print("=" * 60)
