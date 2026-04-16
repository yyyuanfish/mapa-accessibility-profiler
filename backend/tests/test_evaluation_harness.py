from __future__ import annotations

from backend.app.evaluation.harness import PERSONAS, EvaluationHarness


def test_evaluation_harness_runs_all_personas() -> None:
    report = EvaluationHarness().run()

    # Use the persona list length rather than a hard-coded number so new
    # regression personas (e.g. ``free_form_multi_needs_persona``) can be
    # added without breaking this test.
    assert len(report["persona_results"]) == len(PERSONAS)
    assert 0.0 <= report["aggregate"]["precision"] <= 1.0
    assert 0.0 <= report["aggregate"]["recall"] <= 1.0


def test_evaluation_harness_free_form_multi_needs_persona_passes() -> None:
    """Regression guard: the bug-trigger free-form utterance populates
    vision + mobility + cognitive in a single turn."""
    report = EvaluationHarness().run()
    free_form = next(
        r for r in report["persona_results"] if r["persona"] == "free_form_multi_needs_persona"
    )
    predicted = set(free_form["predicted"])
    assert "blind_or_low_vision" in predicted
    assert "needs_step_free_route" in predicted
    assert "needs_simple_language" in predicted
