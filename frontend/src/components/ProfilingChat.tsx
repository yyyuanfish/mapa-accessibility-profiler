import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Send,
  SkipForward,
  Bot,
  User,
  Accessibility,
  ChevronRight,
  Keyboard,
  Mic,
  MicOff,
  Loader2,
  Volume2,
  VolumeX,
  Camera,
  Move,
  X,
} from "lucide-react";
import {
  getProfilingQuestions,
  parseAnswer,
  buildDefaultProfile,
  mergeProfile,
  type AccessibilityProfile,
  type AgentTrace,
} from "@/lib/profiling-engine";
import { useRuntime, t, LANGUAGES, type AppLanguage, type RuntimeMode } from "@/lib/runtime-context";
import {
  backendPatchToFrontendProfile,
  backendProfileTurn,
  frontendProfileToBackendPatch,
} from "@/lib/backend-api";
import {
  QUESTION_TEXT,
  type QuestionId,
  buildRecap,
  classifyYesNoSkip,
  detectLanguage,
  extractTriageFromText,
  triageToProfilePatch,
} from "@/lib/dialogue-policy";
import {
  speakText,
  speakTextTracked,
  stopSpeaking,
} from "@/lib/speech";

interface Message {
  role: "agent" | "user";
  content: string;
  traces?: AgentTrace[];
}

export interface ProfilingSession {
  messages: Message[];
  profile: AccessibilityProfile;
  turnCount: number;
  phase: ConversationPhase;
  step: number;
  currentQuestionId: QuestionId;
  askedQuestions: QuestionId[];
  skippedDomains: string[];
  questionContext: string | null;
  hasInteracted: boolean;
}

interface ProfilingChatProps {
  session?: ProfilingSession | null;
  resumeForRevision?: boolean;
  cameraStream?: MediaStream | null;
  microphoneGranted?: boolean;
  onStopCamera?: () => void;
  onSessionChange?: (session: ProfilingSession) => void;
  onComplete: (profile: AccessibilityProfile) => void;
  onBack: () => void;
}

type ConversationPhase = "profiling" | "confirming" | "revising";
type InputMode = "voice" | "text";

const LANGUAGE_SWITCH_PATTERNS: Record<AppLanguage, RegExp> = {
  en: /^(english|speak english|use english|switch to english|change to english|英语|英文|英文界面)$/i,
  zh: /^(中文|汉语|汉字|说中文|切换中文|换成中文|chinese|use chinese|switch to chinese)$/i,
  de: /^(deutsch|german|auf deutsch|sprich deutsch|switch to german|change to german|德语|德文)$/i,
};

const REVISION_INTENT_RE =
  /^(no|wrong|change|edit|update|fix|not quite|不是|不对|要改|修改|更正|调整|nein|falsch|ändern|aendern|korrigieren)$/i;

interface CameraPreviewProps {
  stream: MediaStream;
  label: string;
  liveLabel: string;
  onClose: () => void;
}

function CameraPreview({ stream, label, liveLabel, onClose }: CameraPreviewProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const dragRef = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const [position, setPosition] = useState({ left: 24, top: 88 });

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  const startDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    dragRef.current = {
      x: event.clientX,
      y: event.clientY,
      left: position.left,
      top: position.top,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const updateDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    const nextLeft = dragRef.current.left + event.clientX - dragRef.current.x;
    const nextTop = dragRef.current.top + event.clientY - dragRef.current.y;
    setPosition({
      left: Math.max(8, Math.min(window.innerWidth - 232, nextLeft)),
      top: Math.max(64, Math.min(window.innerHeight - 188, nextTop)),
    });
  };

  const endDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    dragRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  };

  return (
    <aside
      className="fixed z-50 w-56 rounded-xl border border-border bg-background/95 shadow-xl overflow-hidden"
      style={{ left: position.left, top: position.top }}
    >
      <div
        className="flex items-center justify-between gap-2 px-3 py-2 bg-muted cursor-move select-none"
        onPointerDown={startDrag}
        onPointerMove={updateDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <div className="flex items-center gap-2 text-xs font-medium text-foreground">
          <Move className="w-3.5 h-3.5 text-muted-foreground" />
          <Camera className="w-3.5 h-3.5" />
          {label}
        </div>
        <button
          type="button"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={onClose}
          className="rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-background"
          aria-label="Close camera preview"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="relative aspect-video bg-black">
        <video ref={videoRef} autoPlay muted playsInline className="h-full w-full object-cover" />
        <span className="absolute bottom-2 left-2 rounded-full bg-destructive px-2 py-0.5 text-[10px] font-semibold text-white">
          {liveLabel}
        </span>
      </div>
    </aside>
  );
}

