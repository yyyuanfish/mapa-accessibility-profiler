from __future__ import annotations

from dataclasses import dataclass

from backend.app.providers.llm_provider import MockLLMProvider
from backend.app.providers.route_provider import MockRouteProvider
from backend.app.services.multi_agent_orchestrator import JourneyOrchestrator
from backend.app.services.planner_agent import PlannerAgent
from backend.app.services.profiler_agent import ProfilerAgent


@dataclass
class PersonaCase:
    name: str
    utterances: list[str]
    expected_positive_labels: set[str]


PERSONAS: list[PersonaCase] = [
    PersonaCase(
        name="blind_persona",
        utterances=[
            "I am blind and I use a screen reader.",
            "No hearing support needed.",
            "No wheelchair needs.",
            "Standard language is fine.",
        ],
        expected_positive_labels={"blind_or_low_vision"},
    ),
    PersonaCase(
        name="deaf_sign_persona",
        utterances=[
            "I am deaf and I use sign language.",
            "No vision support needed.",
            "No mobility support needed.",
        ],
        expected_positive_labels={"deaf_or_hard_of_hearing", "sign_language_user"},
    ),
    PersonaCase(
        name="wheelchair_persona",
        utterances=[
            "I use a wheelchair and need step free routes.",
            "No vision support needed.",
            "No hearing support needed.",
        ],
        expected_positive_labels={"wheelchair_user", "needs_step_free_route"},
    ),
    PersonaCase(
        name="memory_child_persona",
        utterances=[
            "Please use simple english and short steps.",
            "I forget directions easily and need reminders.",
            "No vision or hearing support needed.",
        ],
        expected_positive_labels={"needs_simple_language", "needs_memory_support"},
    ),
    PersonaCase(
        name="mixed_needs_persona",
        utterances=[
            "I am hard of hearing and also use a wheelchair.",
            "Please avoid stairs and use simple english.",
            "I may need memory reminders.",
        ],
        expected_positive_labels={
            "deaf_or_hard_of_hearing",
            "wheelchair_user",
            "needs_step_free_route",
            "needs_simple_language",
            "needs_memory_support",
        },
    ),
    # Regression case for the natural-language multi-needs bug:
    # a single free-form utterance that mixes three domains with colloquial
    # phrasing ("eye problem", "walk badly", "complex text"). Before the
    # Phase 1 fix this utterance produced an empty patch.
    PersonaCase(
        name="free_form_multi_needs_persona",
        utterances=[
            "yes I have eye problem, also I walk badly, and I can't read complex text",
            "No hearing support needed.",
        ],
        expected_positive_labels={
            "blind_or_low_vision",
            "needs_step_free_route",
            "needs_simple_language",
        },
    ),
]


class EvaluationHarness:
    def __init__(self) -> None:
        llm_provider = MockLLMProvider()
        route_provider = MockRouteProvider()
        profiler = ProfilerAgent(llm_provider=llm_provider)
        planner = PlannerAgent(llm_provider=llm_provider, route_provider=route_provider)
        self.orchestrator = JourneyOrchestrator(
            profiler_agent=profiler,
            planner_agent=planner,
            route_provider=route_provider,
        )

    def run(self) -> dict:
        results = []
        total_tp = total_fp = total_fn = 0

        for persona in PERSONAS:
            patch: dict = {}
            skipped: list[str] = []
            for turn_count, utterance in enumerate(persona.utterances, start=1):
                output = self.orchestrator.process_profile_turn(
                    user_message=utterance,
                    current_patch=patch,
                    skipped_domains=skipped,
                    turn_count=turn_count,
                )
                patch = output.profiler_output.profile_patch.model_dump()

            profile = self.orchestrator.build_profile(patch)
            predicted = self._positive_labels(profile.model_dump())
            expected = persona.expected_positive_labels
            tp = len(predicted & expected)
            fp = len(predicted - expected)
            fn = len(expected - predicted)
            precision = tp / (tp + fp) if (tp + fp) else 0.0
            recall = tp / (tp + fn) if (tp + fn) else 0.0

            total_tp += tp
            total_fp += fp
            total_fn += fn

            results.append(
                {
                    "persona": persona.name,
                    "expected": sorted(expected),
                    "predicted": sorted(predicted),
                    "precision": round(precision, 3),
                    "recall": round(recall, 3),
                }
            )

        aggregate_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
        aggregate_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0

        return {
            "persona_results": results,
            "aggregate": {
                "precision": round(aggregate_precision, 3),
                "recall": round(aggregate_recall, 3),
            },
        }

    @staticmethod
    def _positive_labels(profile: dict) -> set[str]:
        labels: set[str] = set()
        needs = profile.get("needs", {})

        if needs.get("vision", {}).get("blind_or_low_vision") is True:
            labels.add("blind_or_low_vision")

        hearing = needs.get("hearing", {})
        if hearing.get("deaf_or_hard_of_hearing") is True:
            labels.add("deaf_or_hard_of_hearing")
        if hearing.get("sign_language_user") is True:
            labels.add("sign_language_user")

        mobility = needs.get("mobility", {})
        if mobility.get("wheelchair_user") is True:
            labels.add("wheelchair_user")
        if mobility.get("needs_step_free_route") is True:
            labels.add("needs_step_free_route")

        cognitive = needs.get("cognitive", {})
        if cognitive.get("needs_simple_language") is True:
            labels.add("needs_simple_language")
        if cognitive.get("needs_memory_support") is True:
            labels.add("needs_memory_support")

        return labels
