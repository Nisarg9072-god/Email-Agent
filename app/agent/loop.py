"""Explicit agent loop - the heart of the email handling agent.

Each step is visible and documented. Deterministic decisions use code;
probabilistic decisions delegate to the LLM.

Agent Loop:
1. Start run
2. Check mailbox count
3. List emails
4. For each email:
   a. Check if already processed (DETERMINISTIC)
   b. Claim for processing (DETERMINISTIC, DB constraint)
   c. Retrieve email
   d. Classify with LLM (PROBABILISTIC)
   e. Apply guardrails (DETERMINISTIC)
   f. Retrieve authorized info via tools (DETERMINISTIC auth)
   g. Generate reply with LLM (PROBABILISTIC)
   h. Validate reply (DETERMINISTIC)
   i. Send email (DETERMINISTIC)
   j. Log and update state (DETERMINISTIC)
"""

import json
import logging
from dataclasses import dataclass, field

from app.agent.schemas import AgentStepResult, EmailClassification
from app.db.repositories import AgentRunRepository, ProcessedEmailRepository, ReplyRepository
from app.email.base import EmailProvider
from app.harness.guardrails import AgentGuardrails
from app.harness.state import ProcessingStateManager
from app.harness.validator import ResponseValidator
from app.llm.base import LLMProvider
from app.tools.company_data_tools import CompanyDataTools

logger = logging.getLogger(__name__)


@dataclass
class AgentRunResult:
    run_id: int
    emails_found: int = 0
    emails_processed: int = 0
    emails_skipped: int = 0
    emails_failed: int = 0
    steps: list[AgentStepResult] = field(default_factory=list)


