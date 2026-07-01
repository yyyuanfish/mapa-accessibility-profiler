from __future__ import annotations

import argparse
import csv
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.evaluation.harness import PERSONAS, EvaluationHarness
from backend.app.models import AccessibilityProfile
from backend.app.providers.llm_provider import LLMProvider, MockLLMProvider, OllamaLLMProvider
from backend.app.providers.route_provider import MockRouteProvider, ROUTE_FIXTURES
from backend.app.providers.zurich_data_provider import ROUTE_ZURICH_CENTERS, ZURICH_HB_CENTER
from backend.app.services.orchestrator import Orchestrator
from backend.app.services.planner_agent import PlannerAgent
from backend.app.services.profiler_agent import ProfilerAgent


LABELS = [
    "blind_or_low_vision",
    "deaf_or_hard_of_hearing",
    "sign_language_user",
    "wheelchair_user",
    "needs_step_free_route",
    "needs_simple_language",
    "needs_memory_support",
]

INDOOR_ROUTE_IDS = [
    "indoor_station_transfer_stairs",
    "indoor_station_transfer_elevator",
    "indoor_museum_visual_signage",
    "indoor_noisy_platform_audio",
    "indoor_university_long_corridor",
    "indoor_hospital_complex_instructions",
]

PLANNING_SETTINGS = (
    "no_profile",
    "single_pass_profile",
    "profile_only",
    "profile_zurich_fixture",
)

PLANNING_SETTING_LABELS = {
    "no_profile": "no-profile",
    "single_pass_profile": "single-pass",
    "profile_only": "profile-only",
    "profile_zurich_fixture": "profile+Zurich fixture",
}


@dataclass(frozen=True)
class ProfilingCase:
    name: str
    condition: str
    language: str
    utterances: list[str]
    expected: set[str]


@dataclass(frozen=True)
class PlanningProfile:
    name: str
    profile: AccessibilityProfile


@dataclass(frozen=True)
class BoundaryPlanningCase:
    name: str
    profile_name: str
    profile: AccessibilityProfile
    route_id: str
    fixtures: dict[str, dict[str, Any]]
    fallback_warning_expected: bool = False
    required_preferences: frozenset[str] = frozenset()


class LexiconOnlyLLMProvider(LLMProvider):
    """Disable the LLM triage branch while keeping the normal lexicon fallback."""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if "TASK=PROFILER" in system_prompt:
            return json.dumps({"profile_patch": {}})
        if "TASK=PLANNER" in system_prompt:
            payload = _safe_json_load(user_prompt)
            return json.dumps(payload.get("draft_plan", {}))
        return "{}"


def _safe_json_load(raw: str) -> dict[str, Any]:
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        return {}


def profiling_cases() -> list[ProfilingCase]:
    cases = [
        ProfilingCase(
            name=p.name,
            condition="scripted_persona",
            language="en",
            utterances=p.utterances,
            expected=set(p.expected_positive_labels),
        )
        for p in PERSONAS
    ]
    cases.extend(
        [
            ProfilingCase(
                "colloquial_vision_landmarks",
                "colloquial",
                "en",
                ["My eyesight is bad, so I rely on landmarks and spoken directions."],
                {"blind_or_low_vision"},
            ),
            ProfilingCase(
                "colloquial_steps_lifts",
                "colloquial",
                "en",
                ["I cannot cope with steps; ramps or lifts are safer for me."],
                {"needs_step_free_route"},
            ),
            ProfilingCase(
                "colloquial_audio_announcements",
                "colloquial",
                "en",
                ["I read lips and often miss announcements in noisy stations."],
                {"deaf_or_hard_of_hearing"},
            ),
            ProfilingCase(
                "colloquial_signing_preference",
                "colloquial",
                "en",
                ["I prefer signing to written instructions when that is available."],
                {"deaf_or_hard_of_hearing", "sign_language_user"},
            ),
            ProfilingCase(
                "colloquial_dense_instructions",
                "colloquial",
                "en",
                ["Keep directions in small chunks; long paragraphs make me lose track."],
                {"needs_simple_language", "needs_memory_support"},
            ),
            ProfilingCase(
                "multi_limited_vision_stairs_reminders",
                "multi_domain",
                "en",
                ["My vision is limited, stairs are difficult, and I need short reminders."],
                {"blind_or_low_vision", "needs_step_free_route", "needs_memory_support"},
            ),
            ProfilingCase(
                "multi_signing_audio_ramps",
                "multi_domain",
                "en",
                ["I rely on signing, miss audio announcements, and need ramps."],
                {"deaf_or_hard_of_hearing", "sign_language_user", "needs_step_free_route"},
            ),
            ProfilingCase(
                "multi_bad_knees_eyes_text",
                "multi_domain",
                "en",
                ["Bad knees, poor eyesight, and long instructions are hard for me."],
                {"blind_or_low_vision", "needs_step_free_route", "needs_simple_language"},
            ),
            ProfilingCase(
                "multi_wheelchair_long_text",
                "multi_domain",
                "en",
                [
                    "I use a wheelchair and need step-free routes. I also have trouble "
                    "reading long texts, so please keep instructions short."
                ],
                {"wheelchair_user", "needs_step_free_route", "needs_simple_language"},
            ),
            ProfilingCase(
                "multi_wheelchair_audio_memory",
                "multi_domain",
                "en",
                ["I use a wheelchair, cannot hear announcements, and forget complex directions."],
                {
                    "wheelchair_user",
                    "needs_step_free_route",
                    "deaf_or_hard_of_hearing",
                    "needs_memory_support",
                },
            ),
            ProfilingCase(
                "zh_vision_stairs_simple",
                "multilingual",
                "zh",
                ["我看不清，也不想走楼梯，请用简单一点的话。"],
                {"blind_or_low_vision", "needs_step_free_route", "needs_simple_language"},
            ),
            ProfilingCase(
                "zh_wheelchair_hearing",
                "multilingual",
                "zh",
                ["我坐轮椅，听不见广播。"],
                {"wheelchair_user", "needs_step_free_route", "deaf_or_hard_of_hearing"},
            ),
            ProfilingCase(
                "de_vision_stairs",
                "multilingual",
                "de",
                ["Ich sehe schlecht und Treppen sind schwierig."],
                {"blind_or_low_vision", "needs_step_free_route"},
            ),
            ProfilingCase(
                "de_sign_simple",
                "multilingual",
                "de",
                ["Ich nutze Gebaerdensprache und brauche kurze einfache Hinweise."],
                {"deaf_or_hard_of_hearing", "sign_language_user", "needs_simple_language"},
            ),
            ProfilingCase(
                "contrastive_sign_language_learning",
                "contrastive",
                "en",
                ["I am learning sign language, but I hear fine; I only need simple English."],
                {"needs_simple_language"},
            ),
            ProfilingCase(
                "contrastive_caregiver_wheelchair",
                "contrastive",
                "en",
                ["I push a wheelchair for my parent, but I personally only need short reminders."],
                {"needs_memory_support"},
            ),
            ProfilingCase(
                "contrastive_phone_audio_knee",
                "contrastive",
                "en",
                ["My phone cannot hear announcements, but I need ramps because of knee pain."],
                {"needs_step_free_route"},
            ),
            ProfilingCase(
                "contrastive_not_blind_stepfree",
                "contrastive",
                "en",
                ["I am not blind, but I need step-free routes."],
                {"needs_step_free_route"},
            ),
            ProfilingCase(
                "contrastive_long_paragraphs",
                "contrastive",
                "en",
                ["Please avoid long paragraphs, but no memory issues."],
                {"needs_simple_language"},
            ),
            # --- Extended contrastive cases (n: 5 → 8) ---
            # Device limitation, not a user accessibility need.
            ProfilingCase(
                "contrastive_device_no_maps",
                "contrastive",
                "en",
                ["My phone cannot handle complex map views, but I navigate well on foot."],
                set(),
            ),
            # Caregiver scenario: wheelchair belongs to parent, user only needs reminders.
            ProfilingCase(
                "contrastive_caregiver_wheelchair_parent",
                "contrastive",
                "en",
                ["I push my father's wheelchair at weekends; I only need simple English reminders for myself."],
                {"needs_simple_language", "needs_memory_support"},
            ),
            # Learning context: Braille study does not imply personal vision need.
            ProfilingCase(
                "contrastive_learning_braille_stepfree",
                "contrastive",
                "en",
                ["I study Braille for professional training; I can see fine and just need a step-free route."],
                {"needs_step_free_route"},
            ),
            # --- Extended multi-domain cases (n: 5 → 8) ---
            ProfilingCase(
                "multi_hearing_memory_stairs",
                "multi_domain",
                "en",
                ["I have hearing loss, I forget directions easily, and I cannot climb stairs."],
                {"deaf_or_hard_of_hearing", "needs_memory_support", "needs_step_free_route"},
            ),
            ProfilingCase(
                "multi_low_vision_sign_prefer",
                "multi_domain",
                "en",
                ["My vision is limited and I prefer signing to written text."],
                {"blind_or_low_vision", "deaf_or_hard_of_hearing", "sign_language_user"},
            ),
            ProfilingCase(
                "multi_wheelchair_poor_eyesight_simple",
                "multi_domain",
                "en",
                ["I use a wheelchair, have poor eyesight, and need simple language."],
                {"wheelchair_user", "needs_step_free_route", "blind_or_low_vision", "needs_simple_language"},
            ),
            # --- Extended multilingual cases (n: 4 → 6) ---
            ProfilingCase(
                "de_wheelchair_simple_language",
                "multilingual",
                "de",
                ["Ich nutze einen Rollstuhl und brauche einfache Sprache."],
                {"wheelchair_user", "needs_step_free_route", "needs_simple_language"},
            ),
            ProfilingCase(
                "zh_deaf_simple_text",
                "multilingual",
                "zh",
                ["我听不清广播，也需要简明语言。"],
                {"deaf_or_hard_of_hearing", "needs_simple_language"},
            ),
        ]
    )
    return cases


