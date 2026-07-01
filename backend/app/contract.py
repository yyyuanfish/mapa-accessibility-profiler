"""
═══════════════════════════════════════════════════════════════════════════════
MAPA API Contract — Backend ↔ Frontend shared type definitions
═══════════════════════════════════════════════════════════════════════════════

This file documents all request/response schemas exchanged between the
Python FastAPI backend and the React frontend.

Mirrors: frontend/src/lib/api-contract.ts (TypeScript side)

Endpoints:
    GET  /api/health          → HealthResponse
    GET  /api/routes           → list[RouteInfo]
    GET  /api/zurich/data      → ZurichDataResponse
    POST /api/audio/transcribe → AudioTranscriptionResponse
    POST /api/profile/turn     → ProfileTurnRequest  → ProfileTurnResponse
    POST /api/profile/stream   → ProfileTurnRequest  → SSE stream
    POST /api/plan             → PlanRequest          → PlanResponse
    POST /api/plan/stream      → PlanRequest          → SSE stream
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── LLM Configuration ─────────────────────────────────────────────────────────

LLMMode = Literal["mock", "ollama"]


class LLMConfig(BaseModel):
    """LLM provider configuration sent with every request."""
    mode: LLMMode = "mock"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "shmily_006/Qw3:4b_4bit"
    ollama_profiler_model: str = ""
    ollama_planner_model: str = ""
    ollama_image_model: str = "llava:7b"
    ollama_timeout: int = 300


# ── GET /api/health ───────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: Literal["ok"]


# ── GET /api/routes ───────────────────────────────────────────────────────────

class RouteInfoContract(BaseModel):
    route_id: str
    name: str
    step_free: bool
    total_distance_m: int
    total_duration_min: int


# ── GET /api/zurich/data ──────────────────────────────────────────────────────

class ZurichDataResponseContract(BaseModel):
    barriers: list[dict[str, Any]]
    toilets: list[dict[str, Any]]
    parking: list[dict[str, Any]]
    barriers_count: int
    toilets_count: int
    parking_count: int
    fetch_errors: list[str]
    center_lat: float
    center_lon: float
    radius_m: float


# ── POST /api/audio/transcribe ────────────────────────────────────────────────

class AudioTranscriptionResponseContract(BaseModel):
    transcript: str
    language: str = "en"
    provider: str
    duration_sec: Optional[float] = None


# ── POST /api/profile/turn ────────────────────────────────────────────────────

class ProfileTurnRequestContract(BaseModel):
    """Request body for /api/profile/turn and /api/profile/stream."""
    user_message: str
    current_patch: Optional[dict[str, Any]] = None
    skipped_domains: list[str] = Field(default_factory=list)
    question_context: Optional[str] = None
    turn_count: int = 1
    language: str = "en"
    consent_to_profile: bool = True
    # LLM config (flattened into request body)
    mode: LLMMode = "mock"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "shmily_006/Qw3:4b_4bit"
    ollama_profiler_model: str = ""
    ollama_planner_model: str = ""
    ollama_image_model: str = "llava:7b"
    ollama_timeout: int = 300


class DomainConfidenceContract(BaseModel):
    vision: float = Field(0.5, ge=0.0, le=1.0)
    hearing: float = Field(0.5, ge=0.0, le=1.0)
    mobility: float = Field(0.5, ge=0.0, le=1.0)
    cognitive: float = Field(0.5, ge=0.0, le=1.0)


class ConfidenceScoresContract(BaseModel):
    overall: float = Field(0.5, ge=0.0, le=1.0)
    per_domain: DomainConfidenceContract = Field(
        default_factory=DomainConfidenceContract
    )


class ProfileTurnResponseContract(BaseModel):
    """Response body for /api/profile/turn."""
    profile_patch: dict[str, Any]
    confidence: ConfidenceScoresContract
    missing_critical_fields: list[str]
    next_question: Optional[str] = None
    next_question_context: Optional[str] = None
    confirmation_text: str = ""
    speech_text: str = ""


# ── POST /api/plan ────────────────────────────────────────────────────────────

class PlanRequestContract(BaseModel):
    """Request body for /api/plan and /api/plan/stream."""
    profile_patch: dict[str, Any]
    route_id: str = "route_with_stairs"
    language: str = "en"
    image_hazards: Optional[dict[str, Any]] = None
    # LLM config (flattened into request body)
    mode: LLMMode = "mock"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "shmily_006/Qw3:4b_4bit"
    ollama_profiler_model: str = ""
    ollama_planner_model: str = ""
    ollama_image_model: str = "llava:7b"
    ollama_timeout: int = 300


class PlanResponseContract(BaseModel):
    """Response body for /api/plan."""
    summary: str
    directions: list[str]
    alerts: list[str]
    checklist: list[str]
    if_you_get_lost: list[str]
    preferences_applied: list[str]
    speech_text: str = ""


# ── SSE Stream Events ─────────────────────────────────────────────────────────
#
# SSE events emitted by /api/profile/stream and /api/plan/stream:
#
#   {"type": "progress", "agent": "<name>", "status": "starting"}
#   {"type": "progress", "agent": "<name>", "status": "done", "duration_ms": N}
#   {"type": "result",   ...response fields...}
#   {"type": "error",    "message": "<msg>"}
