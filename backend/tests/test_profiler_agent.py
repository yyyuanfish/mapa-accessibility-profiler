from __future__ import annotations

from backend.app.providers.llm_provider import MockLLMProvider
from backend.app.services.profiler_agent import ProfilerAgent


def test_profiler_retries_once_on_invalid_first_response() -> None:
    llm = MockLLMProvider(invalid_first_for_tasks={"profiler"})
    agent = ProfilerAgent(llm_provider=llm)

    result = agent.process_turn("I am blind and I use a screen reader.")

    assert result.profile_patch.needs.vision.blind_or_low_vision is True
    assert result.confirmation_text.startswith("Here is what I understood")


def test_profiler_auto_switches_to_simple_text_for_cognitive_needs() -> None:
    llm = MockLLMProvider()
    agent = ProfilerAgent(llm_provider=llm)

    result = agent.process_turn("Please use simple english. I need memory reminders.")

    assert result.profile_patch.needs.cognitive.needs_simple_language is True
    assert result.profile_patch.needs.cognitive.needs_memory_support is True
    assert result.profile_patch.communication.output_mode.value == "simple_text"


def test_profiler_handles_skipped_domain() -> None:
    llm = MockLLMProvider()
    agent = ProfilerAgent(llm_provider=llm)

    result = agent.process_turn(
        user_message="skip",
        current_patch={},
        skipped_domains=["vision"],
    )

    assert "needs.vision.blind_or_low_vision" not in result.missing_critical_fields


def test_profiler_context_short_answer_in_chinese_updates_vision() -> None:
    llm = MockLLMProvider()
    agent = ProfilerAgent(llm_provider=llm)

    result = agent.process_turn(
        user_message="有",
        current_patch={},
        question_context="vision",
        response_language="zh",
    )

    assert result.profile_patch.needs.vision.blind_or_low_vision is True
    assert result.next_question_context == "hearing"
    assert result.confirmation_text.startswith("我的理解是：")


def test_profiler_asks_sign_followup_after_hearing_yes() -> None:
    llm = MockLLMProvider()
    agent = ProfilerAgent(llm_provider=llm)

    result = agent.process_turn(
        user_message="yes",
        current_patch={},
        question_context="hearing",
        response_language="en",
        skipped_domains=["vision"],
    )

    assert result.profile_patch.needs.hearing.deaf_or_hard_of_hearing is True
    assert result.next_question_context == "hearing_sign"


def test_profiler_sign_answer_in_german_sets_sign_mode() -> None:
    llm = MockLLMProvider()
    agent = ProfilerAgent(llm_provider=llm)

    first = agent.process_turn(
        user_message="yes",
        current_patch={},
        question_context="hearing",
        response_language="de",
    )
    second = agent.process_turn(
        user_message="ja",
        current_patch=first.profile_patch.model_dump(),
        question_context="hearing_sign",
        response_language="de",
    )

    assert second.profile_patch.needs.hearing.sign_language_user is True
    assert second.profile_patch.communication.output_mode.value == "sign_gloss_text"
    assert second.confirmation_text.startswith("Ich habe Folgendes verstanden:")


def test_profiler_context_short_answer_fou_in_chinese_maps_to_no() -> None:
    llm = MockLLMProvider()
    agent = ProfilerAgent(llm_provider=llm)

    result = agent.process_turn(
        user_message="否",
        current_patch={},
        question_context="hearing",
        response_language="zh",
    )

    assert result.profile_patch.needs.hearing.deaf_or_hard_of_hearing is False
