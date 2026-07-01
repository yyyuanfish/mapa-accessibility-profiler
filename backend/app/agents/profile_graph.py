"""LangGraph pipeline for the profiling workflow.

Pipeline:
  consent_guard_node
       ↓ (if consent denied → END)
  profiler_node          ← ProfilerAgent.process_turn()
       ↓
  profile_manager_node   ← ProfilerAgent.build_profile()
       ↓
  conversation_orchestrator_node
       ↓
      END
"""
from __future__ import annotations

import contextvars
import time
from typing import Any

from langgraph.graph import END, StateGraph

from backend.app.agents.state import ProfilerState
from backend.app.models import AccessibilityProfile
from backend.app.providers.llm_provider import MockLLMProvider, OllamaLLMProvider
from backend.app.services.profiler_agent import ProfilerAgent

# ── Context variable for per-request SSE callbacks ───────────────────────────
_node_callback: contextvars.ContextVar = contextvars.ContextVar(
    "_profile_node_callback", default=None
)


# ── Helper: build LLM provider from state config ─────────────────────────────

def _make_llm(state: ProfilerState, role: str = "profiler"):
    if state["llm_mode"] == "ollama":
        # Per-agent model selection
        model = state.get(f"ollama_{role}_model") or state["ollama_model"]
        return OllamaLLMProvider(
            model=model,
            base_url=state["ollama_url"],
            timeout_sec=state["ollama_timeout"],
        )
    return MockLLMProvider()


# ── Helper: append a trace step ──────────────────────────────────────────────

def _trace_step(
    agent_name: str,
    role: str,
    summary: str,
    input_keys: list[str],
    output_keys: list[str],
    key_findings: list[str],
    start_ms: float,
) -> dict[str, Any]:
    return {
        "agent_name": agent_name,
        "role": role,
        "summary": summary,
        "input_keys": input_keys,
        "output_keys": output_keys,
        "key_findings": key_findings,
        "duration_ms": int(time.time() * 1000 - start_ms),
    }


# ── Node wrapper for SSE "starting" callbacks ─────────────────────────────────

def _wrap(name: str, fn):
    """Fire the per-request callback before the node runs (for SSE progress)."""
    def wrapped(state: ProfilerState):
        cb = _node_callback.get(None)
        if cb:
            cb(name, "starting")
        return fn(state)
    return wrapped


# ── Node implementations ──────────────────────────────────────────────────────

def _consent_guard(state: ProfilerState) -> dict[str, Any]:
    start = time.time() * 1000
    granted = bool(state.get("consent_to_profile", False))
    step = _trace_step(
        agent_name="consent_guard_node",
        role="policy gate",
        summary=(
            "Verified that functional profiling is consented and diagnosis remains out of scope."
            if granted
            else "Profiling blocked: consent was not given."
        ),
        input_keys=["consent_to_profile"],
        output_keys=["consent_granted"],
        key_findings=["functional-needs-only mode enabled"] if granted else ["consent denied"],
        start_ms=start,
    )
    existing = list(state.get("trace_steps", []))
    existing.append(step)
    result: dict[str, Any] = {"consent_granted": granted, "trace_steps": existing}
    if not granted:
        result["error"] = "Consent is required before profiling."
    return result


def _profiler(state: ProfilerState) -> dict[str, Any]:
    start = time.time() * 1000
    llm = _make_llm(state, role="profiler")
    agent = ProfilerAgent(llm_provider=llm)
    output = agent.process_turn(
        user_message=state["user_message"],
        current_patch=state.get("current_patch"),
        skipped_domains=state.get("skipped_domains") or [],
        question_context=state.get("question_context"),
        response_language=state.get("language", "en"),
        turn_count=state.get("turn_count", 1),
    )
    output_dict = {
        "profile_patch": output.profile_patch.model_dump(),
        "confidence": output.confidence.model_dump(),
        "missing_critical_fields": output.missing_critical_fields,
        "next_question": output.next_question,
        "next_question_context": output.next_question_context,
        "confirmation_text": output.confirmation_text,
    }

    # Extract key findings for trace
    patch = output.profile_patch.model_dump()
    needs = patch.get("needs", {})
    findings: list[str] = []
    if needs.get("vision", {}).get("blind_or_low_vision") is True:
        findings.append("vision support detected")
    if needs.get("hearing", {}).get("deaf_or_hard_of_hearing") is True:
        findings.append("hearing support detected")
    if needs.get("mobility", {}).get("needs_step_free_route") is True:
        findings.append("step-free routing preference detected")
    if needs.get("cognitive", {}).get("needs_simple_language") is True:
        findings.append("simple-language mode requested")
    if not findings:
        findings.append("no new positive needs inferred from this turn")

    step = _trace_step(
        agent_name="profiler_node",
        role="dialogue understanding",
        summary="Updated the profile patch from the latest utterance and generated a confirmation recap.",
        input_keys=["user_message", "current_patch", "question_context", "turn_count"],
        output_keys=["profiler_output"],
        key_findings=findings,
        start_ms=start,
    )
    existing = list(state.get("trace_steps", []))
    existing.append(step)
    return {"profiler_output": output_dict, "trace_steps": existing}


