"""Unit tests for the dialogue Orchestrator.

These tests exercise the Phase 2 seams:

- ``handle_turn`` composes NeedsExtractor + ProfilerAgent correctly.
- Multi-domain free-form text on the first turn (under
  ``question_context="vision"``) populates all three mentioned domains — the
  regression guard for the original bug report.
- Session state persists the patch across turns.
- ``skip`` marks the current domain as skipped so it is not re-asked.
- ``build_profile`` produces a valid ``AccessibilityProfile``.
- ``create_plan`` routes to the PlannerAgent and honors image hazards.
- ``reset`` clears state and honors the new language.
"""

from __future__ import annotations

from backend.app.models import AccessibilityProfile
from backend.app.providers.image_provider import MockImageProvider
from backend.app.providers.llm_provider import MockLLMProvider
from backend.app.providers.route_provider import MockRouteProvider
from backend.app.services.needs_extractor import NeedsExtractor
from backend.app.services.orchestrator import Orchestrator
from backend.app.services.planner_agent import PlannerAgent
from backend.app.services.profiler_agent import ProfilerAgent


def _build_orchestrator(
    *,
    with_planner: bool = False,
    with_image_provider: bool = False,
) -> Orchestrator:
    llm = MockLLMProvider()
    extractor = NeedsExtractor(llm_provider=llm)
    profiler = ProfilerAgent(llm_provider=llm, needs_extractor=extractor)
    planner = PlannerAgent(llm_provider=llm, route_provider=MockRouteProvider()) if with_planner else None
    image_provider = MockImageProvider() if with_image_provider else None
    return Orchestrator(
        profiler=profiler,
        needs_extractor=extractor,
        planner=planner,
        image_provider=image_provider,
    )


# ---------------------------------------------------------------------------
# handle_turn — the Phase 1 bug-trigger utterance
# ---------------------------------------------------------------------------


def test_handle_turn_multi_domain_free_form_populates_three_domains() -> None:
    orchestrator = _build_orchestrator()

    result = orchestrator.handle_turn(
        "yes I have eye problem, also I walk badly, and I can't read complex text"
    )

    patch = result.profile_patch
    assert patch["needs"]["vision"]["blind_or_low_vision"] is True
    assert patch["needs"]["mobility"]["needs_step_free_route"] is True
    assert patch["needs"]["cognitive"]["needs_simple_language"] is True
    assert patch["communication"]["output_mode"] == "simple_text"

    # The patch should be non-empty, so the plan button becomes available.
    assert result.can_generate_plan is True


# ---------------------------------------------------------------------------
# Session state persistence
# ---------------------------------------------------------------------------


def test_handle_turn_persists_patch_across_turns() -> None:
    orchestrator = _build_orchestrator()

    orchestrator.handle_turn("I am blind")
    # After turn 1, the cursor should have advanced past vision.
    assert orchestrator.state.last_question_context != "vision"
    assert orchestrator.state.profile_patch["needs"]["vision"]["blind_or_low_vision"] is True

    # Turn 2 is a pure yes to whatever question_context is now active.
    # We don't hard-code which domain — we just require the vision fact to survive.
    second = orchestrator.handle_turn("yes")
    assert second.profile_patch["needs"]["vision"]["blind_or_low_vision"] is True

    # History should hold both user turns + both assistant turns.
    assert len(orchestrator.state.history) == 4
    assert orchestrator.state.history[0].role == "user"
    assert orchestrator.state.history[1].role == "assistant"


def test_handle_turn_records_history() -> None:
    orchestrator = _build_orchestrator()

    orchestrator.handle_turn("I am blind")

    roles = [t.role for t in orchestrator.state.history]
    assert roles == ["user", "assistant"]
    assert orchestrator.state.history[0].text == "I am blind"


# ---------------------------------------------------------------------------
# Skip tracking
# ---------------------------------------------------------------------------


def test_skip_on_vision_marks_domain_as_skipped() -> None:
    orchestrator = _build_orchestrator()

    result = orchestrator.handle_turn("skip")

    assert "vision" in orchestrator.state.skipped_domains
    # Next question cursor advances past vision.
    assert result.next_question_context != "vision"


# ---------------------------------------------------------------------------
# build_profile
# ---------------------------------------------------------------------------


