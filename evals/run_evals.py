"""Run LLM evaluations separately from unit tests.

Default: mock-only offline (no Mistral API calls).
Use --mistral to evaluate with Mistral when MISTRAL_API_KEY is set.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path so 'evals' can be imported when running as script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.evaluator import Evaluator

EVALS_DIR = Path(__file__).resolve().parent


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main():
    parser = argparse.ArgumentParser(description="Run NovaAI email agent evals")
    parser.add_argument(
        "--mistral",
        action="store_true",
        help="Use Mistral API when key is configured (default is mock-only offline)",
    )
    parser.add_argument(
        "--json-out",
        type=str,
        default="",
        help="Write metrics JSON to this path (e.g. evals/report.json)",
    )
    parser.add_argument(
        "--min-runtime-accuracy",
        type=float,
        default=0.85,
        help="Exit 1 if runtime routing accuracy is below this (mock default 0.85)",
    )
    parser.add_argument(
        "--min-category-accuracy",
        type=float,
        default=0.85,
        help="Exit 1 if classification category accuracy is below this",
    )
    args = parser.parse_args()

    setup_logging()
    force_mock = not args.mistral
    evaluator = Evaluator(force_mock=force_mock)
    report = evaluator.run()
    evaluator.print_report(report)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)
        print(f"\nWrote metrics JSON to {out_path}")

    failed = False
    if report.runtime_routing_accuracy < args.min_runtime_accuracy:
        print(
            f"\nWARNING: Runtime routing accuracy {report.runtime_routing_accuracy:.1%} "
            f"below {args.min_runtime_accuracy:.0%} threshold"
        )
        failed = True
    if report.category_accuracy < args.min_category_accuracy:
        print(
            f"\nWARNING: Category accuracy {report.category_accuracy:.1%} "
            f"below {args.min_category_accuracy:.0%} threshold"
        )
        failed = True

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
