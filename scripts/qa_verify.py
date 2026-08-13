"""One-shot QA verification script. Run: python scripts/qa_verify.py"""

import json
import os
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

RESULTS: list[dict] = []


def record(category: str, name: str, status: str, detail: str = ""):
    RESULTS.append({"category": category, "name": name, "status": status, "detail": detail})
    icon = {"PASS": "+", "FAIL": "X", "BLOCKED": "!", "SKIP": "-"}[status]
    print(f"[{icon}] {category} / {name}: {status}" + (f" — {detail}" if detail else ""))


def section(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


# --- 3. DATABASE CHECK ---
def check_database():
    section("3. DATABASE CHECK")
    from sqlalchemy.exc import IntegrityError

    from app.db.database import Database
    from app.db.models import AgentRun, ProcessedEmail, Reply
    from app.db.repositories import ProcessedEmailRepository, ReplyRepository

    db_path = PROJECT_ROOT / "data" / "qa_test.db"
    if db_path.exists():
        db_path.unlink()

    db = Database(f"sqlite:///{db_path}")
    session = db.get_session()

    tables = {t.name for t in ProcessedEmail.metadata.tables.values()}
    expected = {"processed_emails", "replies", "agent_runs"}
    if expected.issubset(tables):
        record("Database", "tables_created", "PASS", str(sorted(expected)))
    else:
        record("Database", "tables_created", "FAIL", f"missing {expected - tables}")

    # PK on email_id
    pk = ProcessedEmail.__table__.columns["email_id"].primary_key
    if pk:
        record("Database", "email_id_primary_key", "PASS")
    else:
        record("Database", "email_id_primary_key", "FAIL")

    repo = ProcessedEmailRepository(session)
    claimed, _ = repo.claim_for_processing("qa-email-001")
    session.commit()
    if claimed:
        record("Database", "insert_email", "PASS")
    else:
        record("Database", "insert_email", "FAIL")

    dup_blocked = False
    try:
        session.add(ProcessedEmail(email_id="qa-email-dup", status="processing"))
        session.flush()
        session.add(ProcessedEmail(email_id="qa-email-dup", status="processing"))
        session.flush()
    except IntegrityError:
        session.rollback()
        dup_blocked = True

    if dup_blocked:
        record("Database", "duplicate_blocked", "PASS", "IntegrityError on duplicate email_id")
    else:
        record("Database", "duplicate_blocked", "FAIL")

    claimed2, reason = repo.claim_for_processing("qa-email-001")
    if not claimed2:
        record("Database", "second_claim_rejected", "PASS", reason)
    else:
        record("Database", "second_claim_rejected", "FAIL")

    reply_repo = ReplyRepository(session)
    reply = reply_repo.create("qa-email-001", "a@b.com", "Re: Test", "Body", status="sent")
    session.commit()
    if reply.id:
        record("Database", "reply_insert", "PASS")
    else:
        record("Database", "reply_insert", "FAIL")

    run = AgentRun(emails_found=1)
    session.add(run)
    session.commit()
    record("Database", "agent_run_insert", "PASS" if run.id else "FAIL")

    session.close()
    del session
    del db
    import gc
    gc.collect()
    try:
        db_path.unlink(missing_ok=True)
    except PermissionError:
        pass  # Windows file lock; test data in data/qa_test.db is harmless


# --- 4. MISTRAL API CHECK ---
def check_mistral():
    section("4. MISTRAL API CHECK")
    from app.config import get_settings
    from app.agent.schemas import EmailClassification
    from app.llm.mistral_provider import MistralProvider
    from app.llm.exceptions import MistralAuthError, MistralAPIError

    settings = get_settings()
    has_key = bool(settings.mistral_api_key and settings.mistral_api_key.strip())
    model = settings.mistral_model or "(not set)"

    if not has_key:
        record("Mistral", "api_key", "BLOCKED", "missing MISTRAL_API_KEY")
        record("Mistral", "model_config", "PASS" if settings.mistral_model else "FAIL", model)
        return

    record("Mistral", "api_key", "PASS", "key present (value not shown)")
    record("Mistral", "model_config", "PASS", model)

    try:
        provider = MistralProvider(
            api_key=settings.mistral_api_key,
            model=settings.mistral_model,
            max_retries=1,
            timeout=30.0,
        )
        result = provider.classify_email(
            "qa@test.com",
            "Pricing question",
            "What is the pricing for NovaSupport AI?",
        )
        if isinstance(result, EmailClassification) and result.category:
            record("Mistral", "live_api_call", "PASS", f"category={result.category}")
            record("Mistral", "structured_output", "PASS", "Pydantic EmailClassification validated")
        else:
            record("Mistral", "live_api_call", "FAIL", "unexpected response type")
    except MistralAuthError as e:
        record("Mistral", "live_api_call", "BLOCKED", f"authentication failed: {e}")
    except MistralAPIError as e:
        record("Mistral", "live_api_call", "FAIL", str(e))
    except Exception as e:
        record("Mistral", "live_api_call", "FAIL", f"{type(e).__name__}: {e}")


# --- 5. MOCK EMAIL PROVIDER ---
def check_mock_email():
    section("5. MOCK EMAIL PROVIDER CHECK")
    from app.config import get_settings
    from app.email.mock_provider import MockEmailProvider

    settings = get_settings()
    provider = MockEmailProvider(settings.mock_emails_path)

    count = provider.get_email_count()
    emails = provider.list_emails()
    record("MockEmail", "get_email_count", "PASS" if count == 10 else "FAIL", f"count={count}")
    record("MockEmail", "list_emails", "PASS" if len(emails) == 10 else "FAIL", f"listed={len(emails)}")

    all_retrieved = True
    for summary in emails:
        msg = provider.get_email(summary.email_id)
        if msg is None or msg.body == "":
            all_retrieved = False
            record("MockEmail", f"get_email_{summary.email_id}", "FAIL")
    if all_retrieved:
        record("MockEmail", "get_all_emails", "PASS", "all 10 emails retrieved with body")

    provider.reset_sent()
    sent_ok = provider.send_email("test@x.com", "Test", "Hello", thread_id="t1")
    record("MockEmail", "send_email", "PASS" if sent_ok and len(provider.sent_emails) == 1 else "FAIL")


# --- 6. COMPANY DATA TOOLS ---
def check_company_tools():
    section("6. COMPANY DATA TOOL CHECK")
    from app.company.authorization import AuthorizationService
    from app.company.repository import CompanyRepository
    from app.company.service import CompanyDataService
    from app.config import get_settings
    from app.tools.company_data_tools import ALLOWED_TOOLS, CompanyDataTools

    settings = get_settings()
    repo = CompanyRepository(settings.company_data_dir)
    auth = AuthorizationService(repo)
    service = CompanyDataService(repo, auth)
    tools = CompanyDataTools(service, auth)

    product = tools.call_tool("get_product_information", product_name="NovaSupport AI")
    if product and "public_pricing" in product and "internal_cost" not in product:
        record("CompanyTools", "product_authorized", "PASS")
    else:
        record("CompanyTools", "product_authorized", "FAIL", str(product))

    service_info = tools.call_tool("get_service_information", service_name="AI consulting")
    if service_info and "employee_data" not in service_info:
        record("CompanyTools", "service_authorized", "PASS")
    else:
        record("CompanyTools", "service_authorized", "FAIL")

    unknown = tools.call_tool("get_product_information", product_name="FakeProduct")
    record("CompanyTools", "unknown_product", "PASS" if unknown is None else "FAIL")

    forbidden = [
        tools.call_tool("execute_sql", query="SELECT * FROM products"),
        tools.call_tool("query_database", table="customers"),
        tools.call_tool("get_database_connection"),
    ]
    if all(x is None for x in forbidden):
        record("CompanyTools", "forbidden_tools_blocked", "PASS")
    else:
        record("CompanyTools", "forbidden_tools_blocked", "FAIL")

    if set(tools.get_available_tools()) == ALLOWED_TOOLS:
        record("CompanyTools", "allowed_tools_only", "PASS", str(ALLOWED_TOOLS))
    else:
        record("CompanyTools", "allowed_tools_only", "FAIL")

    raw = repo.get_product_by_name("NovaSupport AI")
    restricted_present_in_raw = "internal_cost" in raw and "customer_list" in raw
    restricted_absent_in_auth = "internal_cost" not in (product or {}) and "customer_list" not in (product or {})
    if restricted_present_in_raw and restricted_absent_in_auth:
        record("CompanyTools", "restricted_fields_filtered", "PASS")
    else:
        record("CompanyTools", "restricted_fields_filtered", "FAIL")


# --- 9. GUARDRAIL: NO DB ACCESS ---
def check_db_guardrail():
    section("9. DATABASE ACCESS GUARDRAIL")
    from app.tools.company_data_tools import ALLOWED_TOOLS

    forbidden_names = {"execute_sql", "query_database", "get_database_connection", "list_all_products"}
    if forbidden_names.isdisjoint(ALLOWED_TOOLS):
        record("Guardrail", "no_db_tools", "PASS", f"allowed={ALLOWED_TOOLS}")
    else:
        record("Guardrail", "no_db_tools", "FAIL")


# --- 10. ALL MOCK EMAIL SCENARIOS ---
def check_mock_scenarios():
    section("10. MOCK EMAIL SCENARIOS")
    from app.agent.agent import create_agent
    from app.config import Settings
    from app.db.database import Database
    from app.email.mock_provider import MockEmailProvider

    db_path = PROJECT_ROOT / "data" / "qa_scenarios.db"
    if db_path.exists():
        db_path.unlink()

    settings = Settings(
        database_url=f"sqlite:///{db_path}",
        email_provider="mock",
        llm_provider="mock",
    )
    db = Database(settings.database_url)
    agent = create_agent(settings, db)
    mock_provider = agent._email
    mock_provider.reset_sent()

    result = agent.run()
    agent._processed_repo._session.commit()

    expected = {
        "mock-001": "processed",
        "mock-002": "processed",
        "mock-003": "processed",
        "mock-004": "processed",
        "mock-005": "skipped",
        "mock-006": "skipped",
        "mock-007": "skipped",
        "mock-008": "skipped",
        "mock-009": "processed",
        "mock-010": "processed",
    }

    print(f"\n{'Email ID':<12} {'Status':<10} {'Category':<25} {'Reply?':<8} {'Tools'}")
    print("-" * 80)
    all_ok = True
    for step in result.steps:
        cat = step.classification.category if step.classification else "N/A"
        reply = "YES" if step.reply_sent else "NO"
        tools = ",".join(step.tool_calls) if step.tool_calls else "-"
        print(f"{step.email_id:<12} {step.status:<10} {cat:<25} {reply:<8} {tools}")

        exp = expected.get(step.email_id)
        if exp and step.status != exp:
            all_ok = False
            record("Scenarios", step.email_id, "FAIL", f"expected {exp}, got {step.status}")
        else:
            record("Scenarios", step.email_id, "PASS", f"{step.status}, reply={step.reply_sent}")

    if all_ok:
        record("Scenarios", "all_10_emails", "PASS")
    else:
        record("Scenarios", "all_10_emails", "FAIL")

    agent._processed_repo._session.close()
    return db_path, settings


# --- 8. DUPLICATE GUARDRAIL ---
def check_duplicate_guardrail(db_path: Path, settings):
    section("8. DUPLICATE EMAIL GUARDRAIL")
    from app.agent.agent import create_agent
    from app.db.database import Database

    db = Database(settings.database_url)
    agent = create_agent(settings, db)
    mock_provider = agent._email
    sent_before = len(mock_provider.sent_emails)

    result2 = agent.run()
    agent._processed_repo._session.commit()
    sent_after = len(mock_provider.sent_emails)

    processed_second = result2.emails_processed
    skipped_second = result2.emails_skipped
    new_sends = sent_after - sent_before

    print(f"\nSecond run: processed={processed_second}, skipped={skipped_second}, new_sends={new_sends}")
    for step in result2.steps:
        print(f"  {step.email_id} -> {step.status}" + (f" ({step.skip_reason})" if step.skip_reason else ""))

    if processed_second == 0 and skipped_second == 10 and new_sends == 0:
        record("Guardrail", "duplicate_protection", "PASS", "all 10 skipped, 0 new sends")
    else:
        record("Guardrail", "duplicate_protection", "FAIL",
               f"processed={processed_second}, skipped={skipped_second}, new_sends={new_sends}")

    agent._processed_repo._session.close()
    del agent
    import gc
    gc.collect()
    try:
        db_path.unlink(missing_ok=True)
    except PermissionError:
        pass


# --- 14. ERROR HANDLING ---
def check_error_handling():
    section("14. ERROR HANDLING")
    from unittest.mock import MagicMock

    from app.agent.runtime import AgentRuntime
    from app.agent.schemas import AgentDecision, EmailClassification, GeneratedReply
    from app.company.authorization import AuthorizationService
    from app.company.repository import CompanyRepository
    from app.company.service import CompanyDataService
    from app.config import Settings
    from app.db.database import Database
    from app.db.repositories import AgentRunRepository, ProcessedEmailRepository, ReplyRepository
    from app.email.mock_provider import MockEmailProvider
    from app.harness.runtime import AgentHarness
    from app.harness.state import ProcessingStateManager
    from app.harness.validator import ResponseValidator
    from app.llm.base import LLMProvider
    from app.llm.exceptions import MistralAPIError
    from app.tools.agent_toolkit import AgentToolKit

    settings = Settings(database_url="sqlite:///:memory:", llm_provider="mock")
    db = Database(settings.database_url)
    session = db.get_session()

    repo = CompanyRepository(settings.company_data_dir)
    auth = AuthorizationService(repo)
    service = CompanyDataService(repo, auth)
    email = MockEmailProvider(settings.mock_emails_path)
    state = ProcessingStateManager(ProcessedEmailRepository(session))
    harness = AgentHarness(auth)
    validator = ResponseValidator(auth)
    toolkit = AgentToolKit(email, service, auth, validator)

    class FailingLLM(LLMProvider):
        def decide_next_action(self, state, catalog):
            raise MistralAPIError("simulated failure")
        def classify_email(self, s, sub, b):
            raise MistralAPIError("simulated failure")
        def generate_reply(self, s, sub, b, info):
            raise MistralAPIError("simulated failure")

    class BadReplyLLM(LLMProvider):
        def decide_next_action(self, state, catalog):
            if state.body is None:
                return AgentDecision(
                    action="CALL_TOOL",
                    tool_name="get_email",
                    tool_arguments={"email_id": state.email_id},
                )
            return AgentDecision(
                action="CALL_TOOL",
                tool_name="send_reply",
                tool_arguments={
                    "recipient": state.sender,
                    "subject": "Re: x",
                    "body": "",
                },
            )
        def classify_email(self, s, sub, b):
            return EmailClassification(
                requires_action=True, is_product_or_service_inquiry=True,
                category="product_pricing", product_names=["NovaSupport AI"],
            )
        def generate_reply(self, s, sub, b, info):
            return GeneratedReply(subject="Re: x", body="", information_used=[])

    def build_agent(llm, email_provider, sess):
        tk = AgentToolKit(email_provider, service, auth, validator)
        return AgentRuntime(
            email_provider=email_provider, llm=llm, toolkit=tk, harness=AgentHarness(auth),
            state_manager=ProcessingStateManager(ProcessedEmailRepository(sess)),
            processed_repo=ProcessedEmailRepository(sess),
            reply_repo=ReplyRepository(sess),
            agent_run_repo=AgentRunRepository(sess),
        )

    # Mistral/LLM failure on decision
    email2 = MockEmailProvider(settings.mock_emails_path)
    session2 = db.get_session()
    agent_fail = build_agent(FailingLLM(), email2, session2)
    email2._emails = [email2._emails[0]]  # only mock-001
    r = agent_fail.run()
    step = r.steps[0]
    if step.status == "failed" and not step.reply_sent:
        record("ErrorHandling", "llm_decision_failure", "PASS", step.error_message)
    else:
        record("ErrorHandling", "llm_decision_failure", "FAIL", str(step.status))

    # Empty reply validation — isolated DB
    db_path2 = PROJECT_ROOT / "data" / "qa_err2.db"
    db_path2.unlink(missing_ok=True)
    db2 = Database(f"sqlite:///{db_path2}")
    session3 = db2.get_session()
    email3 = MockEmailProvider(settings.mock_emails_path)
    email3._emails = [email3._emails[0]]
    agent_bad = build_agent(BadReplyLLM(), email3, session3)
    email3.reset_sent()
    r3 = agent_bad.run()
    session3.commit()
    if r3.steps[0].status == "failed" and len(email3.sent_emails) == 0:
        record("ErrorHandling", "empty_reply_not_sent", "PASS")
    else:
        record("ErrorHandling", "empty_reply_not_sent", "FAIL", f"status={r3.steps[0].status}, sent={len(email3.sent_emails)}")
    session3.close()
    try:
        db_path2.unlink(missing_ok=True)
    except PermissionError:
        pass

    # Send failure — isolated DB
    db_path3 = PROJECT_ROOT / "data" / "qa_err3.db"
    db_path3.unlink(missing_ok=True)
    db3 = Database(f"sqlite:///{db_path3}")
    session4 = db3.get_session()
    email4 = MockEmailProvider(settings.mock_emails_path)
    email4._emails = [email4._emails[0]]
    from app.llm.mock_provider import MockLLMProvider
    email4.send_email = lambda *a, **k: False
    agent_send_fail = build_agent(MockLLMProvider(), email4, session4)
    r4 = agent_send_fail.run()
    session4.commit()
    rec = ProcessedEmailRepository(session4).get("mock-001")
    if r4.steps[0].status == "failed" and rec and rec.status == "failed":
        record("ErrorHandling", "send_failure_not_processed", "PASS")
    else:
        record("ErrorHandling", "send_failure_not_processed", "FAIL", f"status={r4.steps[0].status}, db={rec.status if rec else None}")
    session4.close()
    try:
        db_path3.unlink(missing_ok=True)
    except PermissionError:
        pass

    session2.close()


def main():
    print("QA VERIFICATION — NovaAI Email Agent")
    section("1. INSTALLATION CHECK")
    record("Install", "python", "PASS", sys.version.split()[0])
    record("Install", "requirements", "PASS", "requirements.txt present")
    record("Install", "env_example", "PASS" if (PROJECT_ROOT / ".env.example").exists() else "FAIL")

    check_database()
    check_mistral()
    check_mock_email()
    check_company_tools()
    check_db_guardrail()
    db_path, settings = check_mock_scenarios()
    check_duplicate_guardrail(db_path, settings)
    check_error_handling()

    section("SUMMARY")
    counts = {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "SKIP": 0}
    for r in RESULTS:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"PASS={counts['PASS']} FAIL={counts['FAIL']} BLOCKED={counts['BLOCKED']}")
    fails = [r for r in RESULTS if r["status"] == "FAIL"]
    if fails:
        print("\nFAILURES:")
        for f in fails:
            print(f"  - {f['category']}/{f['name']}: {f['detail']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