def _profile_manager(state: ProfilerState) -> dict[str, Any]:
    start = time.time() * 1000
    llm = _make_llm(state, role="profiler")
    agent = ProfilerAgent(llm_provider=llm)
    profiler_output = state.get("profiler_output") or {}
    profile = agent.build_profile(
        profile_patch=profiler_output.get("profile_patch", {}),
        consent_to_profile=state.get("consent_to_profile", True),
        skipped_domains=state.get("skipped_domains") or [],
    )
    draft_dict = profile.model_dump()
    missing = profiler_output.get("missing_critical_fields", [])

    step = _trace_step(
        agent_name="profile_manager_node",
        role="schema validation",
        summary="Validated the accumulated patch as strict accessibility_profile JSON.",
        input_keys=["profiler_output", "skipped_domains"],
        output_keys=["draft_profile"],
        key_findings=[
            f"overall confidence={profile.confidence.overall}",
            f"missing_fields={len(missing)}",
        ],
        start_ms=start,
    )
    existing = list(state.get("trace_steps", []))
    existing.append(step)
    return {"draft_profile": draft_dict, "trace_steps": existing}


def _conversation_orchestrator(state: ProfilerState) -> dict[str, Any]:
    start = time.time() * 1000
    profiler_output = state.get("profiler_output") or {}
    draft_dict = state.get("draft_profile") or {}

    confirmation = profiler_output.get("confirmation_text", "")
    next_question = profiler_output.get("next_question")

    # Build positive labels from draft profile
    profile_model = AccessibilityProfile.model_validate(draft_dict)
    labels: list[str] = []
    if profile_model.needs.vision.blind_or_low_vision is True:
        labels.append("low_vision_support")
    if profile_model.needs.hearing.deaf_or_hard_of_hearing is True:
        labels.append("hearing_support")
    if profile_model.needs.hearing.sign_language_user is True:
        labels.append("sign_gloss_output")
    if profile_model.needs.mobility.wheelchair_user is True:
        labels.append("wheelchair_support")
    if profile_model.needs.mobility.needs_step_free_route is True:
        labels.append("step_free_route")
    if profile_model.needs.cognitive.needs_simple_language is True:
        labels.append("simple_language")
    if profile_model.needs.cognitive.needs_memory_support is True:
        labels.append("memory_support")

    orchestration_note = "Multi-agent pipeline: consent_guard → profiler → profile_manager → conversation_orchestrator."
    if labels:
        orchestration_note += " Active supports: " + ", ".join(labels) + "."
    else:
        orchestration_note += " No positive support need confirmed yet."

    if next_question:
        orchestration_note += f" Next action: {next_question}"
    else:
        orchestration_note += " Next action: route planning can start."

    agent_reply = f"{confirmation}\n\n{orchestration_note}" if confirmation else orchestration_note

    step = _trace_step(
        agent_name="conversation_orchestrator_node",
        role="next-step planning",
        summary="Prepared the next action for either another profiling turn or route planning.",
        input_keys=["draft_profile", "next_question"],
        output_keys=["agent_reply"],
        key_findings=[agent_reply[:180]] if agent_reply else [],
        start_ms=start,
    )
    existing = list(state.get("trace_steps", []))
    existing.append(step)
    return {"agent_reply": agent_reply, "trace_steps": existing}


# ── Graph construction ────────────────────────────────────────────────────────

def _after_consent(state: ProfilerState) -> str:
    return "profiler_node" if state.get("consent_granted") else END


def build_profile_graph():
    """Build and compile the profile LangGraph pipeline."""
    g = StateGraph(ProfilerState)

    g.add_node("consent_guard_node", _wrap("consent_guard_node", _consent_guard))
    g.add_node("profiler_node", _wrap("profiler_node", _profiler))
    g.add_node("profile_manager_node", _wrap("profile_manager_node", _profile_manager))
    g.add_node("conversation_orchestrator_node", _wrap("conversation_orchestrator_node", _conversation_orchestrator))

    g.set_entry_point("consent_guard_node")
    g.add_conditional_edges(
        "consent_guard_node",
        _after_consent,
        {"profiler_node": "profiler_node", END: END},
    )
    g.add_edge("profiler_node", "profile_manager_node")
    g.add_edge("profile_manager_node", "conversation_orchestrator_node")
    g.add_edge("conversation_orchestrator_node", END)

    return g.compile()


# Compiled singleton — imported by orchestrator and SSE helpers
profile_pipeline = build_profile_graph()


# ── Public helpers ────────────────────────────────────────────────────────────

def run_profile_turn(state_dict: dict[str, Any]) -> ProfilerState:
    """Run the profile pipeline synchronously and return the final state."""
    return profile_pipeline.invoke(state_dict)


def stream_profile_turn(state_dict: dict[str, Any], on_node_start=None):
    """Generator that yields SSE-style progress dicts then a final 'result' dict.

    If ``on_node_start`` is provided it is called immediately (from the same
    thread) when a node is about to start — useful for pushing 'starting' events
    to the SSE queue before the node finishes.
    """
    _node_start_ms: dict[str, float] = {}
    _emitted_done: set[str] = set()
    final_state: ProfilerState | None = None

    def _on_start(name: str, _status: str) -> None:
        _node_start_ms[name] = time.time() * 1000
        event = {"type": "progress", "status": "starting", "agent": name}
        if on_node_start is not None:
            on_node_start(event)

    token = _node_callback.set(_on_start)
    try:
        # stream_mode="values" → each chunk is the full accumulated state after
        # that step, so the last chunk contains all keys populated so far.
        for full_state in profile_pipeline.stream(state_dict, stream_mode="values"):
            final_state = full_state
            for node_name, start_ms in list(_node_start_ms.items()):
                if node_name not in _emitted_done:
                    _emitted_done.add(node_name)
                    duration_ms = int(time.time() * 1000 - start_ms)
                    yield {
                        "type": "progress",
                        "status": "done",
                        "agent": node_name,
                        "duration_ms": duration_ms,
                    }
    finally:
        _node_callback.reset(token)

    yield {"type": "result", "state": final_state}
