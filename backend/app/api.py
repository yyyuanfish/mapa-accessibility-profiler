"""FastAPI server — profiling and planning endpoints (streaming + non-streaming)."""
from __future__ import annotations

import asyncio
import json
import sys
import os
import threading

# Ensure project root is on path when running with uvicorn from any directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.app.agents.planning_graph import stream_planning
from backend.app.agents.profile_graph import stream_profile_turn
from backend.app.models import (
    AccessibilityProfile,
    ImageHazardsSummary,
    ProfilePatch,
)
from backend.app.providers.llm_provider import MockLLMProvider, OllamaLLMProvider
from backend.app.providers.route_provider import MockRouteProvider
from backend.app.providers.zurich_data_provider import (
    ZURICH_HB_CENTER,
    fetch_all_zurich_data,
)
from backend.app.providers.speech_provider import (
    FasterWhisperSpeechProvider,
    MockSpeechProvider,
)
from backend.app.services.orchestrator import Orchestrator
from backend.app.services.planner_agent import PlannerAgent
from backend.app.services.profiler_agent import ProfilerAgent

app = FastAPI(title="MAPA Profiler API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ──────────────────────────────────────────────────

class ProfileTurnRequest(BaseModel):
    user_message: str
    current_patch: Optional[dict[str, Any]] = None
    skipped_domains: list[str] = []
    question_context: Optional[str] = None
    turn_count: int = 1
    language: str = "en"
    consent_to_profile: bool = True
    # LLM provider config
    mode: str = "mock"           # "mock" | "ollama"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "shmily_006/Qw3:4b_4bit"
    ollama_profiler_model: str = ""
    ollama_planner_model: str = ""
    ollama_image_model: str = "llava:7b"
    ollama_timeout: int = 300


class ProfileTurnResponse(BaseModel):
    profile_patch: dict[str, Any]
    confidence: dict[str, Any]
    missing_critical_fields: list[str]
    next_question: Optional[str]
    next_question_context: Optional[str]
    confirmation_text: str
    speech_text: str


class PlanRequest(BaseModel):
    profile_patch: dict[str, Any]
    route_id: str = "route_with_stairs"
    language: str = "en"
    image_hazards: Optional[dict[str, Any]] = None
    # LLM provider config
    mode: str = "mock"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "shmily_006/Qw3:4b_4bit"
    ollama_profiler_model: str = ""
    ollama_planner_model: str = ""
    ollama_image_model: str = "llava:7b"
    ollama_timeout: int = 300


class PlanResponse(BaseModel):
    summary: str
    directions: list[str]
    alerts: list[str]
    checklist: list[str]
    if_you_get_lost: list[str]
    preferences_applied: list[str]
    speech_text: str


class AudioTranscriptionResponse(BaseModel):
    transcript: str
    language: str = "en"
    provider: str
    duration_sec: Optional[float] = None


class RouteInfo(BaseModel):
    route_id: str
    name: str
    step_free: bool
    total_distance_m: int
    total_duration_min: int


class ZurichDataResponse(BaseModel):
    barriers: list[dict]
    toilets: list[dict]
    parking: list[dict]
    barriers_count: int
    toilets_count: int
    parking_count: int
    fetch_errors: list[str]
    center_lat: float
    center_lon: float
    radius_m: float


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_llm_provider(mode: str, ollama_url: str, ollama_model: str, ollama_timeout: int):
    if mode == "ollama":
        return OllamaLLMProvider(
            model=ollama_model,
            base_url=ollama_url,
            timeout_sec=ollama_timeout,
        )
    return MockLLMProvider()


def _make_orchestrator(req) -> Orchestrator:
    return Orchestrator(
        llm_mode=req.mode,
        ollama_url=req.ollama_url,
        ollama_model=req.ollama_model,
        ollama_timeout=req.ollama_timeout,
        ollama_profiler_model=req.ollama_profiler_model,
        ollama_planner_model=req.ollama_planner_model,
        ollama_image_model=req.ollama_image_model,
        speech_mode=os.getenv("MAPA_SPEECH_PROVIDER", "faster-whisper"),
        speech_model=os.getenv("MAPA_SPEECH_MODEL", "small"),
        speech_device=os.getenv("MAPA_SPEECH_DEVICE", "auto"),
        speech_compute_type=os.getenv("MAPA_SPEECH_COMPUTE_TYPE", "int8"),
    )


def _make_speech_provider(model: str | None = None):
    speech_mode = os.getenv("MAPA_SPEECH_PROVIDER", "faster-whisper").strip().lower()
    if speech_mode == "mock":
        return MockSpeechProvider()
    return FasterWhisperSpeechProvider(
        model_size=model or os.getenv("MAPA_SPEECH_MODEL", "small"),
        device=os.getenv("MAPA_SPEECH_DEVICE", "auto"),
        compute_type=os.getenv("MAPA_SPEECH_COMPUTE_TYPE", "int8"),
    )


def _profile_state_dict(req: ProfileTurnRequest) -> dict[str, Any]:
    return {
        "user_message": req.user_message,
        "current_patch": req.current_patch,
        "skipped_domains": req.skipped_domains,
        "question_context": req.question_context,
        "turn_count": req.turn_count,
        "language": req.language,
        "consent_to_profile": req.consent_to_profile,
        "llm_mode": req.mode,
        "ollama_url": req.ollama_url,
        "ollama_model": req.ollama_model,
        "ollama_profiler_model": req.ollama_profiler_model or req.ollama_model,
        "ollama_planner_model": req.ollama_planner_model or req.ollama_model,
        "ollama_image_model": req.ollama_image_model or "llava:7b",
        "ollama_timeout": req.ollama_timeout,
        "consent_granted": False,
        "trace_steps": [],
        "error": None,
    }


def _plan_state_dict(req: PlanRequest, profile_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": profile_dict,
        "route_id": req.route_id,
        "language": req.language,
        "image_hazards": req.image_hazards,
        "llm_mode": req.mode,
        "ollama_url": req.ollama_url,
        "ollama_model": req.ollama_model,
        "ollama_profiler_model": req.ollama_profiler_model or req.ollama_model,
        "ollama_planner_model": req.ollama_planner_model or req.ollama_model,
        "ollama_image_model": req.ollama_image_model or "llava:7b",
        "ollama_timeout": req.ollama_timeout,
        "is_valid": False,
        "validation_error": None,
        "trace_steps": [],
        "error": None,
    }


def _join_speech_parts(parts: list[str | None]) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def _profile_speech_text(
    orchestrator: Orchestrator,
    *,
    confirmation_text: str,
    next_question: str | None,
    language: str,
) -> str:
    return orchestrator.prepare_spoken_text(
        _join_speech_parts([confirmation_text, next_question]),
        response_language=language,
    )


def _plan_speech_text(
    orchestrator: Orchestrator,
    *,
    summary: str,
    directions: list[str],
    alerts: list[str],
    language: str,
) -> str:
    return orchestrator.prepare_spoken_text(
        _join_speech_parts([summary, " ".join(directions[:2]), " ".join(alerts[:2])]),
        response_language=language,
    )


# ── SSE helper: thread-safe event generator ───────────────────────────────────

def _sse_generator(pipeline_fn, state_dict: dict[str, Any], result_to_dict):
    """Return an async generator for StreamingResponse that runs pipeline_fn
    in a worker thread and streams SSE events to the client.

    Events:
      {"type":"progress","agent":"<name>","status":"starting"}
      {"type":"progress","agent":"<name>","status":"done","duration_ms":N}
      {"type":"result", ...result fields...}
      {"type":"error","message":"<msg>"}
    """
    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def run_thread():
            try:
                def push_start(evt):
                    loop.call_soon_threadsafe(queue.put_nowait, evt)

                for event in pipeline_fn(state_dict, on_node_start=push_start):
                    if event["type"] == "result":
                        result_event = result_to_dict(event["state"])
                        result_event["type"] = "result"
                        loop.call_soon_threadsafe(queue.put_nowait, result_event)
                    else:
                        loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:
                loop.call_soon_threadsafe(
                    queue.put_nowait, {"type": "error", "message": str(exc)}
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

        threading.Thread(target=run_thread, daemon=True).start()

        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return event_generator()


_SSE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/routes", response_model=list[RouteInfo])
def list_routes():
    provider = MockRouteProvider()
    return [
        RouteInfo(
            route_id=r.route_id,
            name=r.name,
            step_free=r.step_free,
            total_distance_m=r.total_distance_m,
            total_duration_min=r.total_duration_min,
        )
        for r in provider.list_routes()
    ]


@app.post("/api/audio/transcribe", response_model=AudioTranscriptionResponse)
async def transcribe_audio(
    request: Request,
    language: str = "en",
    model: str = "small",
):
    audio_bytes = await request.body()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

    orchestrator = Orchestrator(speech_provider=_make_speech_provider(model))
    try:
        result = orchestrator.transcribe_audio(
            audio_bytes,
            mime_type=request.headers.get("content-type"),
            response_language=language,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return AudioTranscriptionResponse(**result.model_dump())


# ── Profile endpoints ──────────────────────────────────────────────────────────

@app.post("/api/profile/turn", response_model=ProfileTurnResponse)
def profile_turn(req: ProfileTurnRequest):
    """Non-streaming profile turn — delegates to the LangGraph profile pipeline."""
    orchestrator = _make_orchestrator(req)
    try:
        result = orchestrator.process_profile_turn(
            user_message=req.user_message,
            current_patch=req.current_patch,
            skipped_domains=req.skipped_domains,
            question_context=req.question_context,
            response_language=req.language,
            consent_to_profile=req.consent_to_profile,
            turn_count=req.turn_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    out = result.profiler_output
    speech_text = _profile_speech_text(
        orchestrator,
        confirmation_text=out.confirmation_text,
        next_question=out.next_question,
        language=req.language,
    )
    return ProfileTurnResponse(
        profile_patch=out.profile_patch.model_dump(),
        confidence=out.confidence.model_dump(),
        missing_critical_fields=out.missing_critical_fields,
        next_question=out.next_question,
        next_question_context=out.next_question_context,
        confirmation_text=out.confirmation_text,
        speech_text=speech_text,
    )


@app.post("/api/profile/stream")
async def profile_turn_stream(req: ProfileTurnRequest):
    """SSE streaming profile turn — emits per-node progress then result."""
    state_dict = _profile_state_dict(req)

    def result_to_dict(state) -> dict[str, Any]:
        profiler_output = state.get("profiler_output") or {}
        speech_text = _profile_speech_text(
            orchestrator,
            confirmation_text=profiler_output.get("confirmation_text", ""),
            next_question=profiler_output.get("next_question"),
            language=req.language,
        )
        return {
            "profile_patch": profiler_output.get("profile_patch", {}),
            "confidence": profiler_output.get("confidence", {}),
            "missing_critical_fields": profiler_output.get("missing_critical_fields", []),
            "next_question": profiler_output.get("next_question"),
            "next_question_context": profiler_output.get("next_question_context"),
            "confirmation_text": profiler_output.get("confirmation_text", ""),
            "speech_text": speech_text,
            "agent_reply": state.get("agent_reply", ""),
            "trace_steps": state.get("trace_steps", []),
        }

    orchestrator = _make_orchestrator(req)
    return StreamingResponse(
        _sse_generator(stream_profile_turn, state_dict, result_to_dict),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


# ── Plan endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/plan", response_model=PlanResponse)
def create_plan(req: PlanRequest):
    """Non-streaming plan creation — delegates to the LangGraph planning pipeline."""
    try:
        patch = ProfilePatch.model_validate(req.profile_patch)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid profile_patch: {exc}") from exc

    # Build full profile from patch
    llm = _make_llm_provider(req.mode, req.ollama_url, req.ollama_model, req.ollama_timeout)
    profiler = ProfilerAgent(llm_provider=llm)
    profile = profiler.build_profile(patch, consent_to_profile=True)

    hazards = None
    if req.image_hazards is not None:
        try:
            hazards = ImageHazardsSummary.model_validate(req.image_hazards)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid image_hazards: {exc}") from exc

    orchestrator = _make_orchestrator(req)
    try:
        result = orchestrator.create_journey_plan(
            profile=profile,
            route_id=req.route_id,
            image_hazards=hazards,
            response_language=req.language,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Route not found: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    plan = result.plan
    speech_text = _plan_speech_text(
        orchestrator,
        summary=plan.summary,
        directions=plan.directions,
        alerts=plan.alerts,
        language=req.language,
    )
    return PlanResponse(
        summary=plan.summary,
        directions=plan.directions,
        alerts=plan.alerts,
        checklist=plan.checklist,
        if_you_get_lost=plan.if_you_get_lost,
        preferences_applied=plan.preferences_applied,
        speech_text=speech_text,
    )


@app.get("/api/zurich/data", response_model=ZurichDataResponse)
def get_zurich_data(
    lat: float = ZURICH_HB_CENTER[0],
    lon: float = ZURICH_HB_CENTER[1],
    radius_m: float = 1000.0,
):
    """Return live Zurich OGD accessibility data (ZüriACT, Züri WC, parking).

    Query params:
      - lat / lon: centre point in WGS-84 (defaults to Zürich HB)
      - radius_m: search radius in metres (default 1000)
    """
    data = fetch_all_zurich_data(
        center_lat=lat,
        center_lon=lon,
        barrier_radius_m=radius_m,
        amenity_radius_m=radius_m,
    )
    return ZurichDataResponse(
        barriers=data["barriers"],
        toilets=data["toilets"],
        parking=data["parking"],
        barriers_count=len(data["barriers"]),
        toilets_count=len(data["toilets"]),
        parking_count=len(data["parking"]),
        fetch_errors=data["errors"],
        center_lat=lat,
        center_lon=lon,
        radius_m=radius_m,
    )


@app.post("/api/plan/stream")
async def create_plan_stream(req: PlanRequest):
    """SSE streaming plan creation — emits per-node progress (incl. parallel) then result."""
    try:
        patch = ProfilePatch.model_validate(req.profile_patch)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid profile_patch: {exc}") from exc

    llm = _make_llm_provider(req.mode, req.ollama_url, req.ollama_model, req.ollama_timeout)
    profiler = ProfilerAgent(llm_provider=llm)
    profile = profiler.build_profile(patch, consent_to_profile=True)
    state_dict = _plan_state_dict(req, profile.model_dump())
    orchestrator = _make_orchestrator(req)

    def result_to_dict(state) -> dict[str, Any]:
        plan = state.get("plan") or {}
        speech_text = _plan_speech_text(
            orchestrator,
            summary=plan.get("summary", ""),
            directions=plan.get("directions", []),
            alerts=plan.get("alerts", []),
            language=req.language,
        )
        return {
            "summary": plan.get("summary", ""),
            "directions": plan.get("directions", []),
            "alerts": plan.get("alerts", []),
            "checklist": plan.get("checklist", []),
            "if_you_get_lost": plan.get("if_you_get_lost", []),
            "preferences_applied": plan.get("preferences_applied", []),
            "speech_text": speech_text,
            "agent_reply": state.get("agent_reply", ""),
            "trace_steps": state.get("trace_steps", []),
        }

    return StreamingResponse(
        _sse_generator(stream_planning, state_dict, result_to_dict),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
