"""LangGraph TypedDict state definitions for both pipelines.

All values are primitives or plain dicts — no Pydantic models — so LangGraph
can merge partial updates from parallel nodes without conflict.

For PlannerState, trace_steps uses Annotated[list, operator.add] so that
parallel nodes (route_reasoner_node and image_hazard_node) can each append
their own step and LangGraph merges both lists automatically.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, NotRequired, TypedDict


class ProfilerState(TypedDict):
    # ── Inputs ────────────────────────────────────────────────────────────────
    user_message: str
    current_patch: dict[str, Any] | None
    skipped_domains: list[str]
    question_context: str | None
    turn_count: int
    language: str
    consent_to_profile: bool

    # LLM config (carried through state so each node can build its own provider)
    llm_mode: str           # "mock" | "ollama"
    ollama_url: str
    ollama_model: str       # legacy single-model fallback
    ollama_timeout: int

    # Per-agent model overrides (if empty, fall back to ollama_model)
    ollama_profiler_model: str   # e.g. "qwen3.5:4b"
    ollama_planner_model: str    # e.g. "llama3.1:8b"
    ollama_image_model: str      # e.g. "llava:7b"

    # ── Node outputs ──────────────────────────────────────────────────────────
    consent_granted: bool                    # consent_guard_node
    profiler_output: NotRequired[dict[str, Any] | None]   # profiler_node
    draft_profile: NotRequired[dict[str, Any] | None]     # profile_manager_node
    agent_reply: NotRequired[str]            # conversation_orchestrator_node

    # ── Observability ─────────────────────────────────────────────────────────
    trace_steps: list[dict[str, Any]]

    # ── Error ─────────────────────────────────────────────────────────────────
    error: str | None


class PlannerState(TypedDict):
    # ── Inputs ────────────────────────────────────────────────────────────────
    profile: dict[str, Any]             # AccessibilityProfile as dict
    route_id: str
    language: str
    image_hazards: dict[str, Any] | None  # pre-analysed ImageHazardsSummary or None
    zurich_data_override: NotRequired[dict[str, Any] | None]  # deterministic evaluation input

    # LLM config
    llm_mode: str
    ollama_url: str
    ollama_model: str
    ollama_timeout: int

    # ── Node outputs ──────────────────────────────────────────────────────────
    is_valid: bool                                      # input_validator_node
    validation_error: str | None                        # input_validator_node

    # Parallel nodes — each returns ONLY its own keys so LangGraph can merge
    selected_route: NotRequired[dict[str, Any] | None]  # route_reasoner_node
    route_preferences: NotRequired[list[str]]           # route_reasoner_node
    route_alerts: NotRequired[list[str]]                # route_reasoner_node

    image_hazard_summary: NotRequired[dict[str, Any] | None]  # image_hazard_node

    fused_hazards: NotRequired[dict[str, Any] | None]   # hazard_fusion_node
    plan: NotRequired[dict[str, Any] | None]            # planner_node
    agent_reply: NotRequired[str]                       # synthesis_node

    # ── Zurich Open Data (fetched once before parallel fan-out) ───────────────
    zurich_barriers: NotRequired[list[dict[str, Any]] | None]  # zurich_data_fetcher_node
    zurich_toilets:  NotRequired[list[dict[str, Any]] | None]  # zurich_data_fetcher_node
    zurich_parking:  NotRequired[list[dict[str, Any]] | None]  # zurich_data_fetcher_node

    # Processed result from amenity_locator_node (parallel with route/image nodes)
    amenity_summary: NotRequired[dict[str, Any] | None]        # amenity_locator_node

    # ── Observability ─────────────────────────────────────────────────────────
    # Annotated with operator.add so that when route_reasoner_node and
    # image_hazard_node both append a step during parallel execution, LangGraph
    # concatenates the two lists rather than raising InvalidUpdateError.
    trace_steps: Annotated[list[dict[str, Any]], operator.add]

    # ── Error ─────────────────────────────────────────────────────────────────
    error: str | None
