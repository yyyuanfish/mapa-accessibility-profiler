from __future__ import annotations

from backend.app.evaluation.research_experiments import (
    profiling_cases,
    planning_latex_table,
    run_boundary_planning_suite,
    run_planning_suite,
    run_indoor_adaptation_suite,
)


def test_profiling_suite_contains_long_text_multineed_regression() -> None:
    case = next(item for item in profiling_cases() if item.name == "multi_wheelchair_long_text")

    assert case.expected == {
        "wheelchair_user",
        "needs_step_free_route",
        "needs_simple_language",
    }


def test_indoor_adaptation_suite_reports_no_profile_metrics_as_not_applicable() -> None:
    report = run_indoor_adaptation_suite()

    no_profile = report["summary"]["no_profile"]
    assert no_profile["mobility_step_free_rate"] == "n/a"
    assert no_profile["vision_nonvisual_guidance_rate"] == "n/a"
    assert no_profile["hearing_text_replacement_rate"] == "n/a"
    assert no_profile["cognitive_simple_structure_rate"] == "n/a"
    assert no_profile["adaptation_coverage_rate"] == "n/a"


def test_indoor_adaptation_suite_covers_profile_conditioned_adaptations() -> None:
    report = run_indoor_adaptation_suite()

    profile_only = report["summary"]["profile_only"]
    assert profile_only["route_switch_correct_rate"] == 1.0
    assert profile_only["mobility_step_free_rate"] == 1.0
    assert profile_only["vision_nonvisual_guidance_rate"] == 1.0
    assert profile_only["hearing_text_replacement_rate"] == 1.0
    assert profile_only["cognitive_simple_structure_rate"] == 1.0
    assert profile_only["schema_valid_rate"] == 1.0


def test_boundary_planning_suite_reports_fallbacks_and_unsupported_claims() -> None:
    report = run_boundary_planning_suite()

    summary = report["summary"]["all"]
    assert summary["fallback_warning_rate"] == 1.0
    assert summary["unsupported_accessibility_claim_rate"] == 0.0
    assert summary["multi_need_adaptation_rate"] == 1.0
    assert summary["schema_valid_rate"] == 1.0


def test_planning_suite_includes_single_pass_baseline() -> None:
    report = run_planning_suite()

    assert len(report["case_results"]) == 120
    single_pass = report["summary"]["single_pass_profile"]
    profile_only = report["summary"]["profile_only"]

    assert single_pass["n"] == 30
    assert single_pass["schema_valid_rate"] == 1.0
    assert single_pass["constraint_satisfaction_rate"] < profile_only["constraint_satisfaction_rate"]
    assert single_pass["route_switch_correct_count"] == {"num": 26, "den": 30}
    assert single_pass["constraint_satisfaction_count"] == {"num": 6, "den": 10}

    grounded = report["summary"]["profile_zurich_fixture"]
    assert grounded["zurich_source_count"] == {"num": 30, "den": 30}
    assert grounded["zurich_grounding_text_count"] == {"num": 30, "den": 30}


def test_planning_latex_table_reports_counts_and_unsupported_claims() -> None:
    report = run_planning_suite()
    table = planning_latex_table(report)

    assert "Setting & $n$ & Route" in table
    assert "single-pass & 30 & 0.867 (26/30)" in table
    assert "Unsupported" in table
