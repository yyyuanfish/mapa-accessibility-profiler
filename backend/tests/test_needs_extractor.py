"""Unit tests for the NeedsExtractor subagent.

Focus: the pure text -> ProfilePatch contract. These tests lock in the
recognition patterns that were the Phase 1 bug fix (`eye problem`,
`walk badly`, `can't read complex text`) and add ZH + DE regression guards so
the multilingual lexicon cannot silently regress.

The MockLLMProvider internally routes through ``needs_taxonomy`` as well, so
every expectation here holds identically for both Mock and Ollama paths as
long as the Ollama few-shot prompt keeps its promises.
"""

from __future__ import annotations

from backend.app.models import ProfilePatch
from backend.app.providers.llm_provider import MockLLMProvider
from backend.app.services.needs_extractor import NeedsExtractor


def _extractor() -> NeedsExtractor:
    return NeedsExtractor(llm_provider=MockLLMProvider())


# ---------------------------------------------------------------------------
# English single-domain patterns
# ---------------------------------------------------------------------------


def test_eye_problem_sets_vision_blind_or_low_vision() -> None:
    patch = _extractor().extract("I have eye problem")
    assert patch["needs"]["vision"]["blind_or_low_vision"] is True


def test_walk_badly_sets_step_free_route() -> None:
    patch = _extractor().extract("I walk badly")
    assert patch["needs"]["mobility"]["needs_step_free_route"] is True


def test_cant_read_complex_text_sets_simple_language() -> None:
    patch = _extractor().extract("I can't read complex text")
    assert patch["needs"]["cognitive"]["needs_simple_language"] is True


# ---------------------------------------------------------------------------
# The original bug-trigger: all three domains in one free-form reply
# ---------------------------------------------------------------------------


def test_bug_trigger_utterance_populates_three_domains() -> None:
    patch = _extractor().extract(
        "yes I have eye problem, also I walk badly, and I can't read complex text",
        current_patch=ProfilePatch(),
        question_context="vision",
    )

    assert patch["needs"]["vision"]["blind_or_low_vision"] is True
    assert patch["needs"]["mobility"]["needs_step_free_route"] is True
    assert patch["needs"]["cognitive"]["needs_simple_language"] is True
    # Simple-language implies simple_text output mode.
    assert patch["communication"]["output_mode"] == "simple_text"


# ---------------------------------------------------------------------------
# Negative phrasing takes precedence over positive
# ---------------------------------------------------------------------------


def test_negative_vision_but_positive_mobility() -> None:
    patch = _extractor().extract("no vision needs, but I walk badly")

    # Negative path for vision.
    assert patch["needs"]["vision"]["blind_or_low_vision"] is False
    # Positive path for mobility still fires.
    assert patch["needs"]["mobility"]["needs_step_free_route"] is True


# ---------------------------------------------------------------------------
# ZH (Simplified Chinese) coverage
# ---------------------------------------------------------------------------


def test_zh_eye_problem_sets_vision() -> None:
    patch = _extractor().extract("眼睛有问题")
    assert patch["needs"]["vision"]["blind_or_low_vision"] is True


def test_zh_walks_badly_sets_step_free() -> None:
    patch = _extractor().extract("走路不好")
    assert patch["needs"]["mobility"]["needs_step_free_route"] is True


def test_zh_complex_text_sets_simple_language() -> None:
    patch = _extractor().extract("读不懂复杂文字")
    assert patch["needs"]["cognitive"]["needs_simple_language"] is True


# ---------------------------------------------------------------------------
# DE (German) coverage
# ---------------------------------------------------------------------------


def test_de_augenproblem_sets_vision() -> None:
    patch = _extractor().extract("Ich habe ein Augenproblem")
    assert patch["needs"]["vision"]["blind_or_low_vision"] is True


def test_de_gehe_schlecht_sets_step_free() -> None:
    patch = _extractor().extract("Ich gehe schlecht")
    assert patch["needs"]["mobility"]["needs_step_free_route"] is True


def test_de_komplexe_texte_sets_simple_language() -> None:
    patch = _extractor().extract("Ich kann keine komplexe Texte lesen")
    assert patch["needs"]["cognitive"]["needs_simple_language"] is True


# ---------------------------------------------------------------------------
# Skip / empty
# ---------------------------------------------------------------------------


def test_skip_produces_empty_patch() -> None:
    patch = _extractor().extract("skip")
    # Lexicon finds nothing; LLM returns empty profile_patch for "skip".
    assert patch == {}


def test_sign_language_sets_sign_gloss_mode() -> None:
    patch = _extractor().extract("I use sign language")
    assert patch["needs"]["hearing"]["sign_language_user"] is True
    assert patch["needs"]["hearing"]["deaf_or_hard_of_hearing"] is True
    assert patch["communication"]["output_mode"] == "sign_gloss_text"


# ---------------------------------------------------------------------------
# Phase 3: extract_with_confidence — domain confidence hints
# ---------------------------------------------------------------------------


def test_extract_with_confidence_returns_domain_hints() -> None:
    """Lexicon-backed domains get >=0.8 confidence; no-signal domains are absent."""
    result = _extractor().extract_with_confidence(
        "I have eye problem and I walk badly"
    )

    assert result.patch["needs"]["vision"]["blind_or_low_vision"] is True
    assert result.patch["needs"]["mobility"]["needs_step_free_route"] is True

    # Both LLM (Mock uses taxonomy) and lexicon agree → 0.9.
    assert result.domain_confidence_hints["vision"] >= 0.8
    assert result.domain_confidence_hints["mobility"] >= 0.8

    # Hearing and cognitive were not mentioned → absent from hints.
    assert "hearing" not in result.domain_confidence_hints
    assert "cognitive" not in result.domain_confidence_hints


def test_extract_with_confidence_skip_has_no_hints() -> None:
    result = _extractor().extract_with_confidence("skip")
    assert result.patch == {}
    assert result.domain_confidence_hints == {}
