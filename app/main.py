"""CLI entry point for the NovaAI Email Agent."""

import logging
import sys
import time

from app.agent.agent import create_agent
from app.config import get_settings
from app.db.database import Database


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def print_run_results(result) -> None:
    print("\n" + "=" * 60)
    print("AGENT RUN RESULTS")
    print("=" * 60)
    print(f"Run ID:          {result.run_id}")
    print(f"Emails found:    {result.emails_found}")
    print(f"Emails processed:{result.emails_processed}")
    print(f"Emails skipped:  {result.emails_skipped}")
    print(f"Emails failed:   {result.emails_failed}")
    print("-" * 60)

    for step in result.steps:
        print(f"\nEmail: {step.email_id}")
        print(f"  Status: {step.status}")
        if step.skip_reason:
            print(f"  Skip reason: {step.skip_reason}")
        if step.error_message:
            print(f"  Error: {step.error_message}")
        if step.classification:
            c = step.classification
            print(f"  Classification:")
            print(f"    requires_action: {c.requires_action}")
            print(f"    is_inquiry: {c.is_product_or_service_inquiry}")
            print(f"    category: {c.category}")
            print(f"    products: {c.product_names}")
            print(f"    services: {c.service_names}")
            print(f"    reasoning: {c.reasoning}")
        if step.tool_calls:
            print(f"  Tool calls: {step.tool_calls}")
        if step.agent_turns:
            print(f"  Agent turns: {step.agent_turns}")
        if step.decision_trace:
            print(f"  Decisions: {len(step.decision_trace)} steps")
        if step.reply_sent:
            print(f"  Reply: SENT")
        else:
            print(f"  Reply: NOT SENT")

    print("\n" + "=" * 60)


def run_single_cycle(settings, db):
    """Run one agent cycle and return the result."""
    agent = create_agent(settings, db)
    try:
        result = agent.run()
        agent._processed_repo._session.commit()
        return result
    except Exception:
        agent._processed_repo._session.rollback()
        raise
    finally:
        agent._processed_repo._session.close()


def run_continuous(settings, db) -> None:
    """Poll inbox, process mail, then repeat until the user stops (Ctrl+C)."""
    logger = logging.getLogger(__name__)
    interval = max(1, settings.agent_poll_interval_seconds)
    cycle = 0

    logger.info(
        "Continuous mode ON — checking mail every %d second(s). Press Ctrl+C to stop.",
        interval,
    )
    print(
        f"\nContinuous agent running (poll every {interval}s). Press Ctrl+C to stop.\n",
        flush=True,
    )

    try:
        while True:
            cycle += 1
            logger.info("=== Agent cycle %d started ===", cycle)
            result = run_single_cycle(settings, db)
            print_run_results(result)
            logger.info(
                "=== Agent cycle %d complete (processed=%d, skipped=%d, failed=%d) — sleeping %ds ===",
                cycle,
                result.emails_processed,
                result.emails_skipped,
                result.emails_failed,
                interval,
            )
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Continuous agent stopped by user after %d cycle(s).", cycle)
        print(f"\nStopped after {cycle} cycle(s). Goodbye.\n", flush=True)


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    logger = logging.getLogger(__name__)
    logger.info("Starting NovaAI Email Agent")
    logger.info("Email provider: %s", settings.email_provider)
    logger.info("LLM provider: %s", settings.llm_provider)

    db = Database(settings.database_url)

    if settings.agent_continuous_mode:
        run_continuous(settings, db)
    else:
        result = run_single_cycle(settings, db)
        print_run_results(result)

    sys.exit(0)


if __name__ == "__main__":
    main()
