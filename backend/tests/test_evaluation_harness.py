from __future__ import annotations

from backend.app.evaluation.harness import EvaluationHarness


def test_evaluation_harness_runs_all_personas() -> None:
    report = EvaluationHarness().run()

    assert len(report["persona_results"]) == 5
    assert 0.0 <= report["aggregate"]["precision"] <= 1.0
    assert 0.0 <= report["aggregate"]["recall"] <= 1.0
