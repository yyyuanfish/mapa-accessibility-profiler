// Deterministic dialogue policy for accessibility profiling.
//
// Pattern (per Porta et al. 2025 "Modular LLM Dialog" + Niu & Penn 2019
// "Rationally Reappraising ATIS"): hardcoded dialog manager + small-LLM slot
// extraction + schema validation. This module is the hardcoded half.
//
//  • Turn 0       — triage: high-density multi-select question
//  • Turn 1+      — adaptive follow-ups, only on hit/uncertain branches
//  • Hardcoded yes/no/skip classification in en/zh/de (no LLM)
//  • Each question explicitly says "answer yes or no only"
//  • Route-critical stopping: done when we have enough for planning,
//    even if not all four domains are filled.

import type { AccessibilityProfile } from "./profiling-engine";
import type { AppLanguage } from "./runtime-context";

// ── Question bank ────────────────────────────────────────────────────────────

export type QuestionId =
  | "triage"
  | "mobility_step_free"
  | "mobility_wheelchair"
  | "hearing_signlang"
  | "cognitive_simple"
  | "cognitive_memory"
  | "vision_detail"
  | "recap"
  | "done";

export const QUESTION_TEXT: Record<AppLanguage, Record<QuestionId, string>> = {
  en: {
    triage:
      "To match a route quickly, tell me which apply — you can list several at once, or say 'none' or 'skip':\n• vision / screen reader\n• hearing / captions / sign language\n• step-free route / wheelchair\n• simple language / reminders",
    mobility_step_free:
      "Do you need a step-free route (no stairs)? Please answer yes or no.",
    mobility_wheelchair:
      "Do you use a wheelchair? Please answer yes or no.",
    hearing_signlang:
      "Would you prefer sign-language style text output? Please answer yes or no.",
    cognitive_simple:
      "Would simple language and shorter sentences help you? Please answer yes or no.",
    cognitive_memory:
      "Would memory reminders along the route help you? Please answer yes or no.",
    vision_detail:
      "Do you use a screen reader or prefer audio guidance? Please answer yes or no.",
    recap: "",
    done: "",
  },
  zh: {
    triage:
      "为了更快匹配路线，请告诉我哪些适用——可以一次说多个，或回答“都不需要”/“跳过”：\n• 视觉 / 屏幕阅读\n• 听力 / 字幕 / 手语\n• 无台阶路线 / 轮椅\n• 简明语言 / 提醒",
    mobility_step_free: "你需要无台阶路线（不走楼梯）吗？请回答“是”或“否”。",
    mobility_wheelchair: "你使用轮椅吗？请回答“是”或“否”。",
    hearing_signlang: "你希望使用手语风格文本输出吗？请回答“是”或“否”。",
    cognitive_simple: "简明语言与较短句子对你有帮助吗？请回答“是”或“否”。",
    cognitive_memory: "路线中的记忆提醒对你有帮助吗？请回答“是”或“否”。",
    vision_detail: "你使用屏幕阅读器或更喜欢语音引导吗？请回答“是”或“否”。",
    recap: "",
    done: "",
  },
  de: {
    triage:
      "Um schnell eine passende Route zu finden, sagen Sie mir, was zutrifft — Sie können mehreres auf einmal nennen oder „nichts“ / „überspringen“ sagen:\n• Sehen / Bildschirmleser\n• Hören / Untertitel / Gebärdensprache\n• Stufenfreie Route / Rollstuhl\n• Einfache Sprache / Erinnerungen",
    mobility_step_free:
      "Benötigen Sie eine stufenfreie Route (ohne Treppen)? Bitte antworten Sie mit ja oder nein.",
    mobility_wheelchair:
      "Nutzen Sie einen Rollstuhl? Bitte antworten Sie mit ja oder nein.",
    hearing_signlang:
      "Möchten Sie eine gebärdensprachnahe Textausgabe? Bitte antworten Sie mit ja oder nein.",
    cognitive_simple:
      "Würden einfache Sprache und kürzere Sätze Ihnen helfen? Bitte antworten Sie mit ja oder nein.",
    cognitive_memory:
      "Würden Erinnerungshilfen entlang der Route Ihnen helfen? Bitte antworten Sie mit ja oder nein.",
    vision_detail:
      "Nutzen Sie einen Bildschirmleser oder bevorzugen Sie Audio-Anleitung? Bitte antworten Sie mit ja oder nein.",
    recap: "",
    done: "",
  },
};

export const RECAP_PREFIX: Record<AppLanguage, string> = {
  en: "Here is what I understood:",
  zh: "好的——我了解到的是：",
  de: "Verstanden — das habe ich notiert:",
};

