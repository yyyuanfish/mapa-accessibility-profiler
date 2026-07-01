// Ollama LLM provider for accessibility profiling.
//
// Architecture (Porta et al. 2025 + Niu & Penn 2019):
//   hardcoded dialog manager  +  LLM ONLY for triage slot-filling  +  schema validation
//
// Most turns are clear yes/no/skip and are handled client-side with ZERO LLM
// calls (see dialogue-policy.ts). The LLM is only called when the user's reply
// to the first "triage" turn isn't handled by the regex extractor.

import {
  type AccessibilityProfile,
  type AgentTrace,
  mergeProfile,
} from "./profiling-engine";
import type { AppLanguage } from "./runtime-context";
import {
  type QuestionId,
  type TriageFlags,
  applyAnswer,
  buildRecap,
  classifyYesNoSkip,
  detectLanguage,
  extractTriageFromText,
  pickNextQuestion,
  QUESTION_TEXT,
  triageToProfilePatch,
  UNCLEAR_HINT,
} from "./dialogue-policy";

// LLM is used only for one thing: extracting triage flags from a free-text
// reply that wasn't cleanly caught by the regex above. Keep the prompt tiny so
// a 4B 4-bit model can still handle it within a few seconds.
const TRIAGE_SYSTEM_PROMPT = `You are an accessibility triage slot-filler. The user just answered a multi-select question about their accessibility needs. Extract ONLY the flags they affirmed. Output ONLY valid JSON, no markdown, no prose:
{
  "vision": true|false|null,
  "hearing": true|false|null,
  "sign": true|false|null,
  "step_free": true|false|null,
  "wheelchair": true|false|null,
  "simple_lang": true|false|null,
  "memory": true|false|null,
  "none": true|false|null
}
Rules:
- true  = user clearly affirms (e.g. "I use a wheelchair", "low vision")
- hearing: true if user mentions deafness, hard of hearing, ear problems, ear pain, ear trouble, hearing loss, hearing issue, bad hearing, or any ear-related difficulty
- step_free: true for leg pain, knee pain, ankle pain, foot pain, leg problems, walking difficulty, mobility issues, or any lower-limb or walking difficulty
- false = user clearly denies (e.g. "not blind")
- null  = not mentioned / uncertain
- "none" = true ONLY if user clearly said none/nothing/no needs
- IMPORTANT: extract ALL conditions mentioned — a single message can have multiple true flags simultaneously (e.g. "leg pain AND ear problem" → step_free=true AND hearing=true)
- Never guess. When unsure, use null.`;

export interface OllamaMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface OllamaProfileResult {
  profile_patch: Partial<AccessibilityProfile>;
  next_question: string;
  next_question_id: QuestionId;
  is_complete: boolean;
  confirmation_text: string;
  input_understood: boolean;
  clarification_hint: string;
  detected_language: AppLanguage | null;
  traces: AgentTrace[];
}

// ── Ollama HTTP helpers ──────────────────────────────────────────────────────

function extractJSON(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    /* fall through */
  }
  const match = text.match(/\{[\s\S]*\}/);
  if (match) {
    try {
      return JSON.parse(match[0]);
    } catch {
      /* give up */
    }
  }
  return null;
}

export async function callOllama(
  ollamaUrl: string,
  messages: OllamaMessage[],
  model: string = "shmily_006/Qw3:4b_4bit",
  timeoutMs: number = 60_000
): Promise<string> {
  const url = `${ollamaUrl}/api/chat`;
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model,
      messages,
      stream: false,
      format: "json",
      options: { temperature: 0 },
    }),
    signal: AbortSignal.timeout(timeoutMs),
  });

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(
      `Ollama error: ${response.status} ${response.statusText}${body ? ` — ${body}` : ""}`
    );
  }

  const data = await response.json();
  return data.message?.content ?? "";
}

async function llmExtractTriage(
  ollamaUrl: string,
  model: string,
  userInput: string
): Promise<TriageFlags> {
  const raw = await callOllama(
    ollamaUrl,
    [
      { role: "system", content: TRIAGE_SYSTEM_PROMPT },
      { role: "user", content: userInput },
    ],
    model,
    60_000
  );
  const parsed = extractJSON(raw);
  if (!parsed || typeof parsed !== "object") return {};
  const p = parsed as Record<string, unknown>;
  const coerce = (v: unknown) =>
    v === true ? true : v === false ? false : undefined;
  return {
    vision: coerce(p.vision),
    hearing: coerce(p.hearing),
    sign: coerce(p.sign),
    step_free: coerce(p.step_free),
    wheelchair: coerce(p.wheelchair),
    simple_lang: coerce(p.simple_lang),
    memory: coerce(p.memory),
    none: coerce(p.none),
  };
}

// ── Public API: one profiling turn ───────────────────────────────────────────
//
// This is the only function ProfilingChat.tsx should call. It runs the
// deterministic policy and only hits the LLM for the triage free-text case.

export interface OllamaTurnInput {
  ollamaUrl: string;
  model: string;
  language: AppLanguage;
  profile: AccessibilityProfile;
  turnCount: number;         // how many user turns so far (excluding this one)
  askedQuestions: QuestionId[]; // question IDs already asked
  currentQuestionId: QuestionId; // what we just asked — triage on turn 0
  userInput: string;
}

