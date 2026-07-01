"""LangGraph pipeline for the planning workflow.

Updated pipeline (✨ Zurich OGD integration + 3-way parallel fan-out):

  input_validator_node
         ↓  (valid)
  zurich_data_fetcher_node   ← NEW: fetches ZüriACT, Züri WC, parking WFS APIs
         ↓
  ┌──────────────────────────────────────┐
  ▼              ▼                       ▼
route_reasoner  image_hazard   amenity_locator   ← parallel (amenity_locator NEW)
  └──────────────┴───────────────────────┘
                 ↓
         hazard_fusion_node   ← UPDATED: fuses ZüriACT barrier scores
                 ↓
           planner_node       ← UPDATED: uses amenity_summary (toilets/parking)
                 ↓
          synthesis_node      ← UPDATED: mentions Zurich data in reply
                 ↓
                END
"""
from __future__ import annotations

import contextvars
import time
from typing import Any

from langgraph.graph import END, StateGraph

from backend.app.agents.state import PlannerState
from backend.app.models import (
    AccessibilityProfile,
    HazardFusionSummary,
    ImageHazardsSummary,
    RawRoute,
    RouteSelectionDecision,
)
from backend.app.providers.llm_provider import MockLLMProvider, OllamaLLMProvider
from backend.app.providers.route_provider import MockRouteProvider
from backend.app.providers.route_provider import ROUTE_STEP_COORDS
from backend.app.providers.zurich_data_provider import (
    ROUTE_ZURICH_CENTERS,
    ZURICH_HB_CENTER,
    SEVERITY_LABELS,
    fetch_all_zurich_data,
    find_nearest_amenity,
    haversine_m,
    score_barriers_per_step,
    score_route_barriers,
)
from backend.app.services.planner_agent import PlannerAgent

