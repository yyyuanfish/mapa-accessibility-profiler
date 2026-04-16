from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OutputMode(str, Enum):
    STANDARD_TEXT = "standard_text"
    SIMPLE_TEXT = "simple_text"
    SIGN_GLOSS_TEXT = "sign_gloss_text"


class VisionNeeds(StrictBaseModel):
    blind_or_low_vision: Optional[bool] = None
    prefers_landmarks: Optional[bool] = None


class HearingNeeds(StrictBaseModel):
    deaf_or_hard_of_hearing: Optional[bool] = None
    sign_language_user: Optional[bool] = None


class MobilityNeeds(StrictBaseModel):
    wheelchair_user: Optional[bool] = None
    needs_step_free_route: Optional[bool] = None
    avoid_long_walks: Optional[bool] = None


class CognitiveNeeds(StrictBaseModel):
    needs_simple_language: Optional[bool] = None
    needs_memory_support: Optional[bool] = None
    reading_or_memory_difficulty_or_child: Optional[bool] = None


class Needs(StrictBaseModel):
    vision: VisionNeeds = Field(default_factory=VisionNeeds)
    hearing: HearingNeeds = Field(default_factory=HearingNeeds)
    mobility: MobilityNeeds = Field(default_factory=MobilityNeeds)
    cognitive: CognitiveNeeds = Field(default_factory=CognitiveNeeds)


class Communication(StrictBaseModel):
    output_mode: OutputMode = OutputMode.STANDARD_TEXT


class Preferences(StrictBaseModel):
    avoid_crowds: Optional[bool] = None
    extra_time_buffer_min: Optional[int] = Field(default=None, ge=0, le=120)


class DomainConfidence(StrictBaseModel):
    vision: float = Field(0.5, ge=0.0, le=1.0)
    hearing: float = Field(0.5, ge=0.0, le=1.0)
    mobility: float = Field(0.5, ge=0.0, le=1.0)
    cognitive: float = Field(0.5, ge=0.0, le=1.0)


class ConfidenceScores(StrictBaseModel):
    overall: float = Field(0.5, ge=0.0, le=1.0)
    per_domain: DomainConfidence = Field(default_factory=DomainConfidence)


class AccessibilityProfile(StrictBaseModel):
    schema_version: str = "accessibility_profile.v1"
    consent_to_profile: bool = True
    needs: Needs = Field(default_factory=Needs)
    communication: Communication = Field(default_factory=Communication)
    preferences: Preferences = Field(default_factory=Preferences)
    confidence: ConfidenceScores = Field(default_factory=ConfidenceScores)


class ProfilePatch(StrictBaseModel):
    needs: Needs = Field(default_factory=Needs)
    communication: Communication = Field(default_factory=Communication)
    preferences: Preferences = Field(default_factory=Preferences)


class ProfilerLLMResponse(StrictBaseModel):
    profile_patch: ProfilePatch = Field(default_factory=ProfilePatch)


class ProfilerAgentOutput(StrictBaseModel):
    profile_patch: ProfilePatch
    confidence: ConfidenceScores
    missing_critical_fields: list[str]
    next_question: Optional[str] = None
    next_question_context: Optional[str] = None
    confirmation_text: str


class RouteStep(StrictBaseModel):
    instruction: str
    distance_m: int = Field(ge=0)
    duration_min: int = Field(ge=0)
    has_stairs: bool = False
    audio_only_cue: bool = False
    landmark: Optional[str] = None


class RawRoute(StrictBaseModel):
    route_id: str
    name: str
    step_free: bool
    total_distance_m: int = Field(ge=0)
    total_duration_min: int = Field(ge=0)
    steps: list[RouteStep]


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ImageHazardsSummary(StrictBaseModel):
    stairs: RiskLevel = RiskLevel.NONE
    slope: RiskLevel = RiskLevel.NONE
    crowd: RiskLevel = RiskLevel.NONE
    scene_summary: str | None = None
    visible_objects: list[str] = Field(default_factory=list)
    accessibility_cues: list[str] = Field(default_factory=list)
    reasoning_steps: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PersonalizedPlan(StrictBaseModel):
    summary: str
    directions: list[str]
    alerts: list[str]
    checklist: list[str]
    if_you_get_lost: list[str]
    preferences_applied: list[str]


class AgentTraceStep(StrictBaseModel):
    agent_name: str
    role: str
    summary: str
    input_keys: list[str] = Field(default_factory=list)
    output_keys: list[str] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)


class AgentTrace(StrictBaseModel):
    workflow: str
    steps: list[AgentTraceStep] = Field(default_factory=list)


class RouteSelectionDecision(StrictBaseModel):
    requested_route_id: str
    requested_route_name: str
    selected_route_id: str
    selected_route_name: str
    switched_to_step_free: bool = False
    reasons: list[str] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)


class HazardFusionSummary(StrictBaseModel):
    source: str
    highlights: list[str] = Field(default_factory=list)


class MultiAgentProfileResult(StrictBaseModel):
    profiler_output: ProfilerAgentOutput
    draft_profile: AccessibilityProfile
    trace: AgentTrace
    agent_reply: str


class MultiAgentPlanResult(StrictBaseModel):
    route_decision: RouteSelectionDecision
    hazard_summary: HazardFusionSummary
    plan: PersonalizedPlan
    trace: AgentTrace
    agent_reply: str