function buildRevisionResumeMessage(language: AppLanguage): Message {
  return {
    role: "agent",
    content: t(language, "chat_revise_prompt"),
    traces: [
      {
        agent: "conversation_orchestrator",
        action: "resume_revision",
        result: "results_to_chat",
      },
    ],
  };
}

function getLanguageSwitchKey(language: AppLanguage): string {
  if (language === "zh") return "chat_switched_zh";
  if (language === "de") return "chat_switched_de";
  return "chat_switched_en";
}

function detectLanguageSwitchIntent(text: string): AppLanguage | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  for (const language of ["en", "zh", "de"] as const) {
    if (LANGUAGE_SWITCH_PATTERNS[language].test(trimmed)) return language;
  }
  return null;
}

function isRevisionIntent(text: string): boolean {
  return REVISION_INTENT_RE.test(text.trim());
}

function buildRouteChoiceMessage(profile: AccessibilityProfile, language: AppLanguage): string {
  const key =
    profile.mobility.wheelchair_user === true || profile.mobility.step_free_route === true
      ? "chat_confirm_route_step_free"
      : "chat_confirm_route_standard";
  return t(language, key);
}

function buildConfirmationMessage(
  profile: AccessibilityProfile,
  language: AppLanguage,
  recapText?: string
): string {
  const summary = recapText || buildRecap(profile, language);
  return `${summary}\n\n${buildRouteChoiceMessage(profile, language)}\n${t(language, "chat_confirm_prompt")}`;
}

function buildOpeningMessage(
  mode: RuntimeMode,
  language: AppLanguage,
  fallbackQuestion: string
): Message {
  if (mode === "backend") {
    return {
      role: "agent",
      content: QUESTION_TEXT[language].triage,
      traces: [
        { agent: "consent_guard_agent", action: "validate_scope", result: "functional_needs_only ✓" },
        { agent: "conversation_orchestrator", action: "runtime", result: "fastapi_profile_pipeline" },
      ],
    };
  }
  return {
    role: "agent",
    content: fallbackQuestion,
    traces: [
      { agent: "consent_guard_agent", action: "validate_scope", result: "functional_needs_only ✓" },
      { agent: "profiler_agent", action: "generate_question", result: "mock question 1" },
    ],
  };
}

function backendContextToQuestionId(context: string | null): QuestionId {
  switch (context) {
    case "mobility_step_free":
    case "mobility_wheelchair":
    case "cognitive_simple":
    case "cognitive_memory":
    case "vision_detail":
    case "triage":
      return context;
    case "hearing_sign":
    case "hearing_signlang":
      return "hearing_signlang";
    case "confirm":
      return "recap";
    default:
      return "triage";
  }
}