class AgentLoop:
    """Orchestrates the email processing workflow."""

    def __init__(
        self,
        email_provider: EmailProvider,
        llm: LLMProvider,
        company_tools: CompanyDataTools,
        state_manager: ProcessingStateManager,
        guardrails: AgentGuardrails,
        validator: ResponseValidator,
        processed_repo: ProcessedEmailRepository,
        reply_repo: ReplyRepository,
        agent_run_repo: AgentRunRepository,
    ):
        self._email = email_provider
        self._llm = llm
        self._tools = company_tools
        self._state = state_manager
        self._guardrails = guardrails
        self._validator = validator
        self._processed_repo = processed_repo
        self._reply_repo = reply_repo
        self._agent_run_repo = agent_run_repo

    def run(self) -> AgentRunResult:
        self._guardrails.reset()
        run = self._agent_run_repo.start_run()
        result = AgentRunResult(run_id=run.id)

        try:
            # Step 1: Check mailbox
            count = self._email.get_email_count()
            result.emails_found = count
            logger.info("Agent run %d started: %d emails found", run.id, count)

            # Step 2: List emails
            summaries = self._email.list_emails()
            email_ids = [s.email_id for s in summaries]
            logger.info("Email IDs discovered: %s", email_ids)

            # Step 3: Process each email
            for summary in summaries:
                if not self._guardrails.increment_step():
                    logger.error("Aborting run: max steps exceeded")
                    break

                step_result = self._process_email(summary.email_id)
                result.steps.append(step_result)

                if step_result.status == "processed":
                    result.emails_processed += 1
                elif step_result.status == "skipped":
                    result.emails_skipped += 1
                elif step_result.status == "failed":
                    result.emails_failed += 1

            self._agent_run_repo.complete_run(
                run.id,
                emails_found=result.emails_found,
                emails_processed=result.emails_processed,
                emails_skipped=result.emails_skipped,
                emails_failed=result.emails_failed,
            )
            logger.info(
                "Agent run %d completed: processed=%d skipped=%d failed=%d",
                run.id,
                result.emails_processed,
                result.emails_skipped,
                result.emails_failed,
            )

        except Exception as e:
            logger.exception("Agent run %d failed", run.id)
            self._agent_run_repo.complete_run(
                run.id,
                emails_found=result.emails_found,
                emails_processed=result.emails_processed,
                emails_skipped=result.emails_skipped,
                emails_failed=result.emails_failed,
                status="failed",
                error_message=str(e),
            )

        return result

    def _process_email(self, email_id: str) -> AgentStepResult:
        self._tools.reset_log()
        step = AgentStepResult(email_id=email_id, status="pending")

        # a. Check if already processed (DETERMINISTIC)
        should_skip, skip_reason = self._state.should_skip(email_id)
        if should_skip:
            step.status = "skipped"
            step.skip_reason = skip_reason
            logger.info("Email %s skipped: %s", email_id, skip_reason)
            return step

        # b. Claim for processing (DETERMINISTIC + DB UNIQUE constraint)
        claimed, claim_reason = self._state.claim(email_id)
        if not claimed:
            step.status = "skipped"
            step.skip_reason = claim_reason
            logger.info("Email %s not claimed: %s", email_id, claim_reason)
            return step

        # c. Retrieve specific email
        email = self._email.get_email(email_id)
        if email is None:
            step.status = "failed"
            step.error_message = "email_not_found"
            self._state.mark_failed(email_id, "email_not_found")
            return step

        if not email.sender or not email.body:
            step.status = "failed"
            step.error_message = "invalid_email_missing_fields"
            self._state.mark_failed(email_id, "invalid_email_missing_fields")
            return step

        # d. Classify with LLM (PROBABILISTIC)
        try:
            classification = self._llm.classify_email(
                email.sender, email.subject, email.body
            )
            step.classification = classification
            logger.info(
                "Email %s classified: category=%s requires_action=%s inquiry=%s",
                email_id,
                classification.category,
                classification.requires_action,
                classification.is_product_or_service_inquiry,
            )
        except Exception as e:
            step.status = "failed"
            step.error_message = f"classification_failed:{e}"
            self._state.mark_failed(email_id, step.error_message)
            return step

        # e. Apply guardrails (DETERMINISTIC)
        should_respond, guard_reason = self._guardrails.should_respond_to_classification(
            classification
        )
        if not should_respond:
            step.status = "skipped"
            step.skip_reason = guard_reason
            self._state.mark_skipped(email_id, guard_reason or "guardrail_skip")
            logger.info("Email %s skipped by guardrails: %s", email_id, guard_reason)
            return step

        # f. Retrieve authorized company info via controlled tools (DETERMINISTIC auth)
        if not self._guardrails.record_tool_call():
            step.status = "failed"
            step.error_message = "max_tool_calls_exceeded"
            self._state.mark_failed(email_id, step.error_message)
            return step

        company_info = self._tools.gather_information_for_classification(
            classification.product_names,
            classification.service_names,
        )
        step.tool_calls = [c["tool"] for c in self._tools.call_log]
        logger.info("Email %s tool calls: %s", email_id, step.tool_calls)

        # g. Generate reply with LLM (PROBABILISTIC)
        try:
            reply = self._llm.generate_reply(
                email.sender,
                email.subject,
                email.body,
                company_info,
            )
            logger.info("Email %s reply generated: subject=%s", email_id, reply.subject)
        except Exception as e:
            step.status = "failed"
            step.error_message = f"reply_generation_failed:{e}"
            self._state.mark_failed(email_id, step.error_message)
            return step

        # h. Validate reply (DETERMINISTIC)
        is_valid, validation_error = self._validator.validate(
            email.sender, reply.subject, reply.body
        )
        if not is_valid:
            step.status = "failed"
            step.error_message = f"validation_failed:{validation_error}"
            self._state.mark_failed(email_id, step.error_message)
            self._reply_repo.create(
                email_id=email_id,
                recipient=email.sender,
                subject=reply.subject,
                body=reply.body,
                status="validation_failed",
            )
            logger.warning("Email %s reply validation failed: %s", email_id, validation_error)
            return step

        # i. Send email (DETERMINISTIC)
        reply_record = self._reply_repo.create(
            email_id=email_id,
            recipient=email.sender,
            subject=reply.subject,
            body=reply.body,
            status="pending",
        )

        sent = self._email.send_email(
            to=email.sender,
            subject=reply.subject,
            body=reply.body,
            thread_id=email.thread_id,
        )

        if not sent:
            step.status = "failed"
            step.error_message = "send_failed"
            self._state.mark_failed(email_id, "send_failed")
            self._reply_repo.mark_failed(reply_record.id, "send_failed")
            logger.error("Email %s send failed", email_id)
            return step

        # j. Log and mark processed (DETERMINISTIC)
        self._reply_repo.mark_sent(reply_record.id)
        classification_json = classification.model_dump_json()
        self._state.mark_processed(email_id, classification=classification_json)

        step.status = "processed"
        step.reply_sent = True
        logger.info("Email %s processed and reply sent", email_id)
        return step
