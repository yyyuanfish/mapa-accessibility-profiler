"""Application orchestrator — delegates to LangGraph workflows.

This is the single top-level orchestrator used by the API and evaluation
paths. It exposes profiling, planning, and speech I/O entry points while
delegating the actual workflow execution to the compiled LangGraph graphs.
"""
from __future__ import annotations

from typing import Any

from backend.app.agents.planning_graph import run_planning
from backend.app.agents.profile_graph import run_profile_turn
from backend.app.models import (
    AccessibilityProfile,
    AgentTrace,
    AgentTraceStep,
    HazardFusionSummary,
    ImageHazardsSummary,
    MultiAgentPlanResult,
    MultiAgentProfileResult,
    PersonalizedPlan,
    ProfilerAgentOutput,
    RouteSelectionDecision,
    SpeechTranscription,
)
from backend.app.providers.llm_provider import LLMProvider, MockLLMProvider
from backend.app.providers.route_provider import RouteProvider
from backend.app.providers.speech_provider import (
    FasterWhisperSpeechProvider,
    MockSpeechProvider,
    SpeechProvider,
)


class Orchestrator:
    """Facade over the LangGraph profiling and planning pipelines."""

    def __init__(
        self,
        profiler_agent=None,  # kept for compatibility; not used internally
        planner_agent=None,   # kept for compatibility; not used internally
        route_provider: RouteProvider | None = None,
        llm_provider: LLMProvider | None = None,
        *,
        llm_mode: str = "mock",
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "qwen3.5:4b",
        ollama_timeout: int = 300,
        ollama_profiler_model: str = "",
        ollama_planner_model: str = "",
        ollama_image_model: str = "",
        speech_provider: SpeechProvider | None = None,
        speech_mode: str = "mock",
        speech_model: str = "small",
        speech_device: str = "auto",
        speech_compute_type: str = "int8",
    ) -> None:
        self._llm_mode = llm_mode
        self._ollama_url = ollama_url
        self._ollama_model = ollama_model
        self._ollama_timeout = ollama_timeout
        self._ollama_profiler_model = ollama_profiler_model or ollama_model
        self._ollama_planner_model = ollama_planner_model or ollama_model
        self._ollama_image_model = ollama_image_model or ollama_model
        self._speech_provider = speech_provider or self._build_speech_provider(
            speech_mode=speech_mode,
            speech_model=speech_model,
            speech_device=speech_device,
            speech_compute_type=speech_compute_type,
        )
        # Reserved for future route provider injection; currently the graph owns
        # route provider construction internally.
        self._route_provider = route_provider
        self._llm_provider = llm_provider
        self._profiler_agent = profiler_agent
        self._planner_agent = planner_agent

    def process_profile_turn(
        self,
        user_message: str,
        current_patch: dict[str, Any] | None = None,
        skipped_domains: list[str] | None = None,
        question_context: str | None = None,
        response_language: str = "en",
        consent_to_profile: bool = True,
        turn_count: int = 1,
    ) -> MultiAgentProfileResult:
        state = run_profile_turn({
            "user_message": user_message,
            "current_patch": current_patch,
            "skipped_domains": skipped_domains or [],
            "question_context": question_context,
            "turn_count": turn_count,
            "language": response_language,
            "consent_to_profile": consent_to_profile,
            "llm_mode": self._llm_mode,
            "ollama_url": self._ollama_url,
            "ollama_model": self._ollama_model,
            "ollama_timeout": self._ollama_timeout,
            "ollama_profiler_model": self._ollama_profiler_model,
            "ollama_planner_model": self._ollama_planner_model,
            "ollama_image_model": self._ollama_image_model,
            "consent_granted": False,
            "trace_steps": [],
            "error": None,
        })

        if state.get("error"):
            raise ValueError(state["error"])

        profiler_output_dict = state.get("profiler_output") or {}
        draft_dict = state.get("draft_profile") or {}

        profiler_output = ProfilerAgentOutput.model_validate({
            "profile_patch": profiler_output_dict.get("profile_patch", {}),
            "confidence": profiler_output_dict.get("confidence", {}),
            "missing_critical_fields": profiler_output_dict.get("missing_critical_fields", []),
            "next_question": profiler_output_dict.get("next_question"),
            "next_question_context": profiler_output_dict.get("next_question_context"),
            "confirmation_text": profiler_output_dict.get("confirmation_text", ""),
        })
        draft_profile = AccessibilityProfile.model_validate(draft_dict)

        trace = self._build_agent_trace("profile_workflow", state.get("trace_steps", []))
        agent_reply = state.get("agent_reply", "")

        return MultiAgentProfileResult(
            profiler_output=profiler_output,
            draft_profile=draft_profile,
            trace=trace,
            agent_reply=agent_reply,
        )

    def build_profile(
        self,
        profile_patch: dict[str, Any],
        consent_to_profile: bool = True,
        skipped_domains: list[str] | None = None,
    ) -> AccessibilityProfile:
        from backend.app.services.profiler_agent import ProfilerAgent

        agent = ProfilerAgent(llm_provider=MockLLMProvider())
        return agent.build_profile(
            profile_patch=profile_patch,
            consent_to_profile=consent_to_profile,
            skipped_domains=skipped_domains,
        )

    def create_journey_plan(
        self,
        profile: AccessibilityProfile | dict[str, Any],
        route_id: str,
        image_hazards: ImageHazardsSummary | dict[str, Any] | None = None,
        response_language: str = "en",
        zurich_data_override: dict[str, Any] | None = None,
    ) -> MultiAgentPlanResult:
        profile_dict = profile.model_dump() if isinstance(profile, AccessibilityProfile) else profile
        hazard_dict: dict[str, Any] | None = None
        if image_hazards is not None:
            hazard_dict = (
                image_hazards.model_dump()
                if isinstance(image_hazards, ImageHazardsSummary)
                else image_hazards
            )

        state = run_planning({
            "profile": profile_dict,
            "route_id": route_id,
            "language": response_language,
            "image_hazards": hazard_dict,
            "zurich_data_override": zurich_data_override,
            "llm_mode": self._llm_mode,
            "ollama_url": self._ollama_url,
            "ollama_model": self._ollama_model,
            "ollama_timeout": self._ollama_timeout,
            "ollama_profiler_model": self._ollama_profiler_model,
            "ollama_planner_model": self._ollama_planner_model,
            "ollama_image_model": self._ollama_image_model,
            "is_valid": False,
            "validation_error": None,
            "trace_steps": [],
            "error": None,
        })

        if state.get("error"):
            raise ValueError(state["error"])

        plan = PersonalizedPlan.model_validate(state.get("plan") or {})

        selected_route_dict = state.get("selected_route") or {}
        route_decision = RouteSelectionDecision(
            requested_route_id=route_id,
            requested_route_name=selected_route_dict.get("name", route_id),
            selected_route_id=selected_route_dict.get("route_id", route_id),
            selected_route_name=selected_route_dict.get("name", route_id),
            switched_to_step_free=selected_route_dict.get("route_id", route_id) != route_id,
            reasons=state.get("route_preferences") or [],
            alerts=state.get("route_alerts") or [],
        )

        fused = state.get("fused_hazards") or {}
        hazard_summary = HazardFusionSummary(
            source=fused.get("source", "route_metadata_only"),
            highlights=fused.get("highlights", []),
        )

        trace = self._build_agent_trace("planning_workflow", state.get("trace_steps", []))
        agent_reply = state.get("agent_reply", "")

        return MultiAgentPlanResult(
            route_decision=route_decision,
            hazard_summary=hazard_summary,
            plan=plan,
            trace=trace,
            agent_reply=agent_reply,
        )

    def format_plan(self, plan: Any, language: str = "en") -> str:
        from backend.app.providers.route_provider import MockRouteProvider
        from backend.app.services.planner_agent import PlannerAgent

        agent = PlannerAgent(llm_provider=MockLLMProvider(), route_provider=MockRouteProvider())
        return agent.format_plan(plan, language=language)

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str | None = None,
        response_language: str = "en",
    ) -> SpeechTranscription:
        return self._speech_provider.transcribe(
            audio_bytes,
            mime_type=mime_type,
            language=response_language,
        )

    def prepare_spoken_text(self, text: str, *, response_language: str = "en") -> str:
        return self._speech_provider.prepare_output_text(
            text,
            language=response_language,
        )

    @staticmethod
    def _build_speech_provider(
        *,
        speech_mode: str,
        speech_model: str,
        speech_device: str,
        speech_compute_type: str,
    ) -> SpeechProvider:
        if speech_mode == "faster-whisper":
            return FasterWhisperSpeechProvider(
                model_size=speech_model,
                device=speech_device,
                compute_type=speech_compute_type,
            )
        return MockSpeechProvider()

    @staticmethod
    def _build_agent_trace(workflow: str, trace_steps: list[dict[str, Any]]) -> AgentTrace:
        steps = [
            AgentTraceStep(
                agent_name=s.get("agent_name", "unknown"),
                role=s.get("role", ""),
                summary=s.get("summary", ""),
                input_keys=s.get("input_keys", []),
                output_keys=s.get("output_keys", []),
                key_findings=s.get("key_findings", []),
            )
            for s in trace_steps
        ]
        return AgentTrace(workflow=workflow, steps=steps)