# ── Context variable for per-request SSE callbacks ───────────────────────────
_node_callback: contextvars.ContextVar = contextvars.ContextVar(
    "_planning_node_callback", default=None
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_llm(state: PlannerState, role: str = "planner"):
    if state["llm_mode"] == "ollama":
        model = state.get(f"ollama_{role}_model") or state["ollama_model"]
        return OllamaLLMProvider(
            model=model,
            base_url=state["ollama_url"],
            timeout_sec=state["ollama_timeout"],
        )
    return MockLLMProvider()


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


def _wrap(name: str, fn):
    """Fire the per-request SSE callback before a node runs."""
    def wrapped(state: PlannerState):
        cb = _node_callback.get(None)
        if cb:
            cb(name, "starting")
        return fn(state)
    return wrapped


# ── Route selection logic ─────────────────────────────────────────────────────

def _decide_route(
    profile: AccessibilityProfile,
    route_id: str,
    route_provider: MockRouteProvider,
) -> tuple[RawRoute, RouteSelectionDecision]:
    requested_route = route_provider.get_route(route_id)
    selected_route = requested_route
    reasons = [f"requested fixture={requested_route.route_id}"]
    alerts: list[str] = []
    needs_step_free = profile.needs.mobility.needs_step_free_route is True

    if needs_step_free and not requested_route.step_free:
        alternative = route_provider.find_step_free_alternative(route_id)
        if alternative is not None and alternative.route_id != requested_route.route_id:
            selected_route = alternative
            reasons.append("step-free preference triggered route switch")
            alerts.append("requested fixture contains stairs; switched to a step-free alternative")
        else:
            reasons.append("step-free preference detected but no alternative fixture exists")
            alerts.append("step-free alternative unavailable in fixture data")
    elif needs_step_free and requested_route.step_free:
        reasons.append("requested route already satisfies the step-free constraint")
    else:
        reasons.append("no route switch required for the current profile")

    if profile.needs.cognitive.needs_simple_language is True:
        reasons.append("planner should prefer simple wording")
    if profile.needs.mobility.avoid_long_walks is True and requested_route.total_distance_m >= 2500:
        alerts.append("requested route has a long walking distance for this profile")

    decision = RouteSelectionDecision(
        requested_route_id=requested_route.route_id,
        requested_route_name=requested_route.name,
        selected_route_id=selected_route.route_id,
        selected_route_name=selected_route.name,
        switched_to_step_free=selected_route.route_id != requested_route.route_id,
        reasons=reasons,
        alerts=alerts,
    )
    return selected_route, decision


# ── Hazard fusion logic ───────────────────────────────────────────────────────

def _fuse_hazards(
    selected_route: RawRoute,
    image_hazards: ImageHazardsSummary | None,
    zurich_barrier_score: dict[str, Any] | None = None,
) -> HazardFusionSummary:
    highlights: list[str] = []

    # Route fixture metadata
    if any(step.has_stairs for step in selected_route.steps):
        highlights.append("selected route fixture includes stairs metadata")
    if any(step.audio_only_cue for step in selected_route.steps):
        highlights.append("selected route fixture includes an audio-only cue")
    if selected_route.total_distance_m >= 2500:
        highlights.append("selected route fixture includes a long walking segment")
    if selected_route.step_free:
        highlights.append("selected route fixture is marked step-free")

    # ZüriACT live data
    source_parts = ["route_metadata"]
    if zurich_barrier_score and zurich_barrier_score.get("total_barriers", 0) > 0:
        source_parts.append("zurich_ogd_zueriact")
        total = zurich_barrier_score["total_barriers"]
        worst = zurich_barrier_score.get("worst_severity", 0)
        categories = zurich_barrier_score.get("categories", [])
        worst_label = SEVERITY_LABELS.get(worst, str(worst))
        highlights.append(
            f"ZüriACT live data: {total} barrier(s) near route"
            + (f" ({', '.join(categories[:3])})" if categories else "")
            + f"; worst severity {worst}/5 ({worst_label})"
        )
        for alert in zurich_barrier_score.get("alerts", []):
            highlights.append(alert)

    # Image hazards
    if image_hazards is not None:
        source_parts.append("image_hazards")
        if image_hazards.stairs.value in {"medium", "high"}:
            highlights.append("optional image analysis flagged possible stairs")
        if image_hazards.slope.value in {"medium", "high"}:
            highlights.append("optional image analysis flagged a slope risk")
        if image_hazards.crowd.value in {"medium", "high"}:
            highlights.append("optional image analysis flagged crowd risk")
        if image_hazards.scene_summary:
            highlights.append("vision summary: " + image_hazards.scene_summary)
        if image_hazards.accessibility_cues:
            highlights.append("vision cues: " + ", ".join(image_hazards.accessibility_cues[:3]))
        if image_hazards.visible_objects:
            highlights.append("visible objects: " + ", ".join(image_hazards.visible_objects[:4]))
        highlights.extend(image_hazards.notes)

    if not highlights:
        highlights.append("no additional hazards were flagged")

    return HazardFusionSummary(
        source="+".join(source_parts),
        highlights=highlights,
    )


# ── Node implementations ──────────────────────────────────────────────────────

def _input_validator(state: PlannerState) -> dict[str, Any]:
    start = time.time() * 1000
    try:
        AccessibilityProfile.model_validate(state["profile"])
        is_valid = True
        err = None
        summary = "AccessibilityProfile schema validated successfully."
    except Exception as exc:
        is_valid = False
        err = str(exc)
        summary = f"Profile validation failed: {err}"

    step = _trace_step(
        agent_name="input_validator_node",
        role="input validation",
        summary=summary,
        input_keys=["profile"],
        output_keys=["is_valid"],
        key_findings=["valid"] if is_valid else [f"error: {err}"],
        start_ms=start,
    )
    result: dict[str, Any] = {
        "is_valid": is_valid,
        "validation_error": err,
        "trace_steps": [step],
    }
    if not is_valid:
        result["error"] = err
    return result


def _zurich_data_fetcher(state: PlannerState) -> dict[str, Any]:
    """Fetch live Zurich OGD accessibility data (ZüriACT + WC + parking).

    Runs sequentially after input_validator, before the parallel fan-out.
    Gracefully returns empty lists on network failure so the pipeline continues.
    """
    start = time.time() * 1000
    route_id = state.get("route_id", "default")
    center_lat, center_lon = ROUTE_ZURICH_CENTERS.get(route_id, ZURICH_HB_CENTER)

    data = state.get("zurich_data_override")
    if data is None:
        data = fetch_all_zurich_data(
            center_lat=center_lat,
            center_lon=center_lon,
            barrier_radius_m=1000.0,
            amenity_radius_m=1000.0,
        )
    barriers = data["barriers"]
    toilets  = data["toilets"]
    parking  = data["parking"]
    errors   = data["errors"]

    findings: list[str] = [
        f"ZüriACT barriers available: {len(barriers)}",
        f"accessible toilets available: {len(toilets)}",
        f"disabled parking spots available: {len(parking)}",
    ]
    if errors:
        findings += [f"fetch error: {e}" for e in errors]

    step = _trace_step(
        agent_name="zurich_data_fetcher_node",
        role="Zurich OGD data retrieval",
        summary=(
            f"Fetched {len(barriers)} ZüriACT barriers, {len(toilets)} accessible toilets, "
            f"{len(parking)} disabled parking spots for route area."
        ),
        input_keys=["route_id"],
        output_keys=["zurich_barriers", "zurich_toilets", "zurich_parking"],
        key_findings=findings,
        start_ms=start,
    )
    return {
        "zurich_barriers": barriers,
        "zurich_toilets":  toilets,
        "zurich_parking":  parking,
        "trace_steps": [step],
    }


def _route_reasoner(state: PlannerState) -> dict[str, Any]:
    """Parallel node — returns ONLY its own keys."""
    start = time.time() * 1000
    profile = AccessibilityProfile.model_validate(state["profile"])
    route_provider = MockRouteProvider()
    selected_route, decision = _decide_route(profile, state["route_id"], route_provider)

    step = _trace_step(
        agent_name="route_reasoner_node",
        role="route selection",
        summary="Compared requested route against functional constraints; selected best match.",
        input_keys=["profile", "route_id"],
        output_keys=["selected_route", "route_preferences", "route_alerts"],
        key_findings=decision.reasons + decision.alerts,
        start_ms=start,
    )
    return {
        "selected_route":    selected_route.model_dump(),
        "route_preferences": decision.reasons,
        "route_alerts":      decision.alerts,
        "trace_steps": [step],
    }


def _image_hazard(state: PlannerState) -> dict[str, Any]:
    """Parallel node — passes through pre-analysed image hazards or None."""
    start = time.time() * 1000
    raw = state.get("image_hazards")
    hazard_dict: dict[str, Any] | None = None
    findings: list[str] = []

    if raw is not None:
        try:
            ImageHazardsSummary.model_validate(raw)
            hazard_dict = raw
            findings = ["image hazards provided and validated"]
        except Exception as exc:
            findings = [f"image hazards validation warning: {exc}"]
    else:
        findings = ["no image provided — image hazard analysis skipped"]

    step = _trace_step(
        agent_name="image_hazard_node",
        role="image hazard analysis",
        summary="Validated and passed through optional pre-analysed image hazards.",
        input_keys=["image_hazards"],
        output_keys=["image_hazard_summary"],
        key_findings=findings,
        start_ms=start,
    )
    return {"image_hazard_summary": hazard_dict, "trace_steps": [step]}


def _amenity_locator(state: PlannerState) -> dict[str, Any]:
    """Parallel node — scores ZüriACT barriers and locates nearest amenities.

    Uses the Zurich OGD data already fetched by zurich_data_fetcher_node.
    When step coordinates are available for the requested route, computes a
    fine-grained per-step barrier score (80m radius per step) in addition to
    the overall route-midpoint score.
    """
    start = time.time() * 1000
    route_id = state.get("route_id", "default")
    center_lat, center_lon = ROUTE_ZURICH_CENTERS.get(route_id, ZURICH_HB_CENTER)

    barriers = state.get("zurich_barriers") or []
    toilets  = state.get("zurich_toilets")  or []
    parking  = state.get("zurich_parking")  or []

    # Overall route-midpoint barrier score (always computed)
    barrier_score = score_route_barriers(
        barriers, center_lat, center_lon, threshold_m=400.0
    )

    # Per-step barrier score (only for routes with known step coordinates)
    step_coords = ROUTE_STEP_COORDS.get(route_id, [])
    step_barrier_scores: list[dict[str, Any]] = []
    if step_coords and barriers:
        step_barrier_scores = score_barriers_per_step(
            barriers, step_coords, step_radius_m=80.0
        )

    # Find nearest accessible toilet (≤600m)
    nearest_toilet_raw = find_nearest_amenity(toilets, center_lat, center_lon, max_distance_m=600.0)
    nearest_toilet: dict[str, Any] | None = None
    if nearest_toilet_raw:
        nearest_toilet = {
            "lat": nearest_toilet_raw["lat"],
            "lon": nearest_toilet_raw["lon"],
            "name": nearest_toilet_raw.get("name", "WC"),
            "amenity_type": "toilet",
            "wheelchair_accessible": nearest_toilet_raw.get("wheelchair_accessible", True),
            "opening_hours": nearest_toilet_raw.get("opening_hours", ""),
            "free": nearest_toilet_raw.get("free", True),
            "address": "",
            "distance_m": nearest_toilet_raw["distance_m"],
        }

    # Find nearest disabled parking (≤800m)
    nearest_parking_raw = find_nearest_amenity(parking, center_lat, center_lon, max_distance_m=800.0)
    nearest_parking: dict[str, Any] | None = None
    if nearest_parking_raw:
        nearest_parking = {
            "lat": nearest_parking_raw["lat"],
            "lon": nearest_parking_raw["lon"],
            "name": nearest_parking_raw.get("address", "Behindertenparkplatz"),
            "amenity_type": "parking",
            "wheelchair_accessible": True,
            "opening_hours": "",
            "free": not nearest_parking_raw.get("fee_required", False),
            "address": nearest_parking_raw.get("address", ""),
            "distance_m": nearest_parking_raw["distance_m"],
        }

    amenity_summary: dict[str, Any] = {
        "barrier_score":       barrier_score,
        "step_barrier_scores": step_barrier_scores,  # list, empty if no step coords
        "nearest_toilet":      nearest_toilet,
        "nearest_parking":     nearest_parking,
        "data_available":      len(barriers) > 0 or len(toilets) > 0 or len(parking) > 0,
        "barriers_total":      len(barriers),
        "toilets_total":       len(toilets),
        "parking_total":       len(parking),
    }

    findings: list[str] = [f"barriers near route: {barrier_score['total_barriers']}"]
    if barrier_score["alerts"]:
        findings += barrier_score["alerts"]
    if step_barrier_scores:
        steps_with_barriers = [s for s in step_barrier_scores if s["barrier_count"] > 0]
        findings.append(
            f"per-step: {len(steps_with_barriers)}/{len(step_barrier_scores)} steps have nearby barriers"
        )
        worst_step = max(step_barrier_scores, key=lambda s: s["worst_severity"], default=None)
        if worst_step and worst_step["worst_severity"] >= 4:
            findings.append(
                f"worst step: step {worst_step['step_index']+1} severity {worst_step['worst_severity']}/5"
            )
    if nearest_toilet:
        findings.append(f"nearest toilet: {nearest_toilet['name']} ({nearest_toilet['distance_m']}m)")
    if nearest_parking:
        findings.append(f"nearest parking: {nearest_parking['address']} ({nearest_parking['distance_m']}m)")

    per_step_note = (
        f"; per-step analysis for {len(step_barrier_scores)} steps"
        if step_barrier_scores else ""
    )
    step = _trace_step(
        agent_name="amenity_locator_node",
        role="Zurich amenity scoring",
        summary=(
            f"Scored {barrier_score['total_barriers']} ZüriACT barriers{per_step_note}; "
            f"located{'nearest toilet and ' if nearest_toilet else ' '}accessible amenities."
        ),
        input_keys=["zurich_barriers", "zurich_toilets", "zurich_parking", "route_id"],
        output_keys=["amenity_summary"],
        key_findings=findings,
        start_ms=start,
    )
    return {"amenity_summary": amenity_summary, "trace_steps": [step]}


def _hazard_fusion(state: PlannerState) -> dict[str, Any]:
    start = time.time() * 1000
    selected_route_dict = state.get("selected_route")
    image_hazard_dict   = state.get("image_hazard_summary")
    amenity_sum         = state.get("amenity_summary") or {}

    route_provider = MockRouteProvider()
    if selected_route_dict:
        selected_route = route_provider.get_route(selected_route_dict["route_id"])
    else:
        selected_route = route_provider.get_route(state["route_id"])

    image_hazards: ImageHazardsSummary | None = None
    if image_hazard_dict is not None:
        try:
            image_hazards = ImageHazardsSummary.model_validate(image_hazard_dict)
        except Exception:
            pass

    barrier_score = amenity_sum.get("barrier_score") or {}
    fusion = _fuse_hazards(selected_route, image_hazards, barrier_score)

    step = _trace_step(
        agent_name="hazard_fusion_node",
        role="risk fusion",
        summary="Merged route metadata, ZüriACT live barriers, and optional image hazards.",
        input_keys=["selected_route", "image_hazard_summary", "amenity_summary"],
        output_keys=["fused_hazards"],
        key_findings=fusion.highlights[:5],
        start_ms=start,
    )
    return {"fused_hazards": fusion.model_dump(), "trace_steps": [step]}


def _planner(state: PlannerState) -> dict[str, Any]:
    start = time.time() * 1000
    llm = _make_llm(state, role="planner")
    route_provider = MockRouteProvider()
    agent = PlannerAgent(llm_provider=llm, route_provider=route_provider)

    image_hazards_model: ImageHazardsSummary | None = None
    if state.get("image_hazard_summary") is not None:
        try:
            image_hazards_model = ImageHazardsSummary.model_validate(state["image_hazard_summary"])
        except Exception:
            pass

    effective_route_id = state["route_id"]
    if state.get("selected_route"):
        effective_route_id = state["selected_route"]["route_id"]

    amenity_sum = state.get("amenity_summary") or {}

    plan = agent.create_plan(
        profile=state["profile"],
        route_id=effective_route_id,
        image_hazards=image_hazards_model,
        response_language=state.get("language", "en"),
        zurich_data=amenity_sum if amenity_sum.get("data_available") else None,
    )

    step = _trace_step(
        agent_name="planner_node",
        role="plan generation",
        summary="Generated personalised directions, alerts, checklists, and recovery steps.",
        input_keys=["profile", "selected_route", "image_hazard_summary", "amenity_summary"],
        output_keys=["plan"],
        key_findings=[
            f"directions={len(plan.directions)}",
            f"alerts={len(plan.alerts)}",
            f"preferences={len(plan.preferences_applied)}",
        ],
        start_ms=start,
    )
    return {"plan": plan.model_dump(), "trace_steps": [step]}


def _synthesis(state: PlannerState) -> dict[str, Any]:
    start = time.time() * 1000
    selected_route_dict = state.get("selected_route") or {}
    fused_hazards_dict  = state.get("fused_hazards")  or {}
    plan_dict           = state.get("plan")            or {}
    amenity_sum         = state.get("amenity_summary") or {}

    # Route note
    req_id   = state["route_id"]
    sel_id   = selected_route_dict.get("route_id", req_id)
    req_name = selected_route_dict.get("name", req_id) if sel_id == req_id else req_id
    sel_name = selected_route_dict.get("name", sel_id)

    route_note = (
        f"Route orchestrator selected '{sel_name}'."
        if sel_id == req_id
        else f"Route orchestrator switched from '{req_name}' to '{sel_name}'."
    )

    highlights = fused_hazards_dict.get("highlights", [])
    risk_note  = " Risk check: " + "; ".join(highlights[:3]) + "." if highlights else ""

    directions = plan_dict.get("directions", [])
    alerts     = plan_dict.get("alerts", [])
    checklist  = plan_dict.get("checklist", [])
    plan_note  = (
        f" Plan synthesis produced {len(directions)} directions, "
        f"{len(alerts)} alerts, and {len(checklist)} checklist items."
    )

    # Zurich data note
    zurich_note = ""
    barrier_score = amenity_sum.get("barrier_score", {})
    n_barriers = barrier_score.get("total_barriers", 0)
    if n_barriers > 0:
        worst = barrier_score.get("worst_severity", 0)
        zurich_note = (
            f" ZüriACT live data: {n_barriers} barrier(s) in area"
            f" (worst severity {worst}/5)."
        )
    if amenity_sum.get("nearest_toilet"):
        t = amenity_sum["nearest_toilet"]
        zurich_note += f" Nearest accessible toilet: {t['name']} ({t['distance_m']}m)."
    if amenity_sum.get("nearest_parking"):
        p = amenity_sum["nearest_parking"]
        zurich_note += f" Nearest disabled parking: {p['address']} ({p['distance_m']}m)."

    agent_reply = route_note + risk_note + plan_note + zurich_note

    step = _trace_step(
        agent_name="synthesis_node",
        role="explanation synthesis",
        summary="Turned multi-agent outputs into a concise user-facing explanation.",
        input_keys=["selected_route", "fused_hazards", "plan", "amenity_summary"],
        output_keys=["agent_reply"],
        key_findings=[agent_reply[:200]] if agent_reply else [],
        start_ms=start,
    )
    return {"agent_reply": agent_reply, "trace_steps": [step]}


# ── Graph construction ────────────────────────────────────────────────────────

def _after_validator(state: PlannerState):
    if state.get("is_valid"):
        return "zurich_data_fetcher_node"
    return END


def _after_zurich_fetcher(state: PlannerState):
    """Fan-out to 3 parallel nodes after Zurich data is fetched."""
    return ["route_reasoner_node", "image_hazard_node", "amenity_locator_node"]


def build_planning_graph():
    """Build and compile the planning LangGraph pipeline."""
    g = StateGraph(PlannerState)

    g.add_node("input_validator_node",       _wrap("input_validator_node",       _input_validator))
    g.add_node("zurich_data_fetcher_node",   _wrap("zurich_data_fetcher_node",   _zurich_data_fetcher))
    g.add_node("route_reasoner_node",        _wrap("route_reasoner_node",        _route_reasoner))
    g.add_node("image_hazard_node",          _wrap("image_hazard_node",          _image_hazard))
    g.add_node("amenity_locator_node",       _wrap("amenity_locator_node",       _amenity_locator))
    g.add_node("hazard_fusion_node",         _wrap("hazard_fusion_node",         _hazard_fusion))
    g.add_node("planner_node",               _wrap("planner_node",               _planner))
    g.add_node("synthesis_node",             _wrap("synthesis_node",             _synthesis))

    g.set_entry_point("input_validator_node")

    # input_validator → zurich_data_fetcher (sequential) or END on failure
    g.add_conditional_edges(
        "input_validator_node",
        _after_validator,
        {
            "zurich_data_fetcher_node": "zurich_data_fetcher_node",
            END: END,
        },
    )

    # zurich_data_fetcher → 3-way parallel fan-out
    g.add_conditional_edges(
        "zurich_data_fetcher_node",
        _after_zurich_fetcher,
        {
            "route_reasoner_node":  "route_reasoner_node",
            "image_hazard_node":    "image_hazard_node",
            "amenity_locator_node": "amenity_locator_node",
        },
    )

    # All three parallel branches converge at hazard_fusion_node
    g.add_edge("route_reasoner_node",  "hazard_fusion_node")
    g.add_edge("image_hazard_node",    "hazard_fusion_node")
    g.add_edge("amenity_locator_node", "hazard_fusion_node")

    g.add_edge("hazard_fusion_node", "planner_node")
    g.add_edge("planner_node",       "synthesis_node")
    g.add_edge("synthesis_node",     END)

    return g.compile()


# Compiled singleton
planning_pipeline = build_planning_graph()


# ── Public helpers ────────────────────────────────────────────────────────────

def run_planning(state_dict: dict[str, Any]) -> PlannerState:
    """Run the planning pipeline synchronously and return the final state."""
    return planning_pipeline.invoke(state_dict)


def stream_planning(state_dict: dict[str, Any], on_node_start=None):
    """Generator that yields SSE-style progress dicts then a final 'result' dict."""
    _node_start_ms: dict[str, float] = {}
    _emitted_done: set[str] = set()
    final_state: PlannerState | None = None

    def _on_start(name: str, _status: str) -> None:
        _node_start_ms[name] = time.time() * 1000
        event = {"type": "progress", "status": "starting", "agent": name}
        if on_node_start is not None:
            on_node_start(event)

    token = _node_callback.set(_on_start)
    try:
        for full_state in planning_pipeline.stream(state_dict, stream_mode="values"):
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