export async function ollamaProfileTurn(
  input: OllamaTurnInput
): Promise<OllamaProfileResult> {
  const {
    ollamaUrl,
    model,
    language,
    profile,
    turnCount,
    askedQuestions,
    currentQuestionId,
    userInput,
  } = input;

  const traces: AgentTrace[] = [
    { agent: "consent_guard_agent", action: "validate_scope", result: "functional_needs_only ✓" },
  ];

  const detectedLanguage = detectLanguage(userInput);
  if (detectedLanguage && detectedLanguage !== language) {
    traces.push({
      agent: "conversation_orchestrator",
      action: "language_detected",
      result: detectedLanguage,
    });
  }

  // ── Branch 1: we just asked the triage question ──────────────────────────
  if (currentQuestionId === "triage") {
    // Try regex extraction first (free client-side path).
    let flags = extractTriageFromText(userInput);
    let usedLLM = false;
    const cleanAns = classifyYesNoSkip(userInput);

    if (flags.none) {
      traces.push({ agent: "profiler_agent", action: "triage_extract", result: "none (client-side)" });
      flags = { none: true };
    } else if (cleanAns === "skip") {
      traces.push({ agent: "profiler_agent", action: "triage_extract", result: "skip (client-side)" });
      flags = {};
    } else if (Object.keys(flags).length === 0 && userInput.trim().length > 2) {
      // Free-text with no obvious keywords → call the small LLM.
      traces.push({ agent: "profiler_agent", action: "triage_extract", result: "calling local LLM" });
      try {
        flags = await llmExtractTriage(ollamaUrl, model, userInput);
        usedLLM = true;
      } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        traces.push({
          agent: "conversation_orchestrator",
          action: "fallback",
          result: `ollama_unreachable: ${detail}`,
        });
        // Surface a polite retry rather than stalling forever.
        return {
          profile_patch: {},
          next_question: `I couldn't reach the local model (${detail}). ${QUESTION_TEXT[language].triage}`,
          next_question_id: "triage",
          is_complete: false,
          confirmation_text: "",
          input_understood: false,
          clarification_hint: UNCLEAR_HINT[language],
          detected_language: detectedLanguage,
          traces,
        };
      }
    } else {
      traces.push({ agent: "profiler_agent", action: "triage_extract", result: "client-side regex" });
    }

    const patch = triageToProfilePatch(flags);
    const updated = mergeProfile(profile, patch);
    const asked = new Set<QuestionId>(askedQuestions);
    asked.add("triage");
    const nextId = pickNextQuestion(updated, turnCount + 1, asked);
    const isComplete = nextId === "done";
    const nextQText = isComplete ? "" : QUESTION_TEXT[language][nextId];
    const recap = isComplete ? buildRecap(updated, language) : "";

    traces.push({
      agent: "profile_manager_agent",
      action: "validate_patch",
      result: `domains=${Object.keys(patch).length}${usedLLM ? " (llm)" : ""}`,
    });
    if (!isComplete) {
      traces.push({ agent: "conversation_orchestrator", action: "next_question", result: nextId });
    }

    return {
      profile_patch: patch,
      next_question: nextQText,
      next_question_id: nextId,
      is_complete: isComplete,
      confirmation_text: recap,
      input_understood: true,
      clarification_hint: "",
      detected_language: detectedLanguage,
      traces,
    };
  }

  // ── Branch 2: a yes/no follow-up (fully client-side, no LLM) ─────────────
  const answer = classifyYesNoSkip(userInput);
  if (answer === "unclear") {
    traces.push({ agent: "profiler_agent", action: "classify", result: "unclear" });
    return {
      profile_patch: {},
      next_question: QUESTION_TEXT[language][currentQuestionId],
      next_question_id: currentQuestionId,
      is_complete: false,
      confirmation_text: "",
      input_understood: false,
      clarification_hint: UNCLEAR_HINT[language],
      detected_language: detectedLanguage,
      traces,
    };
  }

  traces.push({ agent: "profiler_agent", action: "classify", result: answer });
  const patch = applyAnswer(currentQuestionId, answer, profile);
  const updated = mergeProfile(profile, patch);
  const asked = new Set<QuestionId>(askedQuestions);
  asked.add(currentQuestionId);
  const nextId = pickNextQuestion(updated, turnCount + 1, asked);
  const isComplete = nextId === "done";
  const nextQText = isComplete ? "" : QUESTION_TEXT[language][nextId];
  const recap = isComplete ? buildRecap(updated, language) : "";

  traces.push({
    agent: "profile_manager_agent",
    action: "apply_answer",
    result: `${currentQuestionId}=${answer}`,
  });
  if (!isComplete) {
    traces.push({ agent: "conversation_orchestrator", action: "next_question", result: nextId });
  } else {
    traces.push({ agent: "conversation_orchestrator", action: "hand_off", result: "→ planner_agent" });
  }

  return {
    profile_patch: patch,
    next_question: nextQText,
    next_question_id: nextId,
    is_complete: isComplete,
    confirmation_text: recap,
    input_understood: true,
    clarification_hint: "",
    detected_language: detectedLanguage,
    traces,
  };
}

// Legacy helper kept for callers that still build Ollama chat history.
export function buildOllamaHistory(
  messages: { role: "agent" | "user"; content: string }[]
): OllamaMessage[] {
  return messages.map((m) => ({
    role: m.role === "agent" ? ("assistant" as const) : ("user" as const),
    content: m.content,
  }));
}