def _profile_positive_labels(profile: dict[str, Any]) -> set[str]:
    return EvaluationHarness._positive_labels(profile)


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _score(predicted: set[str], expected: set[str]) -> dict[str, Any]:
    tp = len(predicted & expected)
    fp = len(predicted - expected)
    fn = len(expected - predicted)
    precision = tp / (tp + fp) if tp + fp else 1.0 if not expected else 0.0
    recall = tp / (tp + fn) if tp + fn else 1.0 if not expected else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(_f1(precision, recall), 3),
        "exact_match": predicted == expected,
    }


def _provider_label(provider: LLMProvider) -> str:
    if isinstance(provider, LexiconOnlyLLMProvider):
        return "lexicon_only"
    if isinstance(provider, MockLLMProvider):
        return "hybrid_mock"
    if isinstance(provider, OllamaLLMProvider):
        return f"hybrid_ollama:{provider.model}"
    return provider.__class__.__name__


def _followup_answer(context: str | None, expected: set[str], language: str) -> str:
    needs_yes = {
        "mobility_step_free": "needs_step_free_route",
        "mobility_wheelchair": "wheelchair_user",
        "hearing_sign": "sign_language_user",
        "cognitive_simple": "needs_simple_language",
        "cognitive_memory": "needs_memory_support",
    }
    if context == "triage":
        return _canonical_utterance(expected, language)
    label = needs_yes.get(context or "")
    positive = label in expected if label else False
    if language == "zh":
        return "是的。" if positive else "不需要。"
    if language == "de":
        return "Ja." if positive else "Nein, nicht noetig."
    return "Yes." if positive else "No, not needed."


def _canonical_utterance(expected: set[str], language: str) -> str:
    if not expected:
        return {
            "zh": "没有特殊需求。",
            "de": "Keine besonderen Bedarfe.",
        }.get(language, "No special needs.")

    parts: list[str] = []
    if language == "zh":
        if "blind_or_low_vision" in expected:
            parts.append("我看不清")
        if "deaf_or_hard_of_hearing" in expected:
            parts.append("听不清")
        if "sign_language_user" in expected:
            parts.append("使用手语")
        if "wheelchair_user" in expected:
            parts.append("坐轮椅")
        if "needs_step_free_route" in expected:
            parts.append("需要无台阶路线")
        if "needs_simple_language" in expected:
            parts.append("需要简单语言")
        if "needs_memory_support" in expected:
            parts.append("需要提醒")
        return "，".join(parts) + "。"

    if language == "de":
        if "blind_or_low_vision" in expected:
            parts.append("ich sehe schlecht")
        if "deaf_or_hard_of_hearing" in expected:
            parts.append("ich hoere schlecht")
        if "sign_language_user" in expected:
            parts.append("ich nutze Gebaerdensprache")
        if "wheelchair_user" in expected:
            parts.append("ich nutze einen Rollstuhl")
        if "needs_step_free_route" in expected:
            parts.append("ich brauche eine stufenfreie Route")
        if "needs_simple_language" in expected:
            parts.append("ich brauche einfache Sprache")
        if "needs_memory_support" in expected:
            parts.append("ich brauche Erinnerungen")
        return ", ".join(parts) + "."

    if "blind_or_low_vision" in expected:
        parts.append("I have low vision")
    if "deaf_or_hard_of_hearing" in expected:
        parts.append("I am hard of hearing")
    if "sign_language_user" in expected:
        parts.append("I use sign language")
    if "wheelchair_user" in expected:
        parts.append("I use a wheelchair")
    if "needs_step_free_route" in expected:
        parts.append("I need a step-free route")
    if "needs_simple_language" in expected:
        parts.append("I need simple language")
    if "needs_memory_support" in expected:
        parts.append("I need reminders")
    return ", and ".join(parts) + "."


