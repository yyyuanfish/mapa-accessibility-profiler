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


def test_route_provider_lists_indoor_fixtures() -> None:
    provider = MockRouteProvider()
    route_ids = {route.route_id for route in provider.list_routes()}

    assert {
        "indoor_station_transfer_stairs",
        "indoor_station_transfer_elevator",
        "indoor_museum_visual_signage",
        "indoor_noisy_platform_audio",
        "indoor_university_long_corridor",
        "indoor_hospital_complex_instructions",
    }.issubset(route_ids)


def test_indoor_station_transfer_switches_to_elevator_for_step_free_profile() -> None:
    provider = MockRouteProvider()
    planner = PlannerAgent(llm_provider=MockLLMProvider(), route_provider=provider)
    profile = AccessibilityProfile.model_validate(
        {
            "needs": {
                "mobility": {"wheelchair_user": True, "needs_step_free_route": True},
            }
        }
    )

    selected_route, _, _ = planner._select_route(profile, "indoor_station_transfer_stairs")
    plan = planner.create_plan(profile=profile, route_id="indoor_station_transfer_stairs")

    assert selected_route.route_id == "indoor_station_transfer_elevator"
    assert any("step_free" in item.lower() for item in plan.preferences_applied)


def test_indoor_audio_only_cue_is_replaced_for_deaf_profile() -> None:
    planner = PlannerAgent(llm_provider=MockLLMProvider(), route_provider=MockRouteProvider())
    profile = AccessibilityProfile.model_validate(
        {
            "needs": {
                "hearing": {"deaf_or_hard_of_hearing": True},
            }
        }
    )

    plan = planner.create_plan(profile=profile, route_id="indoor_noisy_platform_audio")

    assert "audio_to_visible_cues" in plan.preferences_applied
    assert not any("listen for" in step.lower() for step in plan.directions)


def test_indoor_visual_only_cue_uses_nonvisual_guidance_for_low_vision_profile() -> None:
    planner = PlannerAgent(llm_provider=MockLLMProvider(), route_provider=MockRouteProvider())
    profile = AccessibilityProfile.model_validate(
        {
            "needs": {
                "vision": {"blind_or_low_vision": True, "prefers_landmarks": True},
            }
        }
    )

    plan = planner.create_plan(profile=profile, route_id="indoor_museum_visual_signage")
    directions = " ".join(plan.directions).lower()

    assert "nonvisual_indoor_guidance" in plan.preferences_applied
    assert "look for" not in directions
    assert "see the" not in directions


def test_indoor_cognitive_profile_uses_simple_structure() -> None:
    planner = PlannerAgent(llm_provider=MockLLMProvider(), route_provider=MockRouteProvider())
    profile = AccessibilityProfile.model_validate(
        {
            "needs": {
                "cognitive": {
                    "needs_simple_language": True,
                    "needs_memory_support": True,
                    "reading_or_memory_difficulty_or_child": True,
                }
            },
            "communication": {"output_mode": "simple_text"},
        }
    )

    plan = planner.create_plan(profile=profile, route_id="indoor_hospital_complex_instructions")

    assert "simple_english_mode" in plan.preferences_applied
    assert "Check each step before you move." in plan.checklist
