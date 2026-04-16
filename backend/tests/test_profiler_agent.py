from __future__ import annotations

from backend.app.providers.llm_provider import MockLLMProvider
from backend.app.services.profiler_agent import ProfilerAgent


def test_profiler_retries_once_on_invalid_first_response() -> None:
    llm = MockLLMProvider(invalid_first_for_tasks={"profiler"})
    agent = ProfilerAgent(llm_provider=llm)

    result = agent.process_turn("I am blind and I use a screen reader.")

    assert result.profile_patch.needs.vision.blind_or_low_vision is True
    assert result.next_question_context == "confirm"
    assert result.confirmation_text.startswith("Here is what I understood:")


def test_profiler_first_turn_uses_dense_triage_and_confirms_clear_mobility_need() -> None:
    llm = MockLLMProvider()
    agent = ProfilerAgent(llm_provider=llm)

    result = agent.process_turn("I use a wheelchair and need step free routes.", turn_count=1)

    assert result.profile_patch.needs.mobility.wheelchair_user is True
    assert result.profile_patch.needs.mobility.needs_step_free_route is True
    assert result.next_question_context == "confirm"


def test_profiler_targets_sign_followup_for_hearing_support() -> None:
    llm = MockLLMProvider()
    agent = ProfilerAgent(llm_provider=llm)

    result = agent.process_turn("I am deaf and I use captions.", turn_count=1)

    assert result.profile_patch.needs.hearing.deaf_or_hard_of_hearing is True
    assert result.profile_patch.needs.hearing.sign_language_user is None
    assert result.next_question_context == "hearing_sign"


def test_profiler_generic_mobility_signal_asks_step_free_not_full_domain_scan() -> None:
    llm = MockLLMProvider()
    agent = ProfilerAgent(llm_provider=llm)

    result = agent.process_turn("I need mobility support.", turn_count=1)

    assert result.profile_patch.needs.mobility.needs_step_free_route is None
    assert result.profile_patch.needs.mobility.wheelchair_user is None
    assert result.next_question_context == "mobility_step_free"


def test_profiler_memory_support_switches_simple_text_without_forcing_simple_language_true() -> None:
    llm = MockLLMProvider()
    agent = ProfilerAgent(llm_provider=llm)

    result = agent.process_turn("I forget directions and need reminders.", turn_count=1)

    assert result.profile_patch.needs.cognitive.needs_memory_support is True
    assert result.profile_patch.needs.cognitive.needs_simple_language is None
    assert result.profile_patch.communication.output_mode.value == "simple_text"
    assert result.next_question_context == "confirm"


def test_profiler_no_special_needs_goes_to_confirm_without_scanning_domains() -> None:
    llm = MockLLMProvider()
    agent = ProfilerAgent(llm_provider=llm)

    result = agent.process_turn("No special needs. Standard is fine.", turn_count=1)

    assert result.profile_patch.needs.vision.blind_or_low_vision is False
    assert result.profile_patch.needs.hearing.deaf_or_hard_of_hearing is False
    assert result.profile_patch.needs.mobility.needs_step_free_route is False
    assert result.profile_patch.needs.cognitive.needs_simple_language is False
    assert result.next_question_context == "confirm"


def test_profiler_confirm_yes_finishes() -> None:
    llm = MockLLMProvider()
    agent = ProfilerAgent(llm_provider=llm)

    first = agent.process_turn("I use a wheelchair and need step free routes.", turn_count=1)
    second = agent.process_turn(
        user_message="yes",
        current_patch=first.profile_patch.model_dump(),
        question_context="confirm",
        turn_count=2,
    )

    assert second.next_question is None
    assert second.next_question_context is None


def test_profiler_unclear_first_turn_repeats_triage_prompt() -> None:
    llm = MockLLMProvider()
    agent = ProfilerAgent(llm_provider=llm)

    result = agent.process_turn("maybe", turn_count=1)

    assert result.next_question_context == "triage"
    assert "personalize routes quickly" in (result.next_question or "")