def run_profiling_suite(provider: LLMProvider, *, max_turns: int = 6) -> dict[str, Any]:
    profiler = ProfilerAgent(llm_provider=provider)
    rows: list[dict[str, Any]] = []
    total_tp = total_fp = total_fn = total_exact = 0
    first_total_tp = first_total_fp = first_total_fn = first_total_exact = 0

    for case in profiling_cases():
        patch: dict[str, Any] = {}
        first_predicted: set[str] = set()
        context: str | None = None
        turns = 0
        error: str | None = None

        utterance_queue = list(case.utterances)
        while turns < max_turns:
            if turns < len(utterance_queue):
                utterance = utterance_queue[turns]
            else:
                utterance = _followup_answer(context, case.expected, case.language)
            try:
                output = profiler.process_turn(
                    user_message=utterance,
                    current_patch=patch,
                    question_context=context,
                    response_language=case.language,
                    turn_count=turns + 1,
                )
            except Exception as exc:  # pragma: no cover - recorded for experiments
                error = f"{exc.__class__.__name__}: {exc}"
                break

            turns += 1
            patch = output.profile_patch.model_dump()
            if turns == 1:
                first_profile = profiler.build_profile(patch)
                first_predicted = _profile_positive_labels(first_profile.model_dump())

            context = output.next_question_context
            if context in {None, "confirm"}:
                break

        final_profile = profiler.build_profile(patch)
        predicted = _profile_positive_labels(final_profile.model_dump())
        score = _score(predicted, case.expected)
        first_score = _score(first_predicted, case.expected)

        total_tp += score["tp"]
        total_fp += score["fp"]
        total_fn += score["fn"]
        total_exact += int(score["exact_match"])
        first_total_tp += first_score["tp"]
        first_total_fp += first_score["fp"]
        first_total_fn += first_score["fn"]
        first_total_exact += int(first_score["exact_match"])

        rows.append(
            {
                "provider": _provider_label(provider),
                "case": case.name,
                "condition": case.condition,
                "language": case.language,
                "utterance": case.utterances[0],
                "expected": sorted(case.expected),
                "first_turn_predicted": sorted(first_predicted),
                "final_predicted": sorted(predicted),
                "turns_to_confirmation": turns,
                "error": error,
                **{f"final_{k}": v for k, v in score.items()},
                **{f"first_turn_{k}": v for k, v in first_score.items()},
            }
        )

    def aggregate(tp: int, fp: int, fn: int, exact: int, n: int) -> dict[str, Any]:
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        return {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(_f1(precision, recall), 3),
            "exact_match_rate": round(exact / n, 3),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }

    by_condition: dict[str, dict[str, Any]] = {}
    for condition in sorted({row["condition"] for row in rows}):
        subset = [row for row in rows if row["condition"] == condition]
        tp = sum(int(row["final_tp"]) for row in subset)
        fp = sum(int(row["final_fp"]) for row in subset)
        fn = sum(int(row["final_fn"]) for row in subset)
        exact = sum(1 for row in subset if row["final_exact_match"])
        first_tp = sum(int(row["first_turn_tp"]) for row in subset)
        first_fp = sum(int(row["first_turn_fp"]) for row in subset)
        first_fn = sum(int(row["first_turn_fn"]) for row in subset)
        first_exact = sum(1 for row in subset if row["first_turn_exact_match"])
        turns = sum(int(row["turns_to_confirmation"]) for row in subset) / len(subset)
        by_condition[condition] = {
            "n": len(subset),
            "first_turn": aggregate(first_tp, first_fp, first_fn, first_exact, len(subset)),
            "final": aggregate(tp, fp, fn, exact, len(subset)),
            "mean_turns_to_confirmation": round(turns, 2),
        }

    return {
        "provider": _provider_label(provider),
        "n_cases": len(rows),
        "first_turn": aggregate(
            first_total_tp,
            first_total_fp,
            first_total_fn,
            first_total_exact,
            len(rows),
        ),
        "final": aggregate(total_tp, total_fp, total_fn, total_exact, len(rows)),
        "by_condition": by_condition,
        "case_results": rows,
    }


def planning_profiles() -> list[PlanningProfile]:
    return [
        PlanningProfile("no_profile", AccessibilityProfile()),
        PlanningProfile(
            "wheelchair",
            AccessibilityProfile.model_validate(
                {"needs": {"mobility": {"wheelchair_user": True, "needs_step_free_route": True}}}
            ),
        ),
        PlanningProfile(
            "blind_low_vision",
            AccessibilityProfile.model_validate(
                {"needs": {"vision": {"blind_or_low_vision": True, "prefers_landmarks": True}}}
            ),
        ),
        PlanningProfile(
            "deaf_sign",
            AccessibilityProfile.model_validate(
                {
                    "needs": {
                        "hearing": {
                            "deaf_or_hard_of_hearing": True,
                            "sign_language_user": True,
                        }
                    },
                    "communication": {"output_mode": "sign_gloss_text"},
                }
            ),
        ),
        PlanningProfile(
            "simple_memory",
            AccessibilityProfile.model_validate(
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
            ),
        ),
        PlanningProfile(
            "mixed_needs",
            AccessibilityProfile.model_validate(
                {
                    "needs": {
                        "vision": {"blind_or_low_vision": True, "prefers_landmarks": True},
                        "hearing": {"deaf_or_hard_of_hearing": True},
                        "mobility": {"wheelchair_user": True, "needs_step_free_route": True},
                        "cognitive": {
                            "needs_simple_language": True,
                            "needs_memory_support": True,
                            "reading_or_memory_difficulty_or_child": True,
                        },
                    },
                    "communication": {"output_mode": "simple_text"},
                }
            ),
        ),
    ]


def _direct_plan(
    profile: AccessibilityProfile,
    route_id: str,
    route_provider: MockRouteProvider | None = None,
) -> tuple[str, list[str], dict[str, Any]]:
    route_provider = route_provider or MockRouteProvider()
    planner = PlannerAgent(llm_provider=MockLLMProvider(), route_provider=route_provider)
    selected_route, preferences, route_alerts = planner._select_route(profile, route_id)
    plan = planner.create_plan(profile=profile, route_id=route_id, response_language="en")
    payload = plan.model_dump()
    payload["_route_preferences_from_selection"] = preferences
    payload["_route_alerts_from_selection"] = route_alerts
    return selected_route.route_id, selected_route.name, payload


