"""Smoke tests for offline eval runner."""

from evals.evaluator import Evaluator


class TestEvalsMock:
    def test_mock_eval_run_completes(self):
        evaluator = Evaluator(force_mock=True)
        report = evaluator.run()
        assert report.total >= 20
        assert report.provider == "mock"
        assert report.runtime_routing_accuracy >= 0.70
        assert report.category_accuracy >= 0.70

    def test_runtime_results_cover_all_emails(self):
        evaluator = Evaluator(force_mock=True)
        report = evaluator.run()
        assert len(report.runtime_results) >= 20
