"""Dialogue Orchestrator: owns session state and routes turns to subagents.

The orchestrator is the Phase 2 top-level agent. Responsibilities:

- Hold a ``SessionState`` for one user session (profile patch, skipped
  domains, last question context, language, conversation history).
- On every user turn, call the ``ProfilerAgent`` (which in turn uses the
  ``NeedsExtractor`` subagent) to produce an updated patch, confirmation
  text, and next question.
- Decide when the profile is "done enough" so the UI can offer the plan
  generation button.
- Expose ``create_plan`` to call the ``PlannerAgent`` once a profile exists.

It deliberately owns no LLM prompt itself — prompts belong to the subagent
that talks to the LLM (``NeedsExtractor`` for profiling, ``PlannerAgent``
for plans). This keeps subagents swappable and the orchestrator focused on
flow control.

Not in scope for Phase 2 (see plan file):
- ValidatorAgent post-processing (Phase 4).
- Cross-session memory / preference learning (Phase 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.models import (
    AccessibilityProfile,
    ImageHazardsSummary,
    PersonalizedPlan,
    ProfilerAgentOutput,
)
from backend.app.providers.image_provider import ImageProvider
from backend.app.services.needs_extractor import NeedsExtractor
from backend.app.services.planner_agent import PlannerAgent
from backend.app.services.profiler_agent import ProfilerAgent


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class ConversationTurn:
    role: str  # "user" | "assistant"
    text: str


@dataclass
class SessionState:
    """All mutable state for one profiling session.

    Lives inside the orchestrator. The Streamlit layer reads from here for
    display only — it does not mutate these fields directly anymore.
    """

    profile_patch: dict[str, Any] = field(default_factory=dict)
    skipped_domains: list[str] = field(default_factory=list)
    last_question_context: str | None = "vision"  # first turn asks about vision
    language: str = "en"
    consent_to_profile: bool = True  # caller (Streamlit) gates this up front
    history: list[ConversationTurn] = field(default_factory=list)

    def reset(self, language: str = "en") -> None:
        self.profile_patch = {}
        self.skipped_domains = []
        self.last_question_context = "vision"
        self.language = language
        self.consent_to_profile = True
        self.history = []


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorTurnOutput:
    """Return value of ``handle_turn``.

    Mirrors ``ProfilerAgentOutput`` but adds orchestrator-level signals the
    UI needs to decide what to render next.
    """

    confirmation_text: str
    next_question: str | None
    next_question_context: str | None
    profile_patch: dict[str, Any]
    can_generate_plan: bool
    profiler_output: ProfilerAgentOutput  # full object for callers that want it


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """Dialogue manager composing the profiler + extractor + planner subagents."""

    # Confidence floor above which the UI may offer plan generation. Matches
    # the current frontend check ("any profile patch is enough") but adds a
    # small guard: don't offer plan on an empty patch.
    PLAN_CONFIDENCE_FLOOR = 0.25

    def __init__(
        self,
        profiler: ProfilerAgent,
        needs_extractor: NeedsExtractor | None = None,
        planner: PlannerAgent | None = None,
        image_provider: ImageProvider | None = None,
    ) -> None:
        self.profiler = profiler
        # Use the extractor the profiler already holds if caller did not pass
        # one explicitly. Keeps a single extractor instance per session.
        self.needs_extractor = needs_extractor or profiler.needs_extractor
        self.planner = planner
        self.image_provider = image_provider
        self.state = SessionState()

    # ------------------------------------------------------------------
    # Per-turn handling
    # ------------------------------------------------------------------

    def handle_turn(
        self,
        user_message: str,
        response_language: str | None = None,
    ) -> OrchestratorTurnOutput:
        """Process one user message and advance session state.

        Steps:
        1. Record the user turn in history.
        2. Track ``skip`` as a domain-level skip so the next-question logic
           can move past it.
        3. Delegate to ``ProfilerAgent.process_turn`` (which uses the
           ``NeedsExtractor`` internally and also applies the context yes/no
           overlay).
        4. Update session state from the profiler output.
        5. Record the assistant turn in history.
        """
        language = response_language or self.state.language
        self.state.language = language
        self.state.history.append(ConversationTurn(role="user", text=user_message))

        # Pre-profiler: if the user typed "skip" to the focused question, mark
        # that domain as skipped so we don't re-ask. Mirrors the frontend logic.
        if self.state.last_question_context:
            classified = self.profiler._classify_short_answer(user_message)
            if classified == "skip":
                domain = _context_to_domain(self.state.last_question_context)
                if domain and domain not in self.state.skipped_domains:
                    self.state.skipped_domains.append(domain)

        profiler_output = self.profiler.process_turn(
            user_message=user_message,
            current_patch=self.state.profile_patch,
            skipped_domains=self.state.skipped_domains,
            question_context=self.state.last_question_context,
            response_language=language,
        )

        # Persist new patch + advance dialogue cursor.
        self.state.profile_patch = profiler_output.profile_patch.model_dump()
        self.state.last_question_context = profiler_output.next_question_context

        # Plan-ready gate: either no more questions to ask, or confidence is
        # high enough AND the patch is non-empty.
        overall_confidence = profiler_output.confidence.overall
        patch_has_content = bool(profiler_output.profile_patch.needs.model_dump(exclude_none=True))
        can_generate_plan = patch_has_content and (
            profiler_output.next_question is None
            or overall_confidence >= self.PLAN_CONFIDENCE_FLOOR
        )

        assistant_text = profiler_output.confirmation_text
        if profiler_output.next_question:
            assistant_text = f"{assistant_text}\n\n{profiler_output.next_question}"
        self.state.history.append(ConversationTurn(role="assistant", text=assistant_text))

        return OrchestratorTurnOutput(
            confirmation_text=profiler_output.confirmation_text,
            next_question=profiler_output.next_question,
            next_question_context=profiler_output.next_question_context,
            profile_patch=self.state.profile_patch,
            can_generate_plan=can_generate_plan,
            profiler_output=profiler_output,
        )

    # ------------------------------------------------------------------
    # Profile / plan builders
    # ------------------------------------------------------------------

    def build_profile(self) -> AccessibilityProfile:
        return self.profiler.build_profile(
            self.state.profile_patch,
            consent_to_profile=self.state.consent_to_profile,
            skipped_domains=self.state.skipped_domains,
        )

    def create_plan(
        self,
        route_id: str,
        image_bytes: bytes | None = None,
        image_hazards: ImageHazardsSummary | dict[str, Any] | None = None,
    ) -> PersonalizedPlan:
        if self.planner is None:
            raise RuntimeError(
                "Orchestrator has no planner attached; pass ``planner=`` at construction."
            )
        hazards = image_hazards
        if hazards is None and image_bytes is not None and self.image_provider is not None:
            hazards = self.image_provider.summarize_hazards(image_bytes)

        profile = self.build_profile()
        return self.planner.create_plan(
            profile=profile,
            route_id=route_id,
            image_hazards=hazards,
            response_language=self.state.language,
        )

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------

    def reset(self, language: str = "en") -> None:
        self.state.reset(language=language)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _context_to_domain(question_context: str) -> str | None:
    """Map a ``_QUESTION_TEXTS`` key onto a top-level domain name.

    Mirrors ``frontend/app.py::context_to_domain`` so orchestrator-owned skip
    tracking matches the legacy frontend-owned behavior.
    """
    if question_context in {"vision"}:
        return "vision"
    if question_context in {"hearing", "hearing_sign"}:
        return "hearing"
    if question_context in {"mobility"}:
        return "mobility"
    if question_context in {"cognitive"}:
        return "cognitive"
    return None
