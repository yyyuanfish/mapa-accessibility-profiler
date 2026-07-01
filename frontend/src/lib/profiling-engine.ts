// Mock multi-agent profiling engine following the pipeline:
// consent_guard_agent -> profiler_agent -> profile_manager_agent -> conversation_orchestrator

import type { AppLanguage } from "./runtime-context";

export interface AccessibilityProfile {
  schema_version: string;
  mobility: {
    wheelchair_user: boolean | null;
    step_free_route: boolean | null;
    limited_walking: boolean | null;
    confidence: number;
  };
  vision: { blind: boolean | null; low_vision: boolean | null; confidence: number };
  hearing: { deaf: boolean | null; hard_of_hearing: boolean | null; sign_language: boolean | null; confidence: number };
  cognitive: { simple_language: boolean | null; memory_support: boolean | null; confidence: number };
  communication_mode: string;
  overall_confidence: number;
}

export interface AgentTrace {
  agent: string;
  action: string;
  result: string;
}

export interface ProfilingTurn {
  question: string;
  questionContext: string;
  field: string;
  agentTraces: AgentTrace[];
}

// Localized question texts (per-language). Context + traces + field stay stable.
const QUESTION_TEXT_BY_LANG: Record<AppLanguage, string[]> = {
  en: [
    "Welcome! I'd like to understand your needs to plan the best journey for you. Do you use a wheelchair or have any mobility considerations?",
    "Do you have any vision-related needs? For example, do you use a screen reader or prefer audio guidance?",
    "How about hearing? Do you prefer visual alerts, sign language, or captions?",
    "Would you prefer simplified instructions or step-by-step guidance? Some people find shorter sentences easier to follow.",
    "Do you have any preferences for how you receive information? (e.g., text, audio, sign language gloss)",
    "Are there any other accessibility needs I should know about for your journey?",
  ],
  zh: [
    "您好！我想了解您的需求，为您规划最合适的行程。您是否使用轮椅或有行动方面的需要？",
    "您有没有视力方面的需求？例如使用屏幕阅读器或更倾向于语音引导？",
    "听力方面呢？您更喜欢视觉提示、手语还是字幕？",
    "您希望使用更简明的说明或一步步的引导吗？有些人觉得短句更容易理解。",
    "您希望以哪种方式接收信息？（例如：文字、语音、手语文本）",
    "还有其他我需要了解的无障碍需求吗？",
  ],
  de: [
    "Willkommen! Ich möchte Ihre Bedürfnisse verstehen, um die beste Route für Sie zu planen. Nutzen Sie einen Rollstuhl oder haben Sie sonstige Mobilitätsbedürfnisse?",
    "Haben Sie Bedürfnisse im Bereich Sehen? Nutzen Sie zum Beispiel einen Screenreader oder bevorzugen Sie Audio-Hinweise?",
    "Und beim Hören? Bevorzugen Sie visuelle Hinweise, Gebärdensprache oder Untertitel?",
    "Hätten Sie lieber einfache Anweisungen oder Schritt-für-Schritt-Anleitungen? Manche Menschen finden kürzere Sätze leichter verständlich.",
    "Wie möchten Sie Informationen erhalten? (z. B. Text, Audio, Gebärdensprach-Text)",
    "Gibt es weitere Barrierefreiheitsbedürfnisse, die ich für Ihre Reise kennen sollte?",
  ],
};

const QUESTION_META: Omit<ProfilingTurn, "question">[] = [
  {
    questionContext: "Assessing mobility needs",
    field: "mobility",
    agentTraces: [
      { agent: "consent_guard_agent", action: "validate_scope", result: "functional_needs_only ✓" },
      { agent: "profiler_agent", action: "generate_question", result: "mobility assessment" },
    ],
  },
  {
    questionContext: "Assessing vision needs",
    field: "vision",
    agentTraces: [
      { agent: "profiler_agent", action: "generate_question", result: "vision assessment" },
      { agent: "profile_manager_agent", action: "validate_patch", result: "schema_valid ✓" },
    ],
  },
  {
    questionContext: "Assessing hearing and communication needs",
    field: "hearing",
    agentTraces: [
      { agent: "profiler_agent", action: "generate_question", result: "hearing assessment" },
      { agent: "consent_guard_agent", action: "check_language", result: "no_diagnosis_terms ✓" },
    ],
  },
  {
    questionContext: "Assessing cognitive support needs",
    field: "cognitive",
    agentTraces: [
      { agent: "profiler_agent", action: "generate_question", result: "cognitive support assessment" },
      { agent: "profile_manager_agent", action: "validate_patch", result: "schema_valid ✓" },
    ],
  },
  {
    questionContext: "Assessing communication preferences",
    field: "communication",
    agentTraces: [
      { agent: "profiler_agent", action: "assess_communication", result: "mode_preference" },
      { agent: "conversation_orchestrator", action: "adapt_output_mode", result: "text_default" },
    ],
  },
  {
    questionContext: "Open-ended catch-all",
    field: "other",
    agentTraces: [
      { agent: "profiler_agent", action: "open_query", result: "additional_needs_check" },
      { agent: "profile_manager_agent", action: "merge_patch", result: "profile_updated ✓" },
    ],
  },
];