export const RECAP_SUFFIX: Record<AppLanguage, string> = {
  en: "Please confirm this before I plan your route.",
  zh: "请先确认这些信息，我再为你规划路线。",
  de: "Bitte bestätigen Sie dies, bevor ich Ihre Route plane.",
};

export const NO_NEEDS_NOTE: Record<AppLanguage, string> = {
  en: "No specific accessibility preferences noted. I'll use a standard route.",
  zh: "未记录特定无障碍偏好。我将使用标准路线。",
  de: "Keine speziellen Barrierefreiheits-Präferenzen notiert. Ich verwende eine Standardroute.",
};

export const UNCLEAR_HINT: Record<AppLanguage, string> = {
  en: "Sorry, I didn't catch that — please answer yes or no (or skip).",
  zh: "抱歉，我没听懂——请回答“是”或“否”（或“跳过”）。",
  de: "Entschuldigung, das habe ich nicht verstanden — bitte ja oder nein (oder überspringen).",
};

// ── Yes/no/skip classifier (tri-lingual) ─────────────────────────────────────

export type YesNoSkip = "yes" | "no" | "skip" | "unclear";

const YES_RE =
  /^(y|yes|yeah|yep|yup|sure|ok|okay|是|是的|对|对的|有|要|需要|好|好的|ja|j|jep|jo)[\s\.!。！]*$/i;
const NO_RE =
  /^(n|no|nope|nah|不|不是|不用|不要|不需要|没|没有|没事|nein|nee|nö|noe)[\s\.!。！]*$/i;
const SKIP_RE =
  /^(skip|pass|none|n\/a|跳过|不说|略过|都不需要|没有|überspringen|ueberspringen|uberspringen|keine|nichts)[\s\.!。！]*$/i;

export function classifyYesNoSkip(text: string): YesNoSkip {
  const t = text.trim();
  if (!t) return "unclear";
  if (SKIP_RE.test(t)) return "skip";
  if (YES_RE.test(t)) return "yes";
  if (NO_RE.test(t)) return "no";
  return "unclear";
}

// ── Language auto-detect from the user's first reply ─────────────────────────

const ZH_RE = /[\u4e00-\u9fff]/;
const DE_HINTS =
  /\b(ja|nein|danke|bitte|ich|mein|brauche|rollstuhl|stufenfrei|gebärden|sehbehindert|einfache|überspringen|keine)\b/i;
const EN_HINTS =
  /\b(yes|no|hi|hello|wheelchair|blind|deaf|simple|skip|none|need)\b/i;

export function detectLanguage(text: string): AppLanguage | null {
  const t = text.trim();
  if (!t) return null;
  if (ZH_RE.test(t)) return "zh";
  if (DE_HINTS.test(t)) return "de";
  if (EN_HINTS.test(t)) return "en";
  return null;
}

// ── Triage free-text extractor (no LLM needed for common cases) ──────────────

export interface TriageFlags {
  vision?: boolean;
  hearing?: boolean;
  sign?: boolean;
  step_free?: boolean;
  wheelchair?: boolean;
  simple_lang?: boolean;
  memory?: boolean;
  none?: boolean;
}