def test_build_profile_returns_valid_accessibility_profile() -> None:
    orchestrator = _build_orchestrator()
    orchestrator.handle_turn(
        "yes I have eye problem, also I walk badly, and I can't read complex text"
    )

    profile = orchestrator.build_profile()

    assert isinstance(profile, AccessibilityProfile)
    assert profile.needs.vision.blind_or_low_vision is True
    assert profile.needs.mobility.needs_step_free_route is True
    assert profile.needs.cognitive.needs_simple_language is True
    assert profile.communication.output_mode.value == "simple_text"


# ---------------------------------------------------------------------------
# create_plan
# ---------------------------------------------------------------------------


def test_create_plan_raises_without_planner() -> None:
    orchestrator = _build_orchestrator()  # no planner

    orchestrator.handle_turn("I am blind")

    try:
        orchestrator.create_plan(route_id="demo-001")
    except RuntimeError as exc:
        assert "planner" in str(exc).lower()
    else:
        raise AssertionError("Expected RuntimeError when no planner is attached")


def test_create_plan_routes_through_planner_with_hazards() -> None:
    orchestrator = _build_orchestrator(with_planner=True, with_image_provider=True)

    orchestrator.handle_turn("I am blind")

    plan = orchestrator.create_plan(
        route_id="route_with_stairs",
        image_bytes=b"fake-image-bytes",
    )

    # Just assert the plan object is well-formed; the planner itself is
    # separately tested in test_planner_agent.py.
    assert plan.summary  # non-empty summary
    assert plan.directions  # non-empty directions list


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


def test_reset_clears_state_and_switches_language() -> None:
    orchestrator = _build_orchestrator()
    orchestrator.handle_turn("I am blind")

    orchestrator.reset(language="zh")

    assert orchestrator.state.profile_patch == {}
    assert orchestrator.state.skipped_domains == []
    assert orchestrator.state.last_question_context == "vision"
    assert orchestrator.state.language == "zh"
    assert orchestrator.state.history == []


# ---------------------------------------------------------------------------
# Language propagation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 3: skip-advance — multi-domain free-form skips past vision question
# ---------------------------------------------------------------------------


def test_skip_advance_skips_vision_after_multi_domain_free_form() -> None:
    """When the bug-trigger utterance populates vision on turn 1, the next
    question should NOT be about vision — it should advance to hearing (the
    first domain with still-unknown critical fields)."""
    orchestrator = _build_orchestrator()

    result = orchestrator.handle_turn(
        "yes I have eye problem, also I walk badly, and I can't read complex text"
    )

    # Vision is fully populated → skipped. Next should NOT be vision.
    # The profiler may advance to hearing, mobility, cognitive, or confirm
    # depending on which sub-fields remain unknown.
    assert result.next_question_context != "vision"
    assert result.profile_patch["needs"]["vision"]["blind_or_low_vision"] is True


def test_skip_advance_skips_two_domains_after_full_free_form() -> None:
    """If both vision and hearing are resolved in one turn, the system should
    jump past them."""
    orchestrator = _build_orchestrator()

    result = orchestrator.handle_turn(
        "I am blind and I am not deaf"
    )

    # Vision populated (True), hearing populated (False).
    assert result.profile_patch["needs"]["vision"]["blind_or_low_vision"] is True
    assert result.profile_patch["needs"]["hearing"]["deaf_or_hard_of_hearing"] is False
    # Next question should skip both and land on mobility, cognitive, or confirm.
    assert result.next_question_context not in {"vision", "hearing"}


# ---------------------------------------------------------------------------
# Phase 3: confidence hints propagate to ProfilerAgentOutput
# ---------------------------------------------------------------------------


def test_confidence_reflects_source_hints() -> None:
    """After a lexicon-confirmed extraction, per-domain confidence for
    populated domains should be >= 0.8 (not the default 0.5)."""
    orchestrator = _build_orchestrator()

    result = orchestrator.handle_turn("I have eye problem")

    vision_conf = result.profiler_output.confidence.per_domain.vision
    # Lexicon + Mock LLM both agree → source confidence ~0.9, coverage=1.0.
    assert vision_conf >= 0.8, f"Expected >=0.8 but got {vision_conf}"


# ---------------------------------------------------------------------------
# Language propagation
# ---------------------------------------------------------------------------


def test_handle_turn_honors_zh_response_language() -> None:
    orchestrator = _build_orchestrator()

    result = orchestrator.handle_turn("眼睛有问题", response_language="zh")

    assert result.profile_patch["needs"]["vision"]["blind_or_low_vision"] is True
    # Chinese confirmation prefix — mirrors profiler localization.
    assert "了解" in result.confirmation_text or "理解" in result.confirmation_text
    assert orchestrator.state.language == "zh"