export function getProfilingQuestions(language: AppLanguage = "en"): ProfilingTurn[] {
  const texts = QUESTION_TEXT_BY_LANG[language] ?? QUESTION_TEXT_BY_LANG.en;
  return QUESTION_META.map((meta, i) => ({ ...meta, question: texts[i] }));
}

export function parseAnswer(field: string, answer: string): Partial<AccessibilityProfile> {
  const lower = answer.toLowerCase();
  const isYes = /yes|yeah|yep|right|correct|确|是|ja/i.test(lower);
  const isNo = /no|nope|nah|不|否|nein/i.test(lower);
  const isSkip = /skip|pass|跳过|überspringen/i.test(lower);

  if (isSkip) return {};

  switch (field) {
    case "mobility":
      return {
        mobility: {
          wheelchair_user: isYes ? true : isNo ? false : null,
          step_free_route: isYes ? true : isNo ? false : null,
          limited_walking: /cannot walk far|avoid long walks|short walking distance|不能走远|kurze gehstrecke/i.test(lower) ? true : null,
          confidence: isYes || isNo ? 0.85 : 0.3,
        },
      };
    case "vision":
      return {
        vision: {
          blind: /blind|全盲|blind/i.test(lower) ? true : null,
          low_vision: /low.?vision|partial|screen.?reader|弱视/i.test(lower) || isYes ? true : isNo ? false : null,
          confidence: isYes || isNo ? 0.85 : 0.3,
        },
      };
    case "hearing":
      return {
        hearing: {
          deaf: /deaf|聋|taub/i.test(lower) ? true : null,
          hard_of_hearing: isYes ? true : isNo ? false : null,
          sign_language: /sign|手语|gebärden/i.test(lower) ? true : null,
          confidence: isYes || isNo ? 0.8 : 0.3,
        },
      };
    case "cognitive":
      return {
        cognitive: {
          simple_language: isYes ? true : isNo ? false : null,
          memory_support: /memory|remember|记忆|gedächtnis/i.test(lower) ? true : null,
          confidence: isYes || isNo ? 0.8 : 0.3,
        },
      };
    case "communication":
      return {
        communication_mode: /sign/i.test(lower) ? "sign_gloss_text" : /audio/i.test(lower) ? "audio" : "text",
      };
    default:
      return {};
  }
}

export function buildDefaultProfile(): AccessibilityProfile {
  return {
    schema_version: "accessibility_profile",
    mobility: { wheelchair_user: null, step_free_route: null, limited_walking: null, confidence: 0 },
    vision: { blind: null, low_vision: null, confidence: 0 },
    hearing: { deaf: null, hard_of_hearing: null, sign_language: null, confidence: 0 },
    cognitive: { simple_language: null, memory_support: null, confidence: 0 },
    communication_mode: "text",
    overall_confidence: 0,
  };
}

export function mergeProfile(base: AccessibilityProfile, patch: Partial<AccessibilityProfile>): AccessibilityProfile {
  const merged = { ...base };
  if (patch.mobility) merged.mobility = { ...base.mobility, ...patch.mobility };
  if (patch.vision) merged.vision = { ...base.vision, ...patch.vision };
  if (patch.hearing) merged.hearing = { ...base.hearing, ...patch.hearing };
  if (patch.cognitive) merged.cognitive = { ...base.cognitive, ...patch.cognitive };
  if (patch.communication_mode) merged.communication_mode = patch.communication_mode;

  // Recalculate overall confidence
  const confidences = [merged.mobility.confidence, merged.vision.confidence, merged.hearing.confidence, merged.cognitive.confidence];
  const nonZero = confidences.filter(c => c > 0);
  merged.overall_confidence = nonZero.length > 0 ? nonZero.reduce((a, b) => a + b, 0) / nonZero.length : 0;

  return merged;
}

