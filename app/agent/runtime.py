"""Agent runtime — genuine LLM-driven agentic loop per email."""

import json
import logging
from dataclasses import dataclass, field

from app.agent.decision_normalize import normalize_decision
from app.agent.schemas import AgentDecision, AgentStepResult
from app.agent.state import AgentState
from app.db.repositories import AgentRunRepository, ProcessedEmailRepository, ReplyRepository, failure_attempt_count, is_retryable_failure
from app.email.base import EmailProvider
from app.harness.runtime import AgentHarness, HarnessValidationError
from app.harness.state import ProcessingStateManager
from app.llm.base import LLMProvider
from app.tools.agent_toolkit import AgentToolKit

logger = logging.getLogger(__name__)


@dataclass
class AgentRunResult:
    run_id: int
    emails_found: int = 0
    emails_processed: int = 0
    emails_skipped: int = 0
    emails_failed: int = 0
    steps: list[AgentStepResult] = field(default_factory=list)


class AgentRuntime:
    """
    Genuine agentic runtime: LLM decides next action each turn until FINAL or harness stop.

    Deterministic harness handles: duplicate guard, tool authorization, limits, validation.
    Probabilistic LLM handles: which tool to call, when enough info exists, reply content.
    """

    def __init__(
        self,
        email_provider: EmailProvider,
        llm: LLMProvider,
        toolkit: AgentToolKit,
        harness: AgentHarness,
        state_manager: ProcessingStateManager,
        processed_repo: ProcessedEmailRepository,
        reply_repo: ReplyRepository,
        agent_run_repo: AgentRunRepository,
    ):
        self._email = email_provider
        self._llm = llm
        self._toolkit = toolkit
        self._harness = harness
        self._state = state_manager
        self._processed_repo = processed_repo
        self._reply_repo = reply_repo
        self._agent_run_repo = agent_run_repo

    def _finalize_email(self, email_id: str, step: AgentStepResult) -> None:
        """Mark Gmail read after successful terminal outcome."""
        if step.skip_reason == "already_processing":
            return
        if step.status in {"processed", "skipped"}:
            self._email.mark_as_read(email_id)
        elif step.status == "failed":
            record = self._processed_repo.get(email_id)
            if record and not is_retryable_failure(record.error_message):
                self._email.mark_as_read(email_id)
                logger.info(
                    "Email %s failed with no retries left — marked read to stop reprocessing",
                    email_id,
                )

    def run(self) -> AgentRunResult:
        self._harness.reset_run()
        run = self._agent_run_repo.start_run()
        result = AgentRunResult(run_id=run.id)

        try:
            count = self._email.get_email_count()
            all_summaries = self._email.list_emails()
            summaries = []
            cleanup_ids: list[str] = []
            retry_ids: list[str] = []
            for summary in all_summaries:
                record = self._processed_repo.get(summary.email_id)
                if record is None:
                    summaries.append(summary)
                    continue
                if record.status == "failed":
                    if is_retryable_failure(record.error_message):
                        if self._processed_repo.reclaim_failed_for_retry(summary.email_id):
                            retry_ids.append(summary.email_id)
                            summaries.append(summary)
                            logger.info(
                                "Re-queuing failed email %s (attempt %d)",
                                summary.email_id,
                                failure_attempt_count(record.error_message) + 1,
                            )
                        continue
                    logger.warning(
                        "Email %s already failed (%s) — max attempts reached; marking read, not reprocessing",
                        summary.email_id,
                        record.error_message,
                    )
                    cleanup_ids.append(summary.email_id)
                    continue
                if record.status == "skipped":
                    if not self._reply_repo.has_reply_for_email(summary.email_id):
                        if self._processed_repo.clear_skipped_for_retry(summary.email_id):
                            retry_ids.append(summary.email_id)
                            summaries.append(summary)
                        continue
                    cleanup_ids.append(summary.email_id)
                    logger.debug(
                        "Skip %s: already skipped with reply on file",
                        summary.email_id,
                    )
                    continue
                if record.status == "processed":
                    cleanup_ids.append(summary.email_id)
                    logger.debug(
                        "Skip %s: already processed in database",
                        summary.email_id,
                    )
                    continue
                # Stuck in processing — do not re-run LLM; clear unread noise only
                cleanup_ids.append(summary.email_id)
                logger.warning(
                    "Email %s stuck in processing — marking read without reprocessing",
                    summary.email_id,
                )

            if retry_ids:
                logger.info(
                    "Retrying %d unread message(s) from prior incomplete run(s): %s",
                    len(retry_ids),
                    retry_ids,
                )

            if cleanup_ids:
                marked = self._email.mark_many_as_read(cleanup_ids)
                logger.info(
                    "%d already-handled unread message(s) marked read (no reprocessing): %s",
                    marked,
                    cleanup_ids[:5],
                )
                result.emails_skipped += len(cleanup_ids)

            # Process at most gmail max (via harness email slot limit already); cap new queue
            max_new = getattr(self._email, "_max_messages", len(summaries))
            if len(summaries) > max_new:
                logger.info(
                    "Found %d never-seen unread email(s); processing first %d this run",
                    len(summaries),
                    max_new,
                )
                summaries = summaries[:max_new]

            result.emails_found = len(summaries)
            logger.info(
                "Agent run %d: %d email(s) to process (scanned=%d, cleanup=%d, retry=%d)",
                run.id,
                len(summaries),
                count,
                len(cleanup_ids),
                len(retry_ids),
            )
            if summaries:
                logger.info("Email ids to process: %s", [s.email_id for s in summaries])

            for summary in summaries:
                if not self._harness.increment_email_slot():
                    break
                step = self._run_agentic_loop(summary.email_id)
                self._finalize_email(summary.email_id, step)
                result.steps.append(step)
                if step.status == "processed":
                    result.emails_processed += 1
                elif step.status == "skipped":
                    result.emails_skipped += 1
                elif step.status == "failed":
                    result.emails_failed += 1

            self._agent_run_repo.complete_run(
                run.id,
                emails_found=result.emails_found,
                emails_processed=result.emails_processed,
                emails_skipped=result.emails_skipped,
                emails_failed=result.emails_failed,
            )
        except Exception as exc:
            logger.exception("Agent run %d failed", run.id)
            self._agent_run_repo.complete_run(
                run.id,
                emails_found=result.emails_found,
                emails_processed=result.emails_processed,
                emails_skipped=result.emails_skipped,
                emails_failed=result.emails_failed,
                status="failed",
                error_message=str(exc),
            )
        return result

    def _run_agentic_loop(self, email_id: str) -> AgentStepResult:
        step = AgentStepResult(email_id=email_id, status="pending")

        should_skip, skip_reason = self._state.should_skip(email_id)
        if should_skip:
            step.status = "skipped"
            step.skip_reason = skip_reason
            return step

        claimed, claim_reason = self._state.claim(email_id)
        if not claimed:
            step.status = "skipped"
            step.skip_reason = claim_reason
            return step

        agent_state = AgentState(email_id=email_id)
        tool_catalog = self._harness.tool_catalog_for_prompt()
        stop_reason: str | None = None

        while agent_state.status == "running":
            agent_state.turn += 1
            step.agent_turns = agent_state.turn

            try:
                decision = self._llm.decide_next_action(agent_state, tool_catalog)
                decision = normalize_decision(decision, email_id, agent_state, self._llm)
            except Exception as exc:
                step.status = "failed"
                step.error_message = f"decision_failed:{exc}"
                self._state.mark_failed(email_id, step.error_message)
                return step

            step.decision_trace.append(
                f"turn {agent_state.turn}: {decision.action} "
                f"{decision.tool_name or ''} — {decision.reasoning[:80]}"
            )
            logger.info(
                "Email %s turn %d decision: action=%s tool=%s",
                email_id,
                agent_state.turn,
                decision.action,
                decision.tool_name,
            )

            try:
                self._harness.validate_decision(decision, agent_state)
            except HarnessValidationError as exc:
                step.status = "failed"
                step.error_message = f"harness_violation:{exc}"
                self._state.mark_failed(email_id, step.error_message)
                return step

            if decision.action == "FINAL":
                status, skip_reason = self._harness.interpret_final(
                    decision.final_output, agent_state  # type: ignore[arg-type]
                )
                step.status = status
                step.skip_reason = skip_reason
                step.reply_sent = agent_state.reply_sent
                step.tool_calls = [t.tool_name for t in agent_state.tool_history]
                if status == "processed":
                    self._state.mark_processed(email_id, classification=None)
                elif status == "skipped":
                    self._state.mark_skipped(email_id, skip_reason or "agent_final_skip")
                else:
                    self._state.mark_failed(email_id, skip_reason or "final_failed")
                agent_state.status = "done"
                break

            record = self._toolkit.execute(
                decision.tool_name,  # type: ignore[arg-type]
                decision.tool_arguments,
                agent_state,
            )
            self._toolkit.apply_tool_result(agent_state, record)
            step.tool_calls = [t.tool_name for t in agent_state.tool_history]

            if not record.success:
                step.status = "failed"
                step.error_message = f"tool_failed:{record.tool_name}:{record.error}"
                self._state.mark_failed(email_id, step.error_message)
                if record.tool_name == "send_reply" and agent_state.body:
                    self._reply_repo.create(
                        email_id=email_id,
                        recipient=agent_state.sender or "",
                        subject=decision.tool_arguments.get("subject", ""),
                        body=decision.tool_arguments.get("body", ""),
                        status="validation_failed" if "validation" in (record.error or "") else "failed",
                    )
                return step

            if record.tool_name == "send_reply" and record.success:
                self._reply_repo.create(
                    email_id=email_id,
                    recipient=agent_state.sender or "",
                    subject=decision.tool_arguments.get("subject", ""),
                    body=decision.tool_arguments.get("body", ""),
                    status="sent",
                )

        if agent_state.status == "running":
            step.status = "failed"
            step.error_message = stop_reason or "max_turns_without_final"
            self._state.mark_failed(email_id, step.error_message)

        return step
