from __future__ import annotations

from backend.app.providers.llm_provider import MockLLMProvider
from backend.app.providers.route_provider import MockRouteProvider
from backend.app.services.planner_agent import PlannerAgent
from backend.app.services.profiler_agent import ProfilerAgent


def test_end_to_end_mock_flow() -> None:
    llm = MockLLMProvider()
    profiler = ProfilerAgent(llm_provider=llm)
    planner = PlannerAgent(llm_provider=llm, route_provider=MockRouteProvider())

    patch: dict = {}
    messages = [
        "I am hard of hearing and use sign language.",
        "I use a wheelchair and need step free routes.",
        "Please use simple english and reminders.",
    ]

    for message in messages:
        out = profiler.process_turn(user_message=message, current_patch=patch)
        patch = out.profile_patch.model_dump()

    profile = profiler.build_profile(profile_patch=patch)
    plan = planner.create_plan(profile=profile, route_id="route_with_stairs")

    assert profile.needs.hearing.deaf_or_hard_of_hearing is True
    assert profile.needs.mobility.needs_step_free_route is True
    assert profile.needs.cognitive.needs_simple_language is True
    assert len(plan.directions) >= 1
    assert len(plan.if_you_get_lost) >= 1