export function getDetectedNeeds(profile: AccessibilityProfile): string[] {
  const needs: string[] = [];
  if (profile.mobility.wheelchair_user) needs.push("Wheelchair User");
  if (profile.mobility.step_free_route) needs.push("Step-free Route");
  if (profile.mobility.limited_walking) needs.push("Limited Walking");
  if (profile.vision.blind) needs.push("Blind");
  if (profile.vision.low_vision) needs.push("Low Vision");
  if (profile.hearing.deaf) needs.push("Deaf");
  if (profile.hearing.hard_of_hearing) needs.push("Hard of Hearing");
  if (profile.hearing.sign_language) needs.push("Sign Language");
  if (profile.cognitive.simple_language) needs.push("Simple Language");
  if (profile.cognitive.memory_support) needs.push("Memory Support");
  return needs;
}

// Route planning (planner_agent)
export interface RoutePlan {
  summary: string;
  directions: string[];
  alerts: string[];
  checklist: string[];
  if_you_get_lost: string;
  preferences_applied: string[];
  speech_text?: string;
  /** [lat, lon] pairs for each step — present when backend returns coords */
  route_coords?: [number, number][];
}

export function generatePlan(profile: AccessibilityProfile, routeId: string = "zurich_hb_to_rathaus"): RoutePlan {
  const plan: RoutePlan = {
    summary: "Personalized accessible route from Zürich HB to Rathaus.",
    directions: [],
    alerts: [],
    checklist: [],
    if_you_get_lost: "Stay where you are and look for the nearest information point with the accessibility symbol.",
    preferences_applied: [],
  };

  const isZurich = routeId.startsWith("zurich_");
  const needsStepFree = profile.mobility.wheelchair_user || profile.mobility.step_free_route;

  // Adapt based on profile and route fixture
  if (isZurich && needsStepFree) {
    plan.summary = "Accessible route from Zürich HB to Rathaus with lifts, flat riverside path, and accessible entrance.";
    plan.directions = [
      "Start inside Zürich Hauptbahnhof and head to the Bahnhofquai lift.",
      "Use the lift to reach street level instead of the stairs near Bahnhofquai.",
      "Continue along the flat Limmatquai riverside path toward Rathaus.",
      "Approach the accessible Rathaus entrance from the riverside ramp.",
    ];
    plan.alerts.push("Open-data context will be checked for barriers near Bahnhofquai and Limmatquai.");
    plan.preferences_applied.push("zurich_step_free_route");
    plan.checklist.push("✅ Confirm the Bahnhofquai lift is operating before departure");
  } else if (isZurich) {
    plan.summary = "Fast route from Zürich HB to Rathaus using the central tram and riverside approach.";
    plan.directions = [
      "Leave Zürich Hauptbahnhof through Bahnhofplatz.",
      "Go toward Bahnhofquai and continue to the central tram access point.",
      "Travel toward Central and continue along Limmatquai.",
      "Walk the last short segment to Rathaus.",
    ];
    plan.alerts.push("Open-data context will be checked for barriers around Bahnhofquai and the Rathaus approach.");
    plan.preferences_applied.push("zurich_fastest_route");
  } else if (profile.mobility.wheelchair_user) {
    plan.directions = [
      "Exit Station A via the step-free ramp on Platform 2.",
      "Follow the tactile path to the lift (elevator).",
      "Take the lift to street level.",
      "Turn right and follow the flat pavement for 200m.",
      "Destination B is on your left — accessible entrance via the side ramp.",
    ];
    plan.alerts.push("⚠️ Construction at Main St — use the accessible detour via Park Lane.");
    plan.preferences_applied.push("step_free_route selected");
    plan.checklist.push("✅ Confirm lift is operational before departure");
  } else {
    plan.directions = [
      "Exit Station A via the main stairs or lift.",
      "Follow signs toward East Exit.",
      "Cross Main Street at the signal crossing.",
      "Walk straight for 300m along the sidewalk.",
      "Destination B entrance is on the right.",
    ];
  }

  if (profile.vision.blind || profile.vision.low_vision) {
    plan.alerts.push("🔊 Audio beacons active at crossings along this route.");
    plan.preferences_applied.push("audio_guidance enabled");
    plan.checklist.push("✅ Enable screen reader for turn-by-turn guidance");
  }

  if (profile.hearing.deaf || profile.hearing.hard_of_hearing) {
    plan.alerts.push("📳 Visual alerts will replace all audio announcements.");
    plan.preferences_applied.push("visual_alerts enabled");
    plan.checklist.push("✅ Enable vibration alerts on your device");
  }

  if (profile.cognitive.simple_language) {
    plan.summary = isZurich
      ? "Easy route from Zürich HB to Rathaus. Follow these short steps."
      : "Easy route from Station A to Place B. Follow the steps below.";
    plan.if_you_get_lost = "Stop. Look for a sign with ℹ️. Ask for help.";
    plan.preferences_applied.push("simple_language enabled");
  }

  plan.speech_text = [plan.summary, ...plan.directions.slice(0, 2), ...plan.alerts.slice(0, 1)]
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();

  return plan;
}
