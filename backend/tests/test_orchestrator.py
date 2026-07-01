from __future__ import annotations

from backend.app.models import AccessibilityProfile
from backend.app.providers.llm_provider import MockLLMProvider
from backend.app.providers.route_provider import MockRouteProvider
from backend.app.providers.speech_provider import MockSpeechProvider
from backend.app.services.orchestrator import Orchestrator
from backend.app.services.planner_agent import PlannerAgent
from backend.app.services.profiler_agent import ProfilerAgent


def build_orchestrator() -> Orchestrator:
    route_provider = MockRouteProvider()
    llm_provider = MockLLMProvider()
    profiler = ProfilerAgent(llm_provider=llm_provider)
    planner = PlannerAgent(llm_provider=llm_provider, route_provider=route_provider)
    return Orchestrator(
        profiler_agent=profiler,
        planner_agent=planner,
        route_provider=route_provider,
    )


def test_orchestrator_profile_turn_returns_trace_and_profile() -> None:
    orchestrator = build_orchestrator()

    result = orchestrator.process_profile_turn(
        user_message="I use a wheelchair and need step free routes.",
        current_patch={},
        response_language="en",
        turn_count=1,
    )

    assert result.draft_profile.needs.mobility.wheelchair_user is True
    assert result.draft_profile.needs.mobility.needs_step_free_route is True
    assert result.trace.workflow == "profile_workflow"
    assert [step.agent_name for step in result.trace.steps] == [
        "consent_guard_node",
        "profiler_node",
        "profile_manager_node",
        "conversation_orchestrator_node",
    ]
    assert "step_free_route" in result.agent_reply


def test_orchestrator_plan_returns_route_decision_and_trace() -> None:
    orchestrator = build_orchestrator()
    profile = AccessibilityProfile.model_validate(
        {
            "needs": {
                "mobility": {"wheelchair_user": True, "needs_step_free_route": True},
                "cognitive": {"needs_simple_language": True},
            }
        }
    )

    result = orchestrator.create_journey_plan(
        profile=profile,
        route_id="route_with_stairs",
        image_hazards={
            "stairs": "high",
            "slope": "medium",
            "crowd": "none",
            "scene_summary": "A staircase is visible next to the main path.",
            "visible_objects": ["stairs", "handrail"],
            "accessibility_cues": ["stairs visible", "handrail visible"],
            "notes": ["Check elevators first."],
        },
        response_language="en",
    )

    assert result.route_decision.selected_route_id == "step_free_route"
    assert result.route_decision.switched_to_step_free is True
    # hazard source includes route_metadata and image_hazards (may also include
    # zurich_ogd_zueriact if the live WFS fetch succeeds in this environment)
    assert "route_metadata" in result.hazard_summary.source
    assert "image_hazards" in result.hazard_summary.source
    assert any("possible stairs" in item for item in result.hazard_summary.highlights)
    assert any("vision cues" in item for item in result.hazard_summary.highlights)
    assert "symbolic_vision_feedback" in result.plan.preferences_applied
    assert result.trace.workflow == "planning_workflow"
    step_names = [step.agent_name for step in result.trace.steps]
    # Updated pipeline: input_validator → zurich_data_fetcher → [parallel fan-out x3] → hazard_fusion → planner → synthesis
    assert step_names[0] == "input_validator_node"
    assert step_names[1] == "zurich_data_fetcher_node"
    # Parallel nodes (order may vary within the parallel band)
    parallel_nodes = set(step_names[2:5])
    assert parallel_nodes == {"route_reasoner_node", "image_hazard_node", "amenity_locator_node"}
    # Sequential tail always in this order
    assert step_names[-3:] == ["hazard_fusion_node", "planner_node", "synthesis_node"]


def test_orchestrator_transcribes_audio_and_prepares_spoken_text() -> None:
    orchestrator = Orchestrator(
        speech_provider=MockSpeechProvider(transcripts={"en": "I need simple language."})
    )

    transcription = orchestrator.transcribe_audio(b"fake-audio", response_language="en")
    speech_text = orchestrator.prepare_spoken_text("Hello\n\nthere.", response_language="en")

    assert transcription.transcript == "I need simple language."
    assert speech_text == "Hello there."
