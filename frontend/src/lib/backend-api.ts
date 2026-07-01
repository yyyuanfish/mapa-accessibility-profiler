/**
 * API client for the Python FastAPI backend (backend/app/api.py).
 * Translates between the frontend's AccessibilityProfile schema and the
 * backend's nested Pydantic schema.
 */

import { type AccessibilityProfile, type RoutePlan } from "./profiling-engine";
import { type AgentTrace } from "./profiling-engine";

// ── Backend schema types ──────────────────────────────────────────────────────

export interface BackendProfilePatch {
  needs?: {
    vision?: { blind_or_low_vision?: boolean | null; prefers_landmarks?: boolean | null };
    hearing?: { deaf_or_hard_of_hearing?: boolean | null; sign_language_user?: boolean | null };
    mobility?: {
      wheelchair_user?: boolean | null;
      needs_step_free_route?: boolean | null;
      avoid_long_walks?: boolean | null;
    };
    cognitive?: {
      needs_simple_language?: boolean | null;
      needs_memory_support?: boolean | null;
      reading_or_memory_difficulty_or_child?: boolean | null;
    };
  };
  communication?: { output_mode?: string };
  preferences?: { avoid_crowds?: boolean | null; extra_time_buffer_min?: number | null };
}

export interface BackendConfidence {
  overall: number;
  per_domain: { vision: number; hearing: number; mobility: number; cognitive: number };
}

export interface BackendProfileTurnResponse {
  profile_patch: BackendProfilePatch;
  confidence: BackendConfidence;
  missing_critical_fields: string[];
  next_question: string | null;
  next_question_context: string | null;
  confirmation_text: string;
  speech_text: string;
}

export interface BackendPlanResponse {
  summary: string;
  directions: string[];
  alerts: string[];
  checklist: string[];
  if_you_get_lost: string[];
  preferences_applied: string[];
  speech_text: string;
  /** [lat, lon] pairs for each route step, for map rendering */
  route_coords?: number[][];
}

export interface BackendAudioTranscriptionResponse {
  transcript: string;
  language: string;
  provider: string;
  duration_sec?: number | null;
}

export interface BackendRouteInfo {
  route_id: string;
  name: string;
  step_free: boolean;
  total_distance_m: number;
  total_duration_min: number;
}

// ── Schema translators ────────────────────────────────────────────────────────

/** Convert backend ProfilePatch + ConfidenceScores → frontend AccessibilityProfile */
export function backendPatchToFrontendProfile(
  patch: BackendProfilePatch,
  confidence: BackendConfidence
): AccessibilityProfile {
  const v = patch.needs?.vision;
  const h = patch.needs?.hearing;
  const m = patch.needs?.mobility;
  const c = patch.needs?.cognitive;
  const pd = confidence.per_domain;
  const outputMode = patch.communication?.output_mode ?? "standard_text";

  return {
    schema_version: "accessibility_profile",
    mobility: {
      wheelchair_user: m?.wheelchair_user ?? null,
      step_free_route: m?.needs_step_free_route ?? null,
      limited_walking: m?.avoid_long_walks ?? null,
      confidence: pd.mobility,
    },
    vision: {
      blind: v?.blind_or_low_vision ?? null,
      low_vision: v?.blind_or_low_vision ?? null,
      confidence: pd.vision,
    },
    hearing: {
      deaf: h?.deaf_or_hard_of_hearing ?? null,
      hard_of_hearing: h?.deaf_or_hard_of_hearing ?? null,
      sign_language: h?.sign_language_user ?? null,
      confidence: pd.hearing,
    },
    cognitive: {
      simple_language: c?.needs_simple_language ?? null,
      memory_support: c?.needs_memory_support ?? null,
      confidence: pd.cognitive,
    },
    communication_mode:
      outputMode === "sign_gloss_text"
        ? "sign_gloss_text"
        : outputMode === "simple_text"
        ? "simple_text"
        : "text",
    overall_confidence: confidence.overall,
  };
}

/** Convert frontend AccessibilityProfile → backend ProfilePatch */
export function frontendProfileToBackendPatch(
  profile: AccessibilityProfile
): BackendProfilePatch {
  return {
    needs: {
      vision: {
        blind_or_low_vision: profile.vision.blind ?? profile.vision.low_vision,
        prefers_landmarks: profile.vision.blind ?? profile.vision.low_vision,
      },
      hearing: {
        deaf_or_hard_of_hearing:
          profile.hearing.deaf ?? profile.hearing.hard_of_hearing,
        sign_language_user: profile.hearing.sign_language,
      },
      mobility: {
        wheelchair_user: profile.mobility.wheelchair_user,
        needs_step_free_route:
          profile.mobility.step_free_route ?? profile.mobility.wheelchair_user,
        avoid_long_walks: profile.mobility.limited_walking,
      },
      cognitive: {
        needs_simple_language: profile.cognitive.simple_language,
        needs_memory_support: profile.cognitive.memory_support,
        reading_or_memory_difficulty_or_child:
          profile.cognitive.simple_language ?? profile.cognitive.memory_support,
      },
    },
    communication: {
      output_mode:
        profile.communication_mode === "sign_gloss_text"
          ? "sign_gloss_text"
          : profile.communication_mode === "simple_text"
          ? "simple_text"
          : "standard_text",
    },
  };
}

