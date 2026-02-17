from __future__ import annotations

from backend.app.models import AccessibilityProfile, OutputMode
from backend.app.providers.llm_provider import MockLLMProvider
from backend.app.providers.route_provider import MockRouteProvider
from backend.app.services.planner_agent import PlannerAgent


def test_planner_retries_once_on_invalid_first_response() -> None:
    llm = MockLLMProvider(invalid_first_for_tasks={"planner"})
    planner = PlannerAgent(llm_provider=llm, route_provider=MockRouteProvider())

    profile = AccessibilityProfile.model_validate(
        {
            "needs": {
                "mobility": {"wheelchair_user": True, "needs_step_free_route": True},
            }
        }
    )

    plan = planner.create_plan(profile=profile, route_id="route_with_stairs")

    assert len(plan.directions) > 0
    assert any("step_free" in item.lower() for item in plan.preferences_applied)


def test_planner_removes_audio_only_cue_for_deaf_profile() -> None:
    planner = PlannerAgent(llm_provider=MockLLMProvider(), route_provider=MockRouteProvider())

    profile = AccessibilityProfile.model_validate(
        {
            "needs": {
                "hearing": {"deaf_or_hard_of_hearing": True},
            }
        }
    )

    plan = planner.create_plan(profile=profile, route_id="route_with_stairs")

    assert not any("listen for" in step.lower() for step in plan.directions)


def test_planner_uses_sign_gloss_mode() -> None:
    planner = PlannerAgent(llm_provider=MockLLMProvider(), route_provider=MockRouteProvider())

    profile = AccessibilityProfile.model_validate(
        {
            "communication": {"output_mode": OutputMode.SIGN_GLOSS_TEXT.value},
            "needs": {
                "hearing": {"sign_language_user": True}
            },
        }
    )

    plan = planner.create_plan(profile=profile, route_id="step_free_route")

    assert plan.summary == plan.summary.upper()


def test_planner_localizes_plan_to_chinese() -> None:
    planner = PlannerAgent(llm_provider=MockLLMProvider(), route_provider=MockRouteProvider())
    profile = AccessibilityProfile.model_validate(
        {
            "needs": {
                "vision": {"blind_or_low_vision": True},
                "mobility": {"wheelchair_user": True, "needs_step_free_route": True},
            }
        }
    )

    plan = planner.create_plan(
        profile=profile,
        route_id="route_with_stairs",
        response_language="zh",
    )

    assert "个性化路线方案" in plan.summary
    assert any("第1步" in step for step in plan.directions)
    formatted = planner.format_plan(plan, language="zh")
    assert "摘要:" in formatted
