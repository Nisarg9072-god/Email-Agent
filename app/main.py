"""CLI entry point for the NovaAI Email Agent."""

import logging
import sys

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
        if step.reply_sent:
            print(f"  Reply: SENT")
        else:
            print(f"  Reply: NOT SENT")

    print("\n" + "=" * 60)


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    logger = logging.getLogger(__name__)
    logger.info("Starting NovaAI Email Agent")
    logger.info("Email provider: %s", settings.email_provider)
    logger.info("LLM provider: %s", settings.llm_provider)

    db = Database(settings.database_url)
    agent = create_agent(settings, db)

    try:
        result = agent.run()
        agent._processed_repo._session.commit()
        print_run_results(result)
    except Exception:
        agent._processed_repo._session.rollback()
        raise
    finally:
        agent._processed_repo._session.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
