"""Run LLM evaluations separately from unit tests."""

import logging
import sys

from evals.evaluator import Evaluator


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main():
    setup_logging()
    evaluator = Evaluator()
    report = evaluator.run()
    evaluator.print_report(report)

    if report.category_accuracy < 0.5:
        print("\nWARNING: Category accuracy below 50% threshold")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
