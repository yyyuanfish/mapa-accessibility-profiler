/**
 * ═══════════════════════════════════════════════════════════════════════════════
 * MAPA API Contract — Frontend ↔ Backend shared type definitions
 * ═══════════════════════════════════════════════════════════════════════════════
 *
 * This file defines all request/response types exchanged between the React
 * frontend and the Python FastAPI backend (backend/app/api.py).
 *
 * Mirrors: backend/app/contract.py (Python side)
 *
 * Endpoints:
 *   GET  /api/health          → HealthResponse
 *   GET  /api/routes           → RouteInfo[]
 *   GET  /api/zurich/data      → ZurichDataResponse
 *   POST /api/audio/transcribe → AudioTranscriptionResponse
 *   POST /api/profile/turn     → ProfileTurnRequest  → ProfileTurnResponse
 *   POST /api/profile/stream   → ProfileTurnRequest  → SSE stream
 *   POST /api/plan             → PlanRequest          → PlanResponse
 *   POST /api/plan/stream      → PlanRequest          → SSE stream
 */

// ── LLM Configuration (sent with every request) ──────────────────────────────

export type LLMMode = "mock" | "ollama";

export interface LLMConfig {
  /** Which LLM provider to use */
  mode: LLMMode;
  /** Ollama base URL (used by backend to talk to Ollama) */
  ollama_url: string;
  /** Ollama model tag, e.g. "shmily_006/Qw3:4b_4bit", "llava:7b" */
  ollama_model: string;
  ollama_profiler_model?: string;
  ollama_planner_model?: string;
  ollama_image_model?: string;
  /** Ollama timeout in seconds */
  ollama_timeout?: number;
}

// ── GET /api/health ──────────────────────────────────────────────────────────

export interface HealthResponse {
  status: "ok";
}

// ── GET /api/routes ──────────────────────────────────────────────────────────

export interface RouteInfo {
  route_id: string;
  name: string;
  step_free: boolean;
  total_distance_m: number;
  total_duration_min: number;
}

// ── GET /api/zurich/data ─────────────────────────────────────────────────────

export interface ZurichBarrierPoint {
  lat: number;
  lon: number;
  category: string;
  severity: number;
  severity_label: string;
  tags: string;
  quartier: string;
  temporary: boolean;
  distance_m: number;
}

export interface ZurichToiletPoint {
  lat: number;
  lon: number;
  name: string;
  address: string;
  category: string;
  wheelchair_accessible: boolean;
  opening_hours: string;
  free: boolean;
  distance_m: number;
}

export interface ZurichParkingPoint {
  lat: number;
  lon: number;
  address: string;
  type: string;
  fee_required: boolean;
  distance_m: number;
}

export interface ZurichDataResponse {
  barriers: ZurichBarrierPoint[];
  toilets: ZurichToiletPoint[];
  parking: ZurichParkingPoint[];
  barriers_count: number;
  toilets_count: number;
  parking_count: number;
  fetch_errors: string[];
  center_lat: number;
  center_lon: number;
  radius_m: number;
}

// ── POST /api/audio/transcribe ───────────────────────────────────────────────

export interface AudioTranscriptionResponse {
  transcript: string;
  language: string;
  provider: string;
  duration_sec?: number | null;
}

// ── POST /api/profile/turn ───────────────────────────────────────────────────

export interface ProfileTurnRequest {
  user_message: string;
  current_patch?: ProfilePatch | null;
  skipped_domains: string[];
  question_context?: string | null;
  turn_count?: number;
  language: string;
  consent_to_profile?: boolean;
  // LLM config (flattened)
  mode: LLMMode;
  ollama_url: string;
  ollama_model: string;
  ollama_profiler_model?: string;
  ollama_planner_model?: string;
  ollama_image_model?: string;
  ollama_timeout?: number;
}

export interface ProfileTurnResponse {
  profile_patch: ProfilePatch;
  confidence: ConfidenceScores;
  missing_critical_fields: string[];
  next_question: string | null;
  next_question_context: string | null;
  confirmation_text: string;
  speech_text: string;
}

// ── POST /api/plan ───────────────────────────────────────────────────────────

export interface PlanRequest {
  profile_patch: ProfilePatch;
  route_id: string;
  language: string;
  image_hazards?: ImageHazardsSummary | null;
  // LLM config (flattened)
  mode: LLMMode;
  ollama_url: string;
  ollama_model: string;
  ollama_profiler_model?: string;
  ollama_planner_model?: string;
  ollama_image_model?: string;
  ollama_timeout?: number;
}

export interface PlanResponse {
  summary: string;
  directions: string[];
  alerts: string[];
  checklist: string[];
  if_you_get_lost: string[];
  preferences_applied: string[];
  speech_text: string;
}

// ── SSE stream events (for /stream endpoints) ────────────────────────────────

export interface SSEProgressEvent {
  type: "progress";
  agent: string;
  status: "starting" | "done";
  duration_ms?: number;
}

export interface SSEResultEvent {
  type: "result";
  [key: string]: unknown;
}

export interface SSEErrorEvent {
  type: "error";
  message: string;
}

export type SSEEvent = SSEProgressEvent | SSEResultEvent | SSEErrorEvent;

// ── Domain models (mirrors backend/app/models.py) ────────────────────────────

export interface VisionNeeds {
  blind_or_low_vision?: boolean | null;
  prefers_landmarks?: boolean | null;
}

export interface HearingNeeds {
  deaf_or_hard_of_hearing?: boolean | null;
  sign_language_user?: boolean | null;
}

export interface MobilityNeeds {
  wheelchair_user?: boolean | null;
  needs_step_free_route?: boolean | null;
  avoid_long_walks?: boolean | null;
}

export interface CognitiveNeeds {
  needs_simple_language?: boolean | null;
  needs_memory_support?: boolean | null;
  reading_or_memory_difficulty_or_child?: boolean | null;
}

export interface Needs {
  vision?: VisionNeeds;
  hearing?: HearingNeeds;
  mobility?: MobilityNeeds;
  cognitive?: CognitiveNeeds;
}

export type OutputMode = "standard_text" | "simple_text" | "sign_gloss_text";

export interface Communication {
  output_mode?: OutputMode;
}

export interface Preferences {
  avoid_crowds?: boolean | null;
  extra_time_buffer_min?: number | null;
}

export interface ProfilePatch {
  needs?: Needs;
  communication?: Communication;
  preferences?: Preferences;
}

export interface DomainConfidence {
  vision: number;
  hearing: number;
  mobility: number;
  cognitive: number;
}

export interface ConfidenceScores {
  overall: number;
  per_domain: DomainConfidence;
}

export type RiskLevel = "none" | "low" | "medium" | "high";

export interface ImageHazardsSummary {
  stairs?: RiskLevel;
  slope?: RiskLevel;
  crowd?: RiskLevel;
  scene_summary?: string | null;
  visible_objects?: string[];
  accessibility_cues?: string[];
}