/** Convert backend PersonalizedPlan → frontend RoutePlan */
export function backendPlanToFrontendPlan(plan: BackendPlanResponse): RoutePlan {
  return {
    summary: plan.summary,
    directions: plan.directions,
    alerts: plan.alerts,
    checklist: plan.checklist,
    if_you_get_lost: plan.if_you_get_lost.join(" "),
    preferences_applied: plan.preferences_applied,
    speech_text: plan.speech_text,
    route_coords: plan.route_coords as [number, number][] | undefined,
  };
}

// ── API calls ─────────────────────────────────────────────────────────────────

interface LLMConfig {
  mode: "mock" | "ollama";
  ollamaUrl: string;
  ollamaModel?: string;
  visionModel?: string;
}

async function apiFetch<T>(
  backendUrl: string,
  path: string,
  body: unknown,
  timeoutMs: number = 120_000
): Promise<T> {
  const url = `${backendUrl.replace(/\/$/, "")}${path}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Backend error ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export async function backendProfileTurn(
  backendUrl: string,
  userMessage: string,
  currentPatch: BackendProfilePatch,
  skippedDomains: string[],
  questionContext: string | null,
  turnCount: number,
  language: string,
  llm: LLMConfig
): Promise<BackendProfileTurnResponse & { traces: AgentTrace[] }> {
  const data = await apiFetch<BackendProfileTurnResponse>(
    backendUrl,
    "/api/profile/turn",
    {
      user_message: userMessage,
      current_patch: currentPatch,
      skipped_domains: skippedDomains,
      question_context: questionContext,
      turn_count: turnCount,
      language,
      mode: llm.mode,
      ollama_url: llm.ollamaUrl,
      ollama_model: llm.ollamaModel ?? "shmily_006/Qw3:4b_4bit",
      ollama_profiler_model: llm.ollamaModel ?? "shmily_006/Qw3:4b_4bit",
      ollama_planner_model: llm.ollamaModel ?? "shmily_006/Qw3:4b_4bit",
      ollama_image_model: llm.visionModel ?? "llava:7b",
    }
  );

  const traces: AgentTrace[] = [
    { agent: "profiler_agent", action: "process_turn", result: `backend/${llm.mode}` },
    {
      agent: "profile_manager_agent",
      action: "validate_patch",
      result: `confidence: ${(data.confidence.overall * 100).toFixed(0)}%`,
    },
  ];
  if (data.next_question_context) {
    traces.push({
      agent: "conversation_orchestrator",
      action: "next_question",
      result: data.next_question_context,
    });
  }

  return { ...data, traces };
}

export async function backendCreatePlan(
  backendUrl: string,
  profile: AccessibilityProfile,
  language: string,
  llm: LLMConfig,
  routeId: string = "route_with_stairs"
): Promise<RoutePlan> {
  const patch = frontendProfileToBackendPatch(profile);
  const data = await apiFetch<BackendPlanResponse>(backendUrl, "/api/plan", {
    profile_patch: patch,
    route_id: routeId,
    language,
    mode: llm.mode,
    ollama_url: llm.ollamaUrl,
    ollama_model: llm.ollamaModel ?? "shmily_006/Qw3:4b_4bit",
    ollama_profiler_model: llm.ollamaModel ?? "shmily_006/Qw3:4b_4bit",
    ollama_planner_model: llm.ollamaModel ?? "shmily_006/Qw3:4b_4bit",
    ollama_image_model: llm.visionModel ?? "llava:7b",
  });
  return backendPlanToFrontendPlan(data);
}

export async function backendTranscribeAudio(
  backendUrl: string,
  audioBlob: Blob,
  language: string,
  timeoutMs: number = 120_000,
  speechModel: string = "small",
): Promise<BackendAudioTranscriptionResponse> {
  const url = `${backendUrl.replace(/\/$/, "")}/api/audio/transcribe?language=${encodeURIComponent(language)}&model=${encodeURIComponent(speechModel)}`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": audioBlob.type || "application/octet-stream",
    },
    body: audioBlob,
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Backend error ${res.status}: ${detail}`);
  }
  return res.json() as Promise<BackendAudioTranscriptionResponse>;
}

export async function backendListRoutes(
  backendUrl: string
): Promise<BackendRouteInfo[]> {
  const url = `${backendUrl.replace(/\/$/, "")}/api/routes`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch routes: ${res.statusText}`);
  return res.json() as Promise<BackendRouteInfo[]>;
}

export async function backendHealthCheck(backendUrl: string): Promise<boolean> {
  try {
    const url = `${backendUrl.replace(/\/$/, "")}/api/health`;
    const res = await fetch(url, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}