// ---------------------------------------------------------------------------
// Waveform bar component
// ---------------------------------------------------------------------------
function WaveformBars({
  data,
  tick,
}: {
  data: Uint8Array;
  tick: number;
}) {
  const hasRealData = data.some((v) => v > 10);
  const count = 18;

  return (
    <div className="flex items-end justify-center gap-[3px] h-10 px-2">
      {Array.from({ length: count }, (_, i) => {
        let height: number;
        if (hasRealData) {
          const idx = Math.floor((i / count) * data.length);
          height = Math.max(3, (data[idx] / 255) * 38);
        } else {
          // Smooth sine-wave animation when no real audio data (Web Speech API)
          height = Math.max(3, Math.abs(Math.sin(tick * 0.06 + i * 0.55)) * 34 + 3);
        }
        return (
          <div
            key={i}
            className="w-[5px] bg-primary rounded-full"
            style={{ height: `${height}px`, transition: hasRealData ? "height 60ms ease" : "none" }}
          />
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
const ProfilingChat = ({
  onComplete,
  onBack,
  session = null,
  resumeForRevision = false,
  cameraStream = null,
  microphoneGranted = false,
  onStopCamera,
  onSessionChange,
}: ProfilingChatProps) => {
  const {
    mode,
    ollamaUrl,
    ollamaModel,
    visionModel,
    backendUrl,
    language,
    setLanguage,
    speechOutputEnabled,
    setSpeechOutputEnabled,
  } = useRuntime();
  const questions = useMemo(() => getProfilingQuestions(language), [language]);

  const initialSession =
    session && resumeForRevision
      ? {
          ...session,
          phase: "revising" as const,
          currentQuestionId: "triage" as const,
          questionContext: null,
          messages:
            session.messages.at(-1)?.content === t(language, "chat_revise_prompt")
              ? session.messages
              : [...session.messages, buildRevisionResumeMessage(language)],
        }
      : session;

  // ── conversation state ────────────────────────────────────────────────────
  const [step, setStep] = useState(initialSession?.step ?? 0);
  const [currentQuestionId, setCurrentQuestionId] = useState<QuestionId>(
    initialSession?.currentQuestionId ?? "triage"
  );
  const [askedQuestions, setAskedQuestions] = useState<QuestionId[]>(
    initialSession?.askedQuestions ?? []
  );
  const [messages, setMessages] = useState<Message[]>(
    initialSession?.messages ?? [buildOpeningMessage(mode, language, questions[0].question)]
  );
  const [input, setInput] = useState("");
  const [profile, setProfile] = useState<AccessibilityProfile>(
    initialSession?.profile ?? buildDefaultProfile()
  );
  const [showTraces, setShowTraces] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [turnCount, setTurnCount] = useState(initialSession?.turnCount ?? 0);
  const [phase, setPhase] = useState<ConversationPhase>(initialSession?.phase ?? "profiling");
  const [hasInteracted, setHasInteracted] = useState(initialSession?.hasInteracted ?? false);
  const [skippedDomains, setSkippedDomains] = useState<string[]>(
    initialSession?.skippedDomains ?? []
  );
  const [questionContext, setQuestionContext] = useState<string | null>(
    initialSession?.questionContext ?? null
  );

  // ── input mode: voice is always the default ───────────────────────────────
  const [inputMode, setInputMode] = useState<InputMode>("voice");

  // ── device capability state ──────────────────────────────────────────────
  const [voiceSupported, setVoiceSupported] = useState(true);
  const [showCameraPreview, setShowCameraPreview] = useState(Boolean(cameraStream));

  // ── waveform ──────────────────────────────────────────────────────────────
  const [waveformData, setWaveformData] = useState<Uint8Array>(new Uint8Array(32));
  const [animTick, setAnimTick] = useState(0);
  const animFrameRef = useRef<number>(0);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);

  // ── TTS highlight state ───────────────────────────────────────────────────
  const [speakingMsgIdx, setSpeakingMsgIdx] = useState<number | null>(null);
  const [speakingRange, setSpeakingRange] = useState<{ start: number; end: number } | null>(null);

  // ── refs ──────────────────────────────────────────────────────────────────
  const bottomRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<any>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  /** Separate audio stream used only for waveform visualization in Web Speech API mode */
  const vizStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const lastSpokenAgentIndexRef = useRef(-1);
  const confirmationProfileRef = useRef<AccessibilityProfile>(profile);

  // ── detect whether browser speech recognition is available ───────────────
  useEffect(() => {
    const SpeechRecognitionAPI =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    setVoiceSupported(Boolean(SpeechRecognitionAPI));
  }, []); // run once

  useEffect(() => {
    setShowCameraPreview(Boolean(cameraStream));
  }, [cameraStream]);

  // ── waveform animation ────────────────────────────────────────────────────
  useEffect(() => {
    if (!isListening) {
      cancelAnimationFrame(animFrameRef.current);
      analyserRef.current?.disconnect();
      try { audioCtxRef.current?.close(); } catch { /* ignore */ }
      analyserRef.current = null;
      audioCtxRef.current = null;
      setWaveformData(new Uint8Array(32));
      return;
    }

    // Use viz stream (Web Speech API parallel mic) or the recorder stream
    const activeStream = vizStreamRef.current ?? mediaStreamRef.current;
    if (activeStream) {
      try {
        const audioCtx = new AudioContext();
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 64;
        const source = audioCtx.createMediaStreamSource(activeStream);
        source.connect(analyser);
        analyserRef.current = analyser;
        audioCtxRef.current = audioCtx;

        const buf = new Uint8Array(analyser.frequencyBinCount);
        const drawFrame = () => {
          animFrameRef.current = requestAnimationFrame(drawFrame);
          analyser.getByteFrequencyData(buf);
          setWaveformData(new Uint8Array(buf));
        };
        drawFrame();
        return () => {
          cancelAnimationFrame(animFrameRef.current);
        };
      } catch {
        // AudioContext not available — fall through to tick animation
      }
    }

    // Fallback: tick-based sine animation
    const tickLoop = () => {
      animFrameRef.current = requestAnimationFrame(() => {
        setAnimTick((t) => t + 1);
        tickLoop();
      });
    };
    tickLoop();
    return () => cancelAnimationFrame(animFrameRef.current);
  }, [isListening]);

  // ── reset opening message on language/mode change ─────────────────────────
  useEffect(() => {
    if (hasInteracted) return;
    // questions is already re-derived from language via useMemo, so questions[0]
    // is the correct localized opener for the current language.
    setMessages([buildOpeningMessage(mode, language, questions[0].question)]);
    setCurrentQuestionId("triage");
    setQuestionContext(null);
  }, [hasInteracted, language, mode, questions]);

  // ── auto-scroll ───────────────────────────────────────────────────────────
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ── cleanup on unmount ────────────────────────────────────────────────────
  const cleanupRecordingStream = useCallback(() => {
    mediaRecorderRef.current = null;
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    audioChunksRef.current = [];
  }, []);

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        mediaRecorderRef.current.stop();
      }
      cleanupRecordingStream();
      vizStreamRef.current?.getTracks().forEach((t) => t.stop());
      vizStreamRef.current = null;
      stopSpeaking();
      cancelAnimationFrame(animFrameRef.current);
      try { audioCtxRef.current?.close(); } catch { /* ignore */ }
    };
  }, [cleanupRecordingStream]);

  // ── TTS: auto-speak new agent messages with word highlight ───────────────
  useEffect(() => {
    if (!speechOutputEnabled) {
      stopSpeaking();
      setSpeakingMsgIdx(null);
      setSpeakingRange(null);
      return;
    }
    const lastIndex = messages.length - 1;
    if (lastIndex <= lastSpokenAgentIndexRef.current) return;
    const latest = messages[lastIndex];
    if (!latest || latest.role !== "agent") return;
    lastSpokenAgentIndexRef.current = lastIndex;
    speakTextTracked(
      latest.content,
      language,
      (ci, cl) => {
        setSpeakingMsgIdx(lastIndex);
        setSpeakingRange({ start: ci, end: ci + cl });
      },
      () => {
        setSpeakingMsgIdx(null);
        setSpeakingRange(null);
      },
    );
  }, [language, messages, speechOutputEnabled]);

  // ── session sync ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!onSessionChange) return;
    onSessionChange({
      messages,
      profile,
      turnCount,
      phase,
      step,
      currentQuestionId,
      askedQuestions,
      skippedDomains,
      questionContext,
      hasInteracted,
    });
  }, [
    askedQuestions, currentQuestionId, hasInteracted,
    messages, onSessionChange, phase, profile, questionContext,
    skippedDomains, step, turnCount,
  ]);

  // ── build active prompt ───────────────────────────────────────────────────
  const buildActivePrompt = useCallback(
    (nextLanguage: AppLanguage): string => {
      if (phase === "confirming") return buildConfirmationMessage(profile, nextLanguage);
      if (phase === "revising") return t(nextLanguage, "chat_revise_prompt");
      if (mode === "backend") return QUESTION_TEXT[nextLanguage][currentQuestionId];
      return questions[Math.min(step, questions.length - 1)].question;
    },
    [currentQuestionId, mode, phase, profile, questions, step]
  );

  // ── confirmation / revision helpers ──────────────────────────────────────
  const requestConfirmation = useCallback(
    (nextProfile: AccessibilityProfile, nextLanguage: AppLanguage, recapText: string, traces: AgentTrace[] = []) => {
      confirmationProfileRef.current = nextProfile;
      const confirmationMessage: Message = {
        role: "agent",
        content: buildConfirmationMessage(nextProfile, nextLanguage, recapText),
        traces: [
          ...traces.filter((trace) => trace.action !== "hand_off"),
          { agent: "conversation_orchestrator", action: "await_confirmation", result: "user_review" },
        ],
      };
      setMessages((prev) => [...prev, confirmationMessage]);
      setPhase("confirming");
    },
    []
  );

  const completeAfterConfirmation = useCallback(
    (confirmedProfile: AccessibilityProfile, confirmedLanguage: AppLanguage) => {
      const confirmedMessage: Message = {
        role: "agent",
        content: t(confirmedLanguage, "chat_confirmed"),
        traces: [
          { agent: "profile_manager_agent", action: "finalize", result: `confidence: ${(confirmedProfile.overall_confidence * 100).toFixed(0)}%` },
          { agent: "conversation_orchestrator", action: "hand_off", result: "→ planner_agent" },
        ],
      };
      setMessages((prev) => [...prev, confirmedMessage]);
      setPhase("profiling");
      setTimeout(() => onComplete(confirmedProfile), 700);
    },
    [onComplete]
  );

  const handleLanguageSwitch = useCallback(
    (nextLanguage: AppLanguage, originalText?: string) => {
      setLanguage(nextLanguage);
      const switchMessage: Message = {
        role: "agent",
        content: `${t(nextLanguage, getLanguageSwitchKey(nextLanguage))}\n\n${buildActivePrompt(nextLanguage)}`,
      };
      setMessages((prev) => [
        ...prev,
        ...(originalText ? [{ role: "user" as const, content: originalText }] : []),
        switchMessage,
      ]);
    },
    [buildActivePrompt, setLanguage]
  );

  // ── mock turn ─────────────────────────────────────────────────────────────
  const advanceTurnMock = useCallback(
    (answer: string, options?: { forceTriage?: boolean }) => {
      const userMsg: Message = { role: "user", content: answer };
      const currentQ = questions[step];
      const patch = options?.forceTriage
        ? triageToProfilePatch(extractTriageFromText(answer))
        : parseAnswer(currentQ.field, answer);
      const updatedProfile = mergeProfile(profile, patch);
      setProfile(updatedProfile);
      setTurnCount((count) => count + 1);
      setMessages((prev) => [...prev, userMsg]);

      if (options?.forceTriage) {
        requestConfirmation(updatedProfile, language, buildRecap(updatedProfile, language));
        return;
      }

      const nextStep = step + 1;
      if (nextStep >= questions.length) {
        requestConfirmation(updatedProfile, language, buildRecap(updatedProfile, language), [
          { agent: "profile_manager_agent", action: "merge_patch", result: "profile_updated ✓" },
        ]);
        return;
      }
      const nextQ = questions[nextStep];
      setStep(nextStep);
      setMessages((prev) => [
        ...prev,
        { role: "agent", content: nextQ.question, traces: nextQ.agentTraces },
      ]);
    },
    [language, profile, questions, requestConfirmation, step]
  );

  // ── backend turn ──────────────────────────────────────────────────────────
  const advanceTurnBackend = useCallback(
    async (answer: string, options?: { forceContext?: string | null }) => {
      const activeQuestionContext =
        options?.forceContext !== undefined ? options.forceContext : questionContext;
      const userMsg: Message = { role: "user", content: answer };
      setMessages((prev) => [...prev, userMsg]);
      setIsThinking(true);

      let effectiveLanguage = language;
      if (turnCount === 0) {
        const detected = detectLanguage(answer);
        if (detected && detected !== language) {
          effectiveLanguage = detected;
          setLanguage(detected);
        }
      }

      try {
        const result = await backendProfileTurn(
          backendUrl,
          answer,
          frontendProfileToBackendPatch(profile),
          skippedDomains,
          activeQuestionContext,
          turnCount + 1,
          effectiveLanguage,
          {
            mode: "mock",
            ollamaUrl,
            ollamaModel,
            visionModel,
          },
        );
        const updatedProfile = backendPatchToFrontendProfile(
          result.profile_patch,
          result.confidence,
        );
        setProfile(updatedProfile);
        setTurnCount((count) => count + 1);
        setQuestionContext(result.next_question_context);
        setCurrentQuestionId(backendContextToQuestionId(result.next_question_context));
        setAskedQuestions((prev) => {
          const nextId = backendContextToQuestionId(activeQuestionContext);
          return prev.includes(nextId) ? prev : [...prev, nextId];
        });

        if (result.next_question_context === "confirm" || !result.next_question) {
          requestConfirmation(
            updatedProfile,
            effectiveLanguage,
            result.confirmation_text || buildRecap(updatedProfile, effectiveLanguage),
            [
              ...result.traces,
              { agent: "profile_manager_agent", action: "finalize", result: `confidence: ${(updatedProfile.overall_confidence * 100).toFixed(0)}%` },
            ],
          );
          return;
        }

        setMessages((prev) => [
          ...prev,
          {
            role: "agent",
            content: result.next_question,
            traces: result.traces,
          },
        ]);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          {
            role: "agent",
            content: "Sorry, I couldn't reach the FastAPI backend. Please check that uvicorn is running.",
            traces: [{ agent: "conversation_orchestrator", action: "error", result: String(err) }],
          },
        ]);
      } finally {
        setIsThinking(false);
      }
    },
    [
      backendUrl,
      language,
      ollamaModel,
      visionModel,
      ollamaUrl,
      profile,
      questionContext,
      requestConfirmation,
      setLanguage,
      skippedDomains,
      turnCount,
    ],
  );

  const dispatchProfilingTurn = useCallback(
    (answer: string, options?: { forceRevision?: boolean }) => {
      if (mode === "backend") return advanceTurnBackend(answer, options?.forceRevision ? { forceContext: null } : undefined);
      return advanceTurnMock(answer, options?.forceRevision ? { forceTriage: true } : undefined);
    },
    [advanceTurnBackend, advanceTurnMock, mode]
  );

  const handleConfirmationReply = useCallback(
    (answer: string) => {
      const classified = classifyYesNoSkip(answer);
      if (classified === "yes") {
        setMessages((prev) => [...prev, { role: "user", content: answer }]);
        setTurnCount((count) => count + 1);
        completeAfterConfirmation(confirmationProfileRef.current, language);
        return;
      }
      if (classified === "no" || isRevisionIntent(answer)) {
        setMessages((prev) => [
          ...prev,
          { role: "user", content: answer },
          {
            role: "agent",
            content: t(language, "chat_revise_prompt"),
            traces: [{ agent: "conversation_orchestrator", action: "request_revision", result: "profile_update" }],
          },
        ]);
        setTurnCount((count) => count + 1);
        setPhase("revising");
        setCurrentQuestionId("triage");
        setQuestionContext(null);
        return;
      }
      setPhase("profiling");
      setCurrentQuestionId("triage");
      setQuestionContext(null);
      void dispatchProfilingTurn(answer, { forceRevision: true });
    },
    [completeAfterConfirmation, dispatchProfilingTurn, language]
  );

  const submitAnswer = useCallback(
    (rawAnswer: string) => {
      const answer = rawAnswer.trim();
      if (!answer || isThinking || isTranscribing) return;
      const switchLanguage = detectLanguageSwitchIntent(answer);
      setInput("");
      setHasInteracted(true);
      if (switchLanguage) { handleLanguageSwitch(switchLanguage, answer); return; }
      if (phase === "confirming") { handleConfirmationReply(answer); return; }
      if (phase === "revising") {
        setPhase("profiling");
        setCurrentQuestionId("triage");
        setQuestionContext(null);
        void dispatchProfilingTurn(answer, { forceRevision: true });
        return;
      }
      void dispatchProfilingTurn(answer);
    },
    [dispatchProfilingTurn, handleConfirmationReply, handleLanguageSwitch, isThinking, isTranscribing, phase]
  );

  const handleTranscriptReady = useCallback(
    (transcript: string) => {
      const normalized = transcript.trim();
      if (!normalized) return;
      if (inputMode === "voice") { submitAnswer(normalized); return; }
      setInput(normalized);
      setHasInteracted(true);
    },
    [inputMode, submitAnswer]
  );

  // ── start / stop listening ────────────────────────────────────────────────
  const startListening = useCallback(async () => {
    // Stop any ongoing TTS before we start recording so the mic doesn't pick
    // up the agent's own voice and the waveform shows only the user's input.
    stopSpeaking();
    setSpeakingMsgIdx(null);
    setSpeakingRange(null);

    // Web Speech API (Mock + Ollama modes)
    const SpeechRecognitionAPI =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognitionAPI) {
      alert("Your browser does not support speech recognition.");
      return;
    }

    if (!microphoneGranted) {
      try {
        const permissionStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        permissionStream.getTracks().forEach((track) => track.stop());
      } catch {
        setVoiceSupported(false);
        return;
      }
    }

    const recognition = new SpeechRecognitionAPI();
    recognition.lang = language === "zh" ? "zh-CN" : language === "de" ? "de-DE" : "en-US";
    recognition.interimResults = true;
    recognition.continuous = false;
    let finalTranscript = "";
    recognition.onresult = (event: SpeechRecognitionEvent) => {
      finalTranscript = Array.from(event.results).map((r) => r[0].transcript).join("");
      setInput(finalTranscript);
    };
    recognition.onend = () => {
      setIsListening(false);
      // Release viz stream when done speaking
      vizStreamRef.current?.getTracks().forEach((t) => t.stop());
      vizStreamRef.current = null;
      handleTranscriptReady(finalTranscript);
    };
    recognition.onerror = () => {
      setIsListening(false);
      vizStreamRef.current?.getTracks().forEach((t) => t.stop());
      vizStreamRef.current = null;
    };
    recognitionRef.current = recognition;
    recognition.start();
    setIsListening(true);

    // Open a parallel mic stream purely for real-time AudioContext visualization
    try {
      const vizStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      vizStreamRef.current = vizStream;
    } catch {
      // permission denied or unavailable — waveform will use sine fallback
    }
  }, [handleTranscriptReady, language, microphoneGranted]);

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    vizStreamRef.current?.getTracks().forEach((t) => t.stop());
    vizStreamRef.current = null;
    setIsListening(false);
  }, []);

  const handleSend = () => submitAnswer(input);

  const handleSkip = () => {
    if (isThinking || phase !== "profiling") return;
    setHasInteracted(true);
    setInput("");
    void dispatchProfilingTurn("skip");
  };

  const handleLanguageButton = (nextLanguage: AppLanguage) => {
    if (nextLanguage === language) return;
    if (!hasInteracted) { setLanguage(nextLanguage); return; }
    handleLanguageSwitch(nextLanguage);
  };

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-background flex flex-col">
      {cameraStream && showCameraPreview && (
        <CameraPreview
          stream={cameraStream}
          label={t(language, "consent_camera")}
          liveLabel={t(language, "camera_live")}
          onClose={() => {
            setShowCameraPreview(false);
            onStopCamera?.();
          }}
        />
      )}

      {/* ── header ──────────────────────────────────────────────────────── */}
      <div className="border-b border-border px-6 py-4">
        <div className="max-w-2xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl gradient-warm flex items-center justify-center">
              <Accessibility className="w-5 h-5 text-primary-foreground" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-foreground">
                {t(language, "chat_title")}
                {mode === "backend" && <span className="text-xs font-normal text-muted-foreground ml-1">(Backend)</span>}
              </h2>
              <p className="text-xs text-muted-foreground">
                {t(language, "chat_turn", { current: turnCount })}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Language selector */}
            <div className="flex items-center gap-1 bg-muted rounded-lg p-0.5">
              {LANGUAGES.map((entry) => (
                <button
                  key={entry.value}
                  onClick={() => handleLanguageButton(entry.value)}
                  aria-label={`Switch language to ${entry.label}`}
                  title={entry.label}
                  className={`text-base px-2 py-1 rounded-md transition-colors ${
                    language === entry.value ? "bg-background shadow-sm" : "opacity-50 hover:opacity-100"
                  }`}
                >
                  {entry.flag}
                </button>
              ))}
            </div>
            {/* TTS toggle */}
            <button
              onClick={() => setSpeechOutputEnabled(!speechOutputEnabled)}
              className="text-xs px-3 py-1.5 rounded-lg bg-muted text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1.5"
            >
              {speechOutputEnabled ? <Volume2 className="w-3.5 h-3.5" /> : <VolumeX className="w-3.5 h-3.5" />}
              <span className="hidden sm:inline">
                {speechOutputEnabled ? t(language, "chat_speech_on") : t(language, "chat_speech_off")}
              </span>
            </button>
            {/* Traces toggle */}
            <button
              onClick={() => setShowTraces(!showTraces)}
              className="text-xs px-3 py-1.5 rounded-lg bg-muted text-muted-foreground hover:text-foreground transition-colors"
            >
              {showTraces ? t(language, "chat_hide_traces") : t(language, "chat_show_traces")}
            </button>
          </div>
        </div>
      </div>

      {/* ── messages ────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-2xl mx-auto space-y-4">
          {messages.map((msg, index) => (
            <div
              key={index}
              className={`flex gap-3 animate-slide-up ${msg.role === "user" ? "justify-end" : ""}`}
            >
              {msg.role === "agent" && (
                <div className="w-8 h-8 rounded-lg gradient-agent flex items-center justify-center shrink-0 mt-1">
                  <Bot className="w-4 h-4 text-primary-foreground" />
                </div>
              )}
              <div className="max-w-[80%] space-y-1">
                <div
                  className={`px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-line ${
                    msg.role === "agent"
                      ? "bg-muted text-foreground rounded-tl-sm"
                      : "bg-primary text-primary-foreground rounded-tr-sm"
                  }`}
                >
                  {msg.role === "agent" && speakingMsgIdx === index && speakingRange ? (
                    <>
                      {msg.content.slice(0, speakingRange.start)}
                      <span className="bg-primary/20 rounded px-0.5 transition-all">
                        {msg.content.slice(speakingRange.start, speakingRange.end)}
                      </span>
                      {msg.content.slice(speakingRange.end)}
                    </>
                  ) : (
                    msg.content
                  )}
                </div>
                {/* ── per-message speaker: tap to speak / tap again to stop ── */}
                {msg.role === "agent" && (
                  <button
                    onClick={() => {
                      if (speakingMsgIdx === index) {
                        // Already speaking this message — stop it.
                        stopSpeaking();
                        setSpeakingMsgIdx(null);
                        setSpeakingRange(null);
                      } else {
                        // Start speaking this message with word highlight.
                        speakTextTracked(
                          msg.content,
                          language,
                          (ci, cl) => {
                            setSpeakingMsgIdx(index);
                            setSpeakingRange({ start: ci, end: ci + cl });
                          },
                          () => {
                            setSpeakingMsgIdx(null);
                            setSpeakingRange(null);
                          },
                        );
                      }
                    }}
                    title={speakingMsgIdx === index ? t(language, "chat_speech_stop") : t(language, "chat_speech_replay")}
                    aria-label={speakingMsgIdx === index ? "Stop speaking" : "Speak this message"}
                    className={`ml-1 p-1 transition-colors rounded ${
                      speakingMsgIdx === index
                        ? "text-primary hover:text-primary/70"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {speakingMsgIdx === index
                      ? <VolumeX className="w-3.5 h-3.5" />
                      : <Volume2 className="w-3.5 h-3.5" />
                    }
                  </button>
                )}
                {/* ── agent traces ── */}
                {showTraces && msg.traces && (
                  <div className="space-y-1 pl-2">
                    {msg.traces.map((trace, ti) => (
                      <div key={ti} className="flex items-center gap-2 text-xs text-muted-foreground">
                        <ChevronRight className="w-3 h-3" />
                        <span className="font-mono gradient-agent bg-clip-text text-transparent font-medium">
                          {trace.agent}
                        </span>
                        <span>→ {trace.action}: {trace.result}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              {msg.role === "user" && (
                <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center shrink-0 mt-1">
                  <User className="w-4 h-4 text-accent-foreground" />
                </div>
              )}
            </div>
          ))}

          {isThinking && (
            <div className="flex gap-3 animate-slide-up">
              <div className="w-8 h-8 rounded-lg gradient-agent flex items-center justify-center shrink-0 mt-1">
                <Bot className="w-4 h-4 text-primary-foreground" />
              </div>
              <div className="px-4 py-3 rounded-2xl rounded-tl-sm bg-muted text-muted-foreground text-sm flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                {t(language, "chat_thinking")}
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* ── input area ──────────────────────────────────────────────────── */}
      <div className="border-t border-border px-6 py-4">
        <div className="max-w-2xl mx-auto space-y-3">

          {/* ── mode toggle + skip ── */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 rounded-xl bg-muted p-1">
              <button
                onClick={() => setInputMode("voice")}
                className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs transition-colors ${
                  inputMode === "voice"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Mic className="w-3.5 h-3.5" />
                {t(language, "chat_input_voice")}
              </button>
              <button
                onClick={() => setInputMode("text")}
                className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs transition-colors ${
                  inputMode === "text"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Keyboard className="w-3.5 h-3.5" />
                {t(language, "chat_input_text")}
              </button>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleSkip}
              disabled={isThinking || isTranscribing || phase !== "profiling"}
              className="shrink-0"
            >
              <SkipForward className="w-4 h-4 mr-1" />
              {t(language, "chat_skip")}
            </Button>
            {/* Mic status indicator */}
            {!voiceSupported && inputMode === "voice" && (
              <span className="text-xs text-muted-foreground">
                {t(language, "chat_voice_unsupported")}
              </span>
            )}
          </div>

          {/* ── voice input ── */}
          {inputMode === "voice" && (
            <div className="flex flex-col items-center gap-3 py-2">
              {isListening ? (
                <>
                  <WaveformBars data={waveformData} tick={animTick} />
                  <button
                    onClick={stopListening}
                    className="w-16 h-16 rounded-full bg-destructive flex items-center justify-center shadow-lg hover:bg-destructive/90 active:scale-95 transition-all"
                  >
                    <MicOff className="w-7 h-7 text-white" />
                  </button>
                  <p className="text-xs text-muted-foreground">{t(language, "chat_recording")}</p>
                </>
              ) : isTranscribing ? (
                <div className="flex flex-col items-center gap-2 py-3">
                  <Loader2 className="w-8 h-8 animate-spin text-primary" />
                  <p className="text-xs text-muted-foreground">{t(language, "chat_transcribing")}</p>
                </div>
              ) : (
                <button
                  onClick={startListening}
                  disabled={isThinking || isTranscribing || !voiceSupported}
                  className="w-16 h-16 rounded-full gradient-warm flex items-center justify-center shadow-lg hover:opacity-90 active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Mic className="w-7 h-7 text-white" />
                </button>
              )}
            </div>
          )}

          {/* ── text input ── */}
          {inputMode === "text" && (
            <div className="flex gap-2">
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSend()}
                placeholder={t(language, "chat_placeholder")}
                className="rounded-xl"
                disabled={isTranscribing}
                autoFocus
              />
              <Button
                size="icon"
                onClick={handleSend}
                disabled={isThinking || isTranscribing}
                className="shrink-0 rounded-xl"
              >
                <Send className="w-4 h-4" />
              </Button>
            </div>
          )}

          {/* ── footer ── */}
          <div className="flex justify-between items-center">
            <button
              onClick={onBack}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              {t(language, "chat_back")}
            </button>
            <span className="text-xs text-muted-foreground">{t(language, "chat_no_data")}</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ProfilingChat;