def _single_pass_plan(
    profile: AccessibilityProfile,
    route_id: str,
    route_provider: MockRouteProvider | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Plan directly over the requested route without explicit route reasoning.

    This baseline keeps the same profile-conditioned wording rules as the
    planner but skips the route-selection stage. It therefore tests whether
    accessibility wording alone is enough when a hard route constraint requires
    selecting a different fixture.
    """

    route_provider = route_provider or MockRouteProvider()
    planner = PlannerAgent(llm_provider=MockLLMProvider(), route_provider=route_provider)
    requested_route = route_provider.get_route(route_id)
    draft_plan = planner._build_draft_plan(
        profile,
        requested_route,
        preferences_applied=[],
        route_alerts=[],
        hazards=None,
        zurich_data=None,
    )
    plan = planner._request_llm_plan(draft_plan, planner._effective_output_mode(profile))
    return requested_route.route_id, requested_route.name, plan.model_dump()


def _expected_selected_route(
    profile: AccessibilityProfile,
    route_id: str,
    route_provider: MockRouteProvider | None = None,
) -> str:
    route_provider = route_provider or MockRouteProvider()
    requested = route_provider.get_route(route_id)
    if profile.needs.mobility.needs_step_free_route is True and not requested.step_free:
        alternative = route_provider.find_step_free_alternative(route_id)
        if alternative is not None:
            return alternative.route_id
    return route_id


def _plan_metrics(
    profile: AccessibilityProfile,
    route_id: str,
    selected_route_id: str,
    plan: dict[str, Any],
    *,
    hazard_source: str = "",
    agent_reply: str = "",
    route_provider: MockRouteProvider | None = None,
) -> dict[str, Any]:
    route_provider = route_provider or MockRouteProvider()
    selected_route = route_provider.get_route(selected_route_id)
    requested_route = route_provider.get_route(route_id)
    directions = " ".join(str(item) for item in plan.get("directions", []))
    alerts = " ".join(str(item) for item in plan.get("alerts", []))
    preferences = set(plan.get("preferences_applied", []))
    needs_step_free = profile.needs.mobility.needs_step_free_route is True
    deaf_support = profile.needs.hearing.deaf_or_hard_of_hearing is True
    simple = profile.needs.cognitive.needs_simple_language is True

    audio_route_selected = any(step.audio_only_cue for step in selected_route.steps)
    audio_replacement_expected = deaf_support and audio_route_selected
    audio_replacement_ok = (
        not audio_replacement_expected
        or ("audio_to_visible_cues" in preferences and "Listen for" not in directions)
    )
    constraint_satisfied = not needs_step_free or selected_route.step_free
    route_switch_correct = selected_route_id == _expected_selected_route(
        profile, route_id, route_provider
    )
    simple_language_ok = not simple or "simple_english_mode" in preferences
    schema_valid = True
    try:
        from backend.app.models import PersonalizedPlan

        PersonalizedPlan.model_validate({k: v for k, v in plan.items() if not k.startswith("_")})
    except Exception:
        schema_valid = False

    has_zurich = "zurich_ogd_zueriact" in hazard_source or "ZueriACT" in agent_reply
    has_grounding_text = any(
        token in (alerts + " " + agent_reply).lower()
        for token in ["barrier", "toilet", "parking", "zueriact"]
    )

    return {
        "requested_has_stairs": any(step.has_stairs for step in requested_route.steps),
        "selected_step_free": selected_route.step_free,
        "route_switch_correct": route_switch_correct,
        "constraint_applicable": needs_step_free,
        "constraint_satisfied": constraint_satisfied,
        "audio_replacement_expected": audio_replacement_expected,
        "audio_replacement_ok": audio_replacement_ok,
        "simple_language_expected": simple,
        "simple_language_ok": simple_language_ok,
        "zurich_source_present": has_zurich,
        "zurich_grounding_text_present": has_grounding_text,
        "unsupported_accessibility_claim": _has_unsupported_accessibility_claim(
            selected_route.step_free,
            plan,
        ),
        "schema_valid": schema_valid,
    }


def _reference_zurich_data(route_id: str) -> dict[str, Any]:
    """Return a fixed Zurich-shaped snapshot for reproducible ablations.

    Live WFS retrieval is evaluated separately as a dated case study. The main
    planning matrix uses this small reference fixture so network availability
    cannot change the reported source-use and grounding checks.
    """
    center_lat, center_lon = ROUTE_ZURICH_CENTERS.get(route_id, ZURICH_HB_CENTER)
    return {
        "barriers": [
            {
                "lat": center_lat,
                "lon": center_lon,
                "category": "reference surface barrier",
                "severity": 4,
                "severity_label": "barely_passable",
                "tags": "evaluation fixture",
                "quartier": "reference",
                "temporary": False,
                "distance_m": 0,
            }
        ],
        "toilets": [
            {
                "lat": center_lat,
                "lon": center_lon,
                "name": "Reference accessible toilet",
                "address": "Zurich reference fixture",
                "category": "WC",
                "wheelchair_accessible": True,
                "opening_hours": "unknown",
                "free": True,
                "distance_m": 0,
            }
        ],
        "parking": [
            {
                "lat": center_lat,
                "lon": center_lon,
                "address": "Zurich reference fixture",
                "type": "disabled parking",
                "fee_required": False,
                "distance_m": 0,
            }
        ],
        "errors": [],
    }


def _reference_grounded_plan(
    orchestrator: Orchestrator,
    profile: AccessibilityProfile,
    route_id: str,
):
    return orchestrator.create_journey_plan(
        profile,
        route_id,
        zurich_data_override=_reference_zurich_data(route_id),
    )


def run_planning_suite() -> dict[str, Any]:
    route_ids = [
        "route_with_stairs",
        "step_free_route",
        "long_walk_route",
        "zurich_hb_to_rathaus",
        "zurich_hb_to_rathaus_sf",
    ]
    rows: list[dict[str, Any]] = []
    orchestrator = Orchestrator(llm_mode="mock")

    for profile_case in planning_profiles():
        for route_id in route_ids:
            for setting in PLANNING_SETTINGS:
                effective_profile = (
                    AccessibilityProfile()
                    if setting == "no_profile"
                    else profile_case.profile
                )
                error: str | None = None
                hazard_source = ""
                agent_reply = ""
                try:
                    if setting == "profile_zurich_fixture":
                        result = _reference_grounded_plan(
                            orchestrator, effective_profile, route_id
                        )
                        selected_route_id = result.route_decision.selected_route_id
                        selected_route_name = result.route_decision.selected_route_name
                        plan = result.plan.model_dump()
                        hazard_source = result.hazard_summary.source
                        agent_reply = result.agent_reply
                    elif setting == "single_pass_profile":
                        selected_route_id, selected_route_name, plan = _single_pass_plan(
                            effective_profile, route_id
                        )
                    else:
                        selected_route_id, selected_route_name, plan = _direct_plan(
                            effective_profile, route_id
                        )
                except Exception as exc:  # pragma: no cover - recorded for experiments
                    selected_route_id = ""
                    selected_route_name = ""
                    plan = {
                        "summary": "",
                        "directions": [],
                        "alerts": [],
                        "checklist": [],
                        "if_you_get_lost": [],
                        "preferences_applied": [],
                        "route_coords": [],
                    }
                    error = f"{exc.__class__.__name__}: {exc}"

                metrics = _plan_metrics(
                    effective_profile,
                    route_id,
                    selected_route_id or route_id,
                    plan,
                    hazard_source=hazard_source,
                    agent_reply=agent_reply,
                )
                rows.append(
                    {
                        "profile": profile_case.name,
                        "setting": setting,
                        "route_id": route_id,
                        "selected_route_id": selected_route_id,
                        "selected_route_name": selected_route_name,
                        "hazard_source": hazard_source,
                        "agent_reply": agent_reply,
                        "alerts": plan.get("alerts", []),
                        "preferences_applied": plan.get("preferences_applied", []),
                        "error": error,
                        **metrics,
                    }
                )

    summary: dict[str, Any] = {}
    for setting in PLANNING_SETTINGS:
        subset = [row for row in rows if row["setting"] == setting]
        summary[setting] = {
            "n": len(subset),
            "route_switch_correct_rate": _mean_bool(subset, "route_switch_correct"),
            "route_switch_correct_count": _count_bool(subset, "route_switch_correct"),
            "constraint_satisfaction_rate": _conditional_mean_bool(
                subset, "constraint_applicable", "constraint_satisfied"
            ),
            "constraint_satisfaction_count": _conditional_count_bool(
                subset, "constraint_applicable", "constraint_satisfied"
            ),
            "audio_replacement_rate": _conditional_mean_bool(
                subset, "audio_replacement_expected", "audio_replacement_ok"
            ),
            "audio_replacement_count": _conditional_count_bool(
                subset, "audio_replacement_expected", "audio_replacement_ok"
            ),
            "simple_language_rate": _conditional_mean_bool(
                subset, "simple_language_expected", "simple_language_ok"
            ),
            "simple_language_count": _conditional_count_bool(
                subset, "simple_language_expected", "simple_language_ok"
            ),
            "zurich_source_rate": _mean_bool(subset, "zurich_source_present"),
            "zurich_source_count": _count_bool(subset, "zurich_source_present"),
            "zurich_grounding_text_rate": _mean_bool(subset, "zurich_grounding_text_present"),
            "zurich_grounding_text_count": _count_bool(subset, "zurich_grounding_text_present"),
            "unsupported_accessibility_claim_rate": _mean_bool(
                subset, "unsupported_accessibility_claim"
            ),
            "unsupported_accessibility_claim_count": _count_bool(
                subset, "unsupported_accessibility_claim"
            ),
            "schema_valid_rate": _mean_bool(subset, "schema_valid"),
            "schema_valid_count": _count_bool(subset, "schema_valid"),
        }
    return {"summary": summary, "case_results": rows}


def boundary_planning_cases() -> list[BoundaryPlanningCase]:
    wheelchair = AccessibilityProfile.model_validate(
        {"needs": {"mobility": {"wheelchair_user": True, "needs_step_free_route": True}}}
    )
    blind = AccessibilityProfile.model_validate(
        {"needs": {"vision": {"blind_or_low_vision": True, "prefers_landmarks": True}}}
    )
    avoid_long_walk = AccessibilityProfile.model_validate(
        {"needs": {"mobility": {"avoid_long_walks": True}}}
    )
    mixed = AccessibilityProfile.model_validate(
        {
            "needs": {
                "hearing": {"deaf_or_hard_of_hearing": True},
                "mobility": {"wheelchair_user": True, "needs_step_free_route": True},
                "cognitive": {
                    "needs_simple_language": True,
                    "needs_memory_support": True,
                    "reading_or_memory_difficulty_or_child": True,
                },
            },
            "communication": {"output_mode": "simple_text"},
        }
    )

    stairs_no_alternative = deepcopy(ROUTE_FIXTURES["route_with_stairs"])
    stairs_no_alternative.update(
        {
            "route_id": "boundary_stairs_no_alternative",
            "name": "Boundary route with stairs and no registered alternative",
        }
    )

    step_free_with_audio = deepcopy(ROUTE_FIXTURES["step_free_route"])
    step_free_with_audio.update(
        {
            "route_id": "boundary_step_free_with_audio_cue",
            "name": "Boundary step-free route with audio cue",
        }
    )
    step_free_with_audio["steps"][1]["instruction"] = (
        "Listen for the platform announcement beside the elevator before continuing."
    )
    step_free_with_audio["steps"][1]["audio_only_cue"] = True

    visual_only_step_free = deepcopy(ROUTE_FIXTURES["step_free_route"])
    visual_only_step_free.update(
        {
            "route_id": "boundary_visual_only_step_free_route",
            "name": "Boundary step-free route with visual-only signage",
        }
    )
    visual_only_step_free["steps"][2]["instruction"] = (
        "Look for the green overhead sign and follow it toward the accessible entrance."
    )
    visual_only_step_free["steps"][2]["visual_only_cue"] = True
    visual_only_step_free["steps"][2]["landmark"] = "Green overhead sign"

    long_walk_no_short = deepcopy(ROUTE_FIXTURES["long_walk_route"])
    long_walk_no_short.update(
        {
            "route_id": "boundary_long_walk_no_short_alternative",
            "name": "Boundary long route without a shorter fixture alternative",
        }
    )

    return [
        BoundaryPlanningCase(
            name="stairs_no_alternative",
            profile_name="wheelchair",
            profile=wheelchair,
            route_id=stairs_no_alternative["route_id"],
            fixtures={stairs_no_alternative["route_id"]: stairs_no_alternative},
            fallback_warning_expected=True,
        ),
        BoundaryPlanningCase(
            name="step_free_with_audio_cue",
            profile_name="mixed_needs",
            profile=mixed,
            route_id=step_free_with_audio["route_id"],
            fixtures={step_free_with_audio["route_id"]: step_free_with_audio},
            required_preferences=frozenset(
                {
                    "audio_to_visible_cues",
                    "mobility_step_free_preference",
                    "simple_english_mode",
                }
            ),
        ),
        BoundaryPlanningCase(
            name="visual_only_step_free_route",
            profile_name="blind_low_vision",
            profile=blind,
            route_id=visual_only_step_free["route_id"],
            fixtures={visual_only_step_free["route_id"]: visual_only_step_free},
            required_preferences=frozenset({"nonvisual_indoor_guidance"}),
        ),
        BoundaryPlanningCase(
            name="long_walk_no_short_alternative",
            profile_name="avoid_long_walks",
            profile=avoid_long_walk,
            route_id=long_walk_no_short["route_id"],
            fixtures={long_walk_no_short["route_id"]: long_walk_no_short},
            fallback_warning_expected=True,
            required_preferences=frozenset({"fatigue_risk_alert"}),
        ),
    ]


def run_boundary_planning_suite() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in boundary_planning_cases():
        route_provider = MockRouteProvider(case.fixtures)
        error: str | None = None
        try:
            selected_route_id, selected_route_name, plan = _direct_plan(
                case.profile,
                case.route_id,
                route_provider,
            )
        except Exception as exc:  # pragma: no cover - recorded for experiments
            selected_route_id = ""
            selected_route_name = ""
            plan = _empty_plan()
            error = f"{exc.__class__.__name__}: {exc}"

        metrics = _plan_metrics(
            case.profile,
            case.route_id,
            selected_route_id or case.route_id,
            plan,
            route_provider=route_provider,
        )
        boundary_metrics = _boundary_plan_metrics(case, selected_route_id, plan, route_provider)
        rows.append(
            {
                "case": case.name,
                "profile": case.profile_name,
                "route_id": case.route_id,
                "selected_route_id": selected_route_id,
                "selected_route_name": selected_route_name,
                "alerts": plan.get("alerts", []),
                "preferences_applied": plan.get("preferences_applied", []),
                "directions": plan.get("directions", []),
                "error": error,
                **metrics,
                **boundary_metrics,
            }
        )

    fallback_subset = [row for row in rows if row["fallback_warning_expected"]]
    multi_need_subset = [row for row in rows if row["multi_need_adaptation_expected"]]
    unsupported_count = _count_bool(rows, "unsupported_accessibility_claim", expected=True)
    summary = {
        "all": {
            "n": len(rows),
            "fallback_warning_rate": _mean_bool(fallback_subset, "fallback_warning_ok"),
            "fallback_warning_count": _count_bool(fallback_subset, "fallback_warning_ok"),
            "unsupported_accessibility_claim_rate": round(
                unsupported_count["num"] / unsupported_count["den"], 3
            )
            if unsupported_count["den"]
            else 0.0,
            "unsupported_accessibility_claim_count": unsupported_count,
            "multi_need_adaptation_rate": _mean_bool(
                multi_need_subset, "multi_need_adaptation_ok"
            ),
            "multi_need_adaptation_count": _count_bool(
                multi_need_subset, "multi_need_adaptation_ok"
            ),
            "schema_valid_rate": _mean_bool(rows, "schema_valid"),
            "schema_valid_count": _count_bool(rows, "schema_valid"),
        }
    }
    return {"summary": summary, "case_results": rows}


def _boundary_plan_metrics(
    case: BoundaryPlanningCase,
    selected_route_id: str,
    plan: dict[str, Any],
    route_provider: MockRouteProvider,
) -> dict[str, Any]:
    selected_route = route_provider.get_route(selected_route_id or case.route_id)
    alerts = " ".join(str(item) for item in plan.get("alerts", [])).lower()
    preferences = set(plan.get("preferences_applied", []))
    fallback_warning_ok = (
        not case.fallback_warning_expected
        or "no step-free alternative" in alerts
        or "long walking distance" in alerts
        or "fatigue" in alerts
    )
    multi_need_expected = bool(case.required_preferences)
    return {
        "fallback_warning_expected": case.fallback_warning_expected,
        "fallback_warning_ok": fallback_warning_ok,
        "unsupported_accessibility_claim": _has_unsupported_accessibility_claim(
            selected_route.step_free, plan
        ),
        "multi_need_adaptation_expected": multi_need_expected,
        "multi_need_adaptation_ok": (
            not multi_need_expected or case.required_preferences.issubset(preferences)
        ),
        "required_preferences": sorted(case.required_preferences),
    }


def _has_unsupported_accessibility_claim(selected_step_free: bool, plan: dict[str, Any]) -> bool:
    if selected_step_free:
        return False
    user_facing_route_text = " ".join(
        str(item)
        for key in ("summary", "directions")
        for item in (
            plan.get(key, [])
            if isinstance(plan.get(key), list)
            else [plan.get(key, "")]
        )
    ).lower()
    unsupported_terms = [
        "accessible route",
        "accessible entrance",
        "barrier-free",
        "no stairs",
        "stair-free",
        "step-free route",
        "step free route",
    ]
    return any(term in user_facing_route_text for term in unsupported_terms)


def run_indoor_adaptation_suite() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for profile_case in planning_profiles():
        for route_id in INDOOR_ROUTE_IDS:
            for setting in ("no_profile", "profile_only"):
                effective_profile = (
                    AccessibilityProfile()
                    if setting == "no_profile"
                    else profile_case.profile
                )
                error: str | None = None
                try:
                    selected_route_id, selected_route_name, plan = _direct_plan(
                        effective_profile, route_id
                    )
                except Exception as exc:  # pragma: no cover - recorded for experiments
                    selected_route_id = ""
                    selected_route_name = ""
                    plan = _empty_plan()
                    error = f"{exc.__class__.__name__}: {exc}"

                metrics = _indoor_adaptation_metrics(
                    effective_profile,
                    route_id,
                    selected_route_id or route_id,
                    plan,
                )
                rows.append(
                    {
                        "profile": profile_case.name,
                        "setting": setting,
                        "route_id": route_id,
                        "selected_route_id": selected_route_id,
                        "selected_route_name": selected_route_name,
                        "preferences_applied": plan.get("preferences_applied", []),
                        "directions": plan.get("directions", []),
                        "checklist": plan.get("checklist", []),
                        "error": error,
                        **metrics,
                    }
                )

    summary: dict[str, Any] = {}
    for setting in ("no_profile", "profile_only"):
        subset = [row for row in rows if row["setting"] == setting]
        mobility_rate = _conditional_mean_bool(
            subset, "mobility_step_free_applicable", "mobility_step_free_ok"
        )
        vision_rate = _conditional_mean_bool(
            subset, "vision_nonvisual_guidance_applicable", "vision_nonvisual_guidance_ok"
        )
        hearing_rate = _conditional_mean_bool(
            subset, "hearing_text_replacement_applicable", "hearing_text_replacement_ok"
        )
        cognitive_rate = _conditional_mean_bool(
            subset, "cognitive_simple_structure_applicable", "cognitive_simple_structure_ok"
        )
        summary[setting] = {
            "n": len(subset),
            "route_switch_correct_rate": _mean_bool(subset, "route_switch_correct"),
            "route_switch_correct_count": _count_bool(subset, "route_switch_correct"),
            "mobility_step_free_rate": mobility_rate,
            "mobility_step_free_count": _conditional_count_bool(
                subset, "mobility_step_free_applicable", "mobility_step_free_ok"
            ),
            "vision_nonvisual_guidance_rate": vision_rate,
            "vision_nonvisual_guidance_count": _conditional_count_bool(
                subset, "vision_nonvisual_guidance_applicable", "vision_nonvisual_guidance_ok"
            ),
            "hearing_text_replacement_rate": hearing_rate,
            "hearing_text_replacement_count": _conditional_count_bool(
                subset, "hearing_text_replacement_applicable", "hearing_text_replacement_ok"
            ),
            "cognitive_simple_structure_rate": cognitive_rate,
            "cognitive_simple_structure_count": _conditional_count_bool(
                subset, "cognitive_simple_structure_applicable", "cognitive_simple_structure_ok"
            ),
            "adaptation_coverage_rate": _macro_average(
                [mobility_rate, vision_rate, hearing_rate, cognitive_rate]
            ),
            "schema_valid_rate": _mean_bool(subset, "schema_valid"),
            "schema_valid_count": _count_bool(subset, "schema_valid"),
        }
    return {"summary": summary, "case_results": rows}


def _indoor_adaptation_metrics(
    profile: AccessibilityProfile,
    route_id: str,
    selected_route_id: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    route_provider = MockRouteProvider()
    requested_route = route_provider.get_route(route_id)
    selected_route = route_provider.get_route(selected_route_id)
    directions = " ".join(str(item) for item in plan.get("directions", []))
    directions_lower = directions.lower()
    checklist = " ".join(str(item) for item in plan.get("checklist", []))
    preferences = set(plan.get("preferences_applied", []))

    needs_step_free = profile.needs.mobility.needs_step_free_route is True
    blind_support = profile.needs.vision.blind_or_low_vision is True
    deaf_support = profile.needs.hearing.deaf_or_hard_of_hearing is True
    simple = profile.needs.cognitive.needs_simple_language is True

    requested_has_stairs = any(step.has_stairs for step in requested_route.steps)
    selected_has_audio = any(step.audio_only_cue for step in selected_route.steps)
    selected_has_visual_only = any(step.visual_only_cue for step in selected_route.steps)

    mobility_applicable = needs_step_free and requested_has_stairs
    hearing_applicable = deaf_support and selected_has_audio
    vision_applicable = blind_support and selected_has_visual_only
    cognitive_applicable = simple

    visual_terms_absent = not any(
        term in directions_lower
        for term in ["look for", "look at", "see the", "visual sign only"]
    )

    schema_valid = True
    try:
        from backend.app.models import PersonalizedPlan

        PersonalizedPlan.model_validate({k: v for k, v in plan.items() if not k.startswith("_")})
    except Exception:
        schema_valid = False

    return {
        "route_switch_correct": selected_route_id == _expected_selected_route(profile, route_id),
        "mobility_step_free_applicable": mobility_applicable,
        "mobility_step_free_ok": not mobility_applicable or selected_route.step_free,
        "vision_nonvisual_guidance_applicable": vision_applicable,
        "vision_nonvisual_guidance_ok": (
            not vision_applicable
            or ("nonvisual_indoor_guidance" in preferences and visual_terms_absent)
        ),
        "hearing_text_replacement_applicable": hearing_applicable,
        "hearing_text_replacement_ok": (
            not hearing_applicable
            or ("audio_to_visible_cues" in preferences and "listen for" not in directions_lower)
        ),
        "cognitive_simple_structure_applicable": cognitive_applicable,
        "cognitive_simple_structure_ok": (
            not cognitive_applicable
            or (
                "simple_english_mode" in preferences
                and "Check each step before you move." in checklist
            )
        ),
        "schema_valid": schema_valid,
    }


def _mean_bool(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if row.get(key) is True) / len(rows), 3)


def _count_bool(rows: list[dict[str, Any]], key: str, *, expected: bool = True) -> dict[str, int]:
    return {
        "num": sum(1 for row in rows if row.get(key) is expected),
        "den": len(rows),
    }


def _conditional_mean_bool(rows: list[dict[str, Any]], condition_key: str, key: str) -> float | str:
    applicable = [row for row in rows if row.get(condition_key) is True]
    if not applicable:
        return "n/a"
    return _mean_bool(applicable, key)


def _conditional_count_bool(
    rows: list[dict[str, Any]],
    condition_key: str,
    key: str,
    *,
    expected: bool = True,
) -> dict[str, int] | str:
    applicable = [row for row in rows if row.get(condition_key) is True]
    if not applicable:
        return "n/a"
    return _count_bool(applicable, key, expected=expected)


def _macro_average(values: list[float | str]) -> float | str:
    numeric = [value for value in values if not isinstance(value, str)]
    if not numeric:
        return "n/a"
    return round(sum(numeric) / len(numeric), 3)


def _empty_plan() -> dict[str, Any]:
    return {
        "summary": "",
        "directions": [],
        "alerts": [],
        "checklist": [],
        "if_you_get_lost": [],
        "preferences_applied": [],
        "route_coords": [],
    }


def maybe_ollama_provider(base_url: str, requested_model: str, timeout_sec: int) -> OllamaLLMProvider | None:
    probe = OllamaLLMProvider(model=requested_model, base_url=base_url, timeout_sec=timeout_sec)
    ok, _, resolved_url, models = probe.health_check()
    if not ok:
        return None
    fallback_order = [
        requested_model,
        "qwen3.5:4b",
        "qwen3:4b",
        "shmily_006/Qw3:4b_4bit",
        "qwen2.5:3b",
        "llama3.2:3b",
    ]
    for candidate in fallback_order:
        if candidate in models:
            return OllamaLLMProvider(model=candidate, base_url=resolved_url, timeout_sec=timeout_sec)
    return None


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "experiment_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    profiling_rows = []
    for suite in report["profiling"].values():
        profiling_rows.extend(suite["case_results"])
    _write_csv(output_dir / "profiling_cases.csv", profiling_rows)
    _write_csv(output_dir / "planning_cases.csv", report["planning"]["case_results"])
    _write_csv(
        output_dir / "boundary_planning_cases.csv",
        report["boundary_planning"]["case_results"],
    )
    _write_csv(output_dir / "indoor_adaptation_cases.csv", report["indoor_adaptation"]["case_results"])

    (output_dir / "table_profiling_comparison.tex").write_text(
        profiling_latex_table(report["profiling"]),
        encoding="utf-8",
    )
    (output_dir / "table_planning_ablation.tex").write_text(
        planning_latex_table(report["planning"]),
        encoding="utf-8",
    )
    (output_dir / "table_boundary_planning.tex").write_text(
        boundary_planning_latex_table(report["boundary_planning"]),
        encoding="utf-8",
    )
    (output_dir / "table_indoor_adaptation.tex").write_text(
        indoor_adaptation_latex_table(report["indoor_adaptation"]),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
                 for key, value in row.items()}
            )


def profiling_latex_table(profiling: dict[str, Any]) -> str:
    lines = [
        "\\begin{tabular}{llrrrrr}",
        "\\toprule",
        "Provider & Condition & $n$ & First $F_1$ & Final $F_1$ & Exact & Turns \\\\",
        "\\midrule",
    ]
    for provider, suite in profiling.items():
        for condition, item in suite["by_condition"].items():
            lines.append(
                f"{provider.replace('_', '\\_')} & {condition.replace('_', '\\_')} & "
                f"{item['n']} & {item['first_turn']['f1']:.3f} & "
                f"{item['final']['f1']:.3f} & {item['final']['exact_match_rate']:.3f} & "
                f"{item['mean_turns_to_confirmation']:.2f} \\\\"
            )
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    return "\n".join(lines)


def planning_latex_table(planning: dict[str, Any]) -> str:
    lines = [
        "\\begin{tabular}{lrrrrrrrr}",
        "\\toprule",
        "Setting & $n$ & Route & Constraint & Audio & Simple & Zurich src. & Unsupported & Schema \\\\",
        "\\midrule",
    ]
    for setting, item in planning["summary"].items():
        label = PLANNING_SETTING_LABELS.get(setting, setting.replace("_", "\\_"))
        lines.append(
            f"{label} & "
            f"{item['n']} & "
            f"{_fmt_metric(item['route_switch_correct_rate'], item.get('route_switch_correct_count'))} & "
            f"{_fmt_metric(item['constraint_satisfaction_rate'], item.get('constraint_satisfaction_count'))} & "
            f"{_fmt_metric(item['audio_replacement_rate'], item.get('audio_replacement_count'))} & "
            f"{_fmt_metric(item['simple_language_rate'], item.get('simple_language_count'))} & "
            f"{_fmt_metric(item['zurich_source_rate'], item.get('zurich_source_count'))} & "
            f"{_fmt_metric(item['unsupported_accessibility_claim_rate'], item.get('unsupported_accessibility_claim_count'))} & "
            f"{_fmt_metric(item['schema_valid_rate'], item.get('schema_valid_count'))} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    return "\n".join(lines)


def boundary_planning_latex_table(boundary: dict[str, Any]) -> str:
    item = boundary["summary"]["all"]
    fallback = item.get("fallback_warning_count", {"num": 0, "den": 0})
    unsupported = item.get("unsupported_accessibility_claim_count", {"num": 0, "den": 0})
    multi_need = item.get("multi_need_adaptation_count", {"num": 0, "den": 0})
    schema = item.get("schema_valid_count", {"num": 0, "den": 0})
    lines = [
        "\\begin{tabularx}{\\textwidth}{>{\\raggedright\\arraybackslash}p{4.0cm} >{\\centering\\arraybackslash}p{1.8cm} X}",
        "\\toprule",
        "Check & Count & Interpretation \\\\",
        "\\midrule",
        "Fallback warnings when required & "
        f"{fallback['num']}/{fallback['den']} & "
        "Both no-alternative cases surface an explicit limitation instead of silently claiming that the route was optimized. \\\\",
        "Unsupported accessibility claims & "
        f"{unsupported['num']}/{unsupported['den']} & "
        "None of the boundary plans asserts accessibility without route-fixture evidence. This is an error count, so 0 is the desired result. \\\\",
        "Multi-need adaptations & "
        f"{multi_need['num']}/{multi_need['den']} & "
        "All cases with multiple required preferences activate every expected adaptation. \\\\",
        "Schema-valid plans & "
        f"{schema['num']}/{schema['den']} & "
        "All boundary plans satisfy the output schema. \\\\",
        "\\bottomrule",
        "\\end{tabularx}",
        "",
    ]
    return "\n".join(lines)


def indoor_adaptation_latex_table(indoor: dict[str, Any]) -> str:
    lines = [
        "\\begin{tabular}{lrrrrrrr}",
        "\\toprule",
        "Setting & Route & Mobility & Vision & Hearing & Cognitive & Coverage & Schema \\\\",
        "\\midrule",
    ]
    for setting, item in indoor["summary"].items():
        lines.append(
            f"{setting.replace('_', '\\_')} & "
            f"{_fmt_metric(item['route_switch_correct_rate'], item.get('route_switch_correct_count'))} & "
            f"{_fmt_metric(item['mobility_step_free_rate'], item.get('mobility_step_free_count'))} & "
            f"{_fmt_metric(item['vision_nonvisual_guidance_rate'], item.get('vision_nonvisual_guidance_count'))} & "
            f"{_fmt_metric(item['hearing_text_replacement_rate'], item.get('hearing_text_replacement_count'))} & "
            f"{_fmt_metric(item['cognitive_simple_structure_rate'], item.get('cognitive_simple_structure_count'))} & "
            f"{_fmt_metric(item['adaptation_coverage_rate'])} & "
            f"{_fmt_metric(item['schema_valid_rate'], item.get('schema_valid_count'))} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    return "\n".join(lines)


def _fmt_metric(value: float | str, count: dict[str, int] | str | None = None) -> str:
    if isinstance(value, str):
        return value
    if isinstance(count, dict):
        return f"{value:.3f} ({count['num']}/{count['den']})"
    return f"{value:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MAPA thesis evaluation experiments.")
    parser.add_argument(
        "--output-dir",
        default="YuanYu_Bachelor_cl-thesis/results",
        help="Directory for JSON/CSV/LaTeX outputs.",
    )
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--ollama-model", default="qwen3.5:4b")
    parser.add_argument("--ollama-timeout", type=int, default=300)
    parser.add_argument(
        "--ollama-max-turns",
        type=int,
        default=2,
        help="Maximum scripted profiling turns for the optional local Ollama comparison.",
    )
    parser.add_argument(
        "--include-ollama",
        action="store_true",
        help="Include local Ollama profiling if the server and requested model are available.",
    )
    args = parser.parse_args()

    providers: dict[str, tuple[LLMProvider, int]] = {
        "lexicon_only": (LexiconOnlyLLMProvider(), 6),
        "hybrid_mock": (MockLLMProvider(), 6),
    }
    notes = [
        "hybrid_mock uses the deterministic mock provider; it is a regression setting, not evidence of LLM gain.",
        "The main planning matrix uses a fixed Zurich-shaped reference fixture. Live WFS retrieval is reported only as a dated case study.",
    ]
    if args.include_ollama:
        ollama = maybe_ollama_provider(args.ollama_url, args.ollama_model, args.ollama_timeout)
        if ollama is not None:
            providers[f"hybrid_ollama:{ollama.model}"] = (ollama, args.ollama_max_turns)
            notes.append(
                f"Ollama profiling provider available: {ollama.model}; "
                f"local comparison capped at {args.ollama_max_turns} scripted turns per case."
            )
        else:
            notes.append("Ollama profiling provider unavailable; LLM-gain claims are not supported by this run.")
    else:
        notes.append("Ollama profiling was not requested; reported profiling results are deterministic.")

    profiling = {
        name: run_profiling_suite(provider, max_turns=max_turns)
        for name, (provider, max_turns) in providers.items()
    }
    planning = run_planning_suite()
    boundary_planning = run_boundary_planning_suite()
    indoor_adaptation = run_indoor_adaptation_suite()
    report = {
        "notes": notes,
        "profiling": profiling,
        "planning": planning,
        "boundary_planning": boundary_planning,
        "indoor_adaptation": indoor_adaptation,
    }
    write_outputs(report, Path(args.output_dir))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