const RE = {
  vision:
    /(blind|low.?vision|screen.?reader|audio.?guid|盲|低视力|弱视|屏幕阅读|语音引导|sehbehindert|bildschirmleser|audio)/i,
  hearing:
    /(deaf|hard.?of.?hearing|hoh|caption|subtitle|ear.?problem|ear.?issues?|ear.?trouble|hearing.?problem|hearing.?issues?|bad.?hearing|字幕|聋|重听|听障|耳朵有问题|耳朵不好|听力问题|taub|schwerhörig|schwerhoerig|untertitel|hörproblem|hörprobleme)/i,
  sign:
    /(sign.?language|\basl\b|\bbsl\b|手语|手語|gebärden|gebaerden)/i,
  step_free:
    /(step.?free|no.?stairs|avoid.?stairs|elevator|ramp|mobility.?support|mobility.?issue|mobility.?problem|leg.?problem|leg.?pain|knee.?pain|ankle.?pain|foot.?pain|hip.?pain|pain.?in.?(my.?)?(leg|knee|ankle|foot|hip)|problems?.?with.?my.?legs|walking.?difficult|difficulty.?walking|can't.?walk.?far|cannot.?walk.?far|无台阶|无楼梯|电梯|坡道|腿.?有问题|腿.?痛|膝盖.?痛|腿脚不便|行动不便|走路困难|stufenfrei|keine.?treppen|aufzug|rampe|mobilit[aä]tsproblem|gehproblem|beinprobleme|schlecht.?laufen|beinschmerzen|knieschmerzen)/i,
  wheelchair:
    /(wheelchair|power.?chair|walker|mobility.?aid|轮椅|助行|rollstuhl|gehhilfe)/i,
  simple_lang:
    /(simple.?(language|english|chinese|german)|easy.?read|plain.?language|short.?sentence|short.?instruction|keep.?instructions?.?short|trouble.?reading|difficulty.?reading|reading.?difficult|hard.?to.?read|long.?texts?|long.?paragraphs?|简明|通俗|易读|leichte.?sprache|einfache.?sprache)/i,
  memory:
    /(reminder|remind.?me|memory|forget|提醒|记忆|容易忘|erinnerung|gedächtnis|gedaechtnis|vergess)/i,
  none:
    /^(none|nothing|no.?need|no.?preferenc|都不|都没有|都不需要|没有需求|keine|nichts|kein bedarf)[\s\.!。！]*$/i,
};

export function extractTriageFromText(text: string): TriageFlags {
  const t = text.trim();
  if (!t) return {};
  const f: TriageFlags = {};
  if (RE.none.test(t)) {
    f.none = true;
    return f;
  }
  if (RE.vision.test(t)) f.vision = true;
  if (RE.hearing.test(t)) f.hearing = true;
  if (RE.sign.test(t)) {
    f.hearing = true;
    f.sign = true;
  }
  if (RE.step_free.test(t)) f.step_free = true;
  if (RE.wheelchair.test(t)) {
    f.wheelchair = true;
    f.step_free = true; // wheelchair implies step-free
  }
  if (RE.simple_lang.test(t)) f.simple_lang = true;
  if (RE.memory.test(t)) f.memory = true;
  return f;
}

// ── Apply triage flags → AccessibilityProfile patch ──────────────────────────

export function triageToProfilePatch(
  flags: TriageFlags
): Partial<AccessibilityProfile> {
  const patch: Partial<AccessibilityProfile> = {};
  if (flags.none) {
    patch.mobility = { wheelchair_user: false, step_free_route: false, limited_walking: false, confidence: 0.7 };
    patch.vision = { blind: false, low_vision: false, confidence: 0.7 };
    patch.hearing = { deaf: false, hard_of_hearing: false, sign_language: false, confidence: 0.7 };
    patch.cognitive = { simple_language: false, memory_support: false, confidence: 0.7 };
    return patch;
  }
  if (flags.wheelchair !== undefined || flags.step_free !== undefined) {
    patch.mobility = {
      wheelchair_user: flags.wheelchair ?? null,
      step_free_route: flags.step_free ? true : null,
      limited_walking: null,
      confidence: 0.75,
    };
  }
  if (flags.vision !== undefined) {
    patch.vision = {
      blind: null,
      low_vision: flags.vision ? true : null,
      confidence: 0.7,
    };
  }
  if (flags.hearing !== undefined || flags.sign !== undefined) {
    patch.hearing = {
      deaf: null,
      hard_of_hearing: flags.hearing ? true : null,
      sign_language: flags.sign ?? null,
      confidence: 0.75,
    };
  }
  if (flags.simple_lang !== undefined || flags.memory !== undefined) {
    patch.cognitive = {
      simple_language: flags.simple_lang ?? null,
      memory_support: flags.memory ?? null,
      confidence: 0.75,
    };
    if (flags.sign) patch.communication_mode = "sign_gloss_text";
    else if (flags.simple_lang) patch.communication_mode = "simple_text";
  } else if (flags.sign) {
    patch.communication_mode = "sign_gloss_text";
  }
  return patch;
}

// ── Apply a yes/no answer to a single follow-up question ─────────────────────

export function applyAnswer(
  questionId: QuestionId,
  ans: YesNoSkip,
  profile: AccessibilityProfile
): Partial<AccessibilityProfile> {
  if (ans === "unclear") return {};
  const yes = ans === "yes";
  const known = ans !== "skip";
  const val = (b: boolean) => (known ? b : null);

  switch (questionId) {
    case "mobility_step_free":
      return {
        mobility: {
          wheelchair_user: profile.mobility.wheelchair_user,
          step_free_route: val(yes),
          limited_walking: profile.mobility.limited_walking,
          confidence: Math.max(profile.mobility.confidence, 0.75),
        },
      };
    case "mobility_wheelchair":
      return {
        mobility: {
          wheelchair_user: val(yes),
          step_free_route: yes ? true : profile.mobility.step_free_route,
          limited_walking: profile.mobility.limited_walking,
          confidence: Math.max(profile.mobility.confidence, 0.8),
        },
      };
    case "hearing_signlang":
      return {
        hearing: {
          deaf: profile.hearing.deaf,
          hard_of_hearing: profile.hearing.hard_of_hearing,
          sign_language: val(yes),
          confidence: Math.max(profile.hearing.confidence, 0.8),
        },
        ...(known && yes ? { communication_mode: "sign_gloss_text" } : {}),
      };
    case "cognitive_simple":
      return {
        cognitive: {
          simple_language: val(yes),
          memory_support: profile.cognitive.memory_support,
          confidence: Math.max(profile.cognitive.confidence, 0.75),
        },
        ...(known && yes ? { communication_mode: "simple_text" } : {}),
      };
    case "cognitive_memory":
      return {
        cognitive: {
          simple_language: profile.cognitive.simple_language,
          memory_support: val(yes),
          confidence: Math.max(profile.cognitive.confidence, 0.75),
        },
      };
    case "vision_detail":
      return {
        vision: {
          blind: profile.vision.blind,
          low_vision: val(yes),
          confidence: Math.max(profile.vision.confidence, 0.75),
        },
      };
    default:
      return {};
  }
}

// ── Next-question policy (adaptive; route-critical first) ────────────────────
//
// Rules (per expert review):
//   • Follow up only on HIT or uncertain branches
//   • Route-critical priority: step_free  >  sign_language  >  simple_language
//   • If nothing positive after triage → go straight to recap
//   • Cap at MAX_FOLLOWUPS rounds regardless

const MAX_FOLLOWUPS = 5;

export function pickNextQuestion(
  profile: AccessibilityProfile,
  turnCount: number,
  asked: Set<QuestionId>
): QuestionId {
  // Turn 0 is always triage.
  if (turnCount === 0 && !asked.has("triage")) return "triage";

  // Route-critical follow-ups, in priority order.
  // mobility: if user mentioned wheelchair but not step-free yet, pin it down
  const m = profile.mobility;
  if (
    !asked.has("mobility_step_free") &&
    (m.wheelchair_user === true || m.limited_walking === true) &&
    m.step_free_route === null
  ) {
    return "mobility_step_free";
  }
  if (
    !asked.has("mobility_wheelchair") &&
    m.step_free_route === true &&
    m.wheelchair_user === null
  ) {
    return "mobility_wheelchair";
  }

  // hearing → sign preference only if hearing support was indicated
  const h = profile.hearing;
  const hearingHit =
    h.deaf === true || h.hard_of_hearing === true || h.sign_language === true;
  if (!asked.has("hearing_signlang") && hearingHit && h.sign_language === null) {
    return "hearing_signlang";
  }

  // cognitive: split simple-language from memory reminders
  const c = profile.cognitive;
  const cognitiveHit = c.simple_language === true || c.memory_support === true;
  if (!asked.has("cognitive_simple") && cognitiveHit && c.simple_language === null) {
    return "cognitive_simple";
  }
  if (!asked.has("cognitive_memory") && cognitiveHit && c.memory_support === null) {
    return "cognitive_memory";
  }

  // vision: only follow up if user mentioned it
  const v = profile.vision;
  const visionHit = v.blind === true || v.low_vision === true;
  if (!asked.has("vision_detail") && visionHit && v.low_vision === null) {
    return "vision_detail";
  }

  // Budget ceiling — don't over-ask.
  if (turnCount >= MAX_FOLLOWUPS) return "done";

  return "done";
}

// ── Recap builder (diff-aware) ───────────────────────────────────────────────

export function buildRecap(
  profile: AccessibilityProfile,
  language: AppLanguage
): string {
  const parts: string[] = [];
  if (profile.mobility.wheelchair_user === true)
    parts.push({ en: "wheelchair user", zh: "使用轮椅", de: "Rollstuhl" }[language]);
  if (profile.mobility.step_free_route === true)
    parts.push({ en: "step-free routing", zh: "无台阶路线", de: "stufenfreie Route" }[language]);
  if (profile.vision.blind === true || profile.vision.low_vision === true)
    parts.push({ en: "vision support", zh: "视觉支持", de: "Seh-Unterstützung" }[language]);
  if (profile.hearing.deaf === true || profile.hearing.hard_of_hearing === true)
    parts.push({ en: "hearing support", zh: "听力支持", de: "Hör-Unterstützung" }[language]);
  if (profile.hearing.sign_language === true)
    parts.push({ en: "sign-language style output", zh: "手语风格输出", de: "gebärdensprachnahe Ausgabe" }[language]);
  if (profile.cognitive.simple_language === true)
    parts.push({ en: "simple language", zh: "简明语言", de: "einfache Sprache" }[language]);
  if (profile.cognitive.memory_support === true)
    parts.push({ en: "memory reminders", zh: "记忆提醒", de: "Erinnerungshilfen" }[language]);

  if (parts.length === 0) {
    return `${NO_NEEDS_NOTE[language]} ${RECAP_SUFFIX[language]}`;
  }

  const joiner = language === "zh" ? "、" : ", ";
  return `${RECAP_PREFIX[language]} ${parts.join(joiner)}. ${RECAP_SUFFIX[language]}`;
}
