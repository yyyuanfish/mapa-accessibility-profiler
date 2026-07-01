import type { AppLanguage } from "./runtime-context";

function toSpeechLanguage(language: AppLanguage): string {
  if (language === "zh") return "zh-CN";
  if (language === "de") return "de-DE";
  return "en-US";
}

// Preferred female voice names by platform (checked case-insensitively).
// macOS/iOS voices come first; Google/Microsoft voices follow.
const FEMALE_VOICE_NAMES: Partial<Record<AppLanguage, string[]>> = {
  en: [
    "Samantha", "Victoria", "Karen", "Fiona", "Moira", "Tessa",   // macOS/iOS
    "Microsoft Zira", "Microsoft Jenny", "Google US English",       // Windows/Chrome
    "Google UK English Female",
  ],
  zh: [
    "Ting-Ting", "Sin-Ji", "Mei-Jia",                              // macOS
    "Microsoft Yaoyao", "Google 普通话（中国大陆）",
  ],
  de: [
    "Anna", "Microsoft Hedda",                                      // macOS/Windows
    "Google Deutsch",
  ],
};

// High-quality voice name patterns (Premium / Enhanced / Natural / Neural).
// These sound close to ChatGPT / Doubao and should be tried first.
const NATURAL_VOICE_PATTERNS: RegExp[] = [
  // macOS Premium / Enhanced voices (most human-sounding on Mac)
  /ava.*premium/i,   /samantha.*enhanced/i, /allison.*enhanced/i,
  /serena.*premium/i, /susan.*enhanced/i,   /karen.*enhanced/i,
  /victoria.*premium/i, /moira.*enhanced/i,
  // Windows / Azure Neural / Natural voices
  /jenny.*natural/i, /jenny.*neural/i,
  /aria.*natural/i,  /aria.*neural/i,
  /sonia.*natural/i, /emily.*natural/i, /libby.*natural/i,
  /xiaoxiao/i,       /xiaoyi/i,         /yunxi/i,   // Azure ZH neural
  /katja.*neural/i,  /amala.*neural/i,              // DE neural
  // Generic quality markers
  /(premium|enhanced|natural|neural)/i,
];

function pickFemaleVoice(lang: AppLanguage): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return null;

  const langTag = toSpeechLanguage(lang);
  const langPrefix = langTag.split("-")[0];
  const preferred = FEMALE_VOICE_NAMES[lang] ?? [];

  // 0. Premium / Enhanced / Natural / Neural voices — most human-sounding
  for (const pat of NATURAL_VOICE_PATTERNS) {
    const v = voices.find((v) => pat.test(v.name) && v.lang.startsWith(langPrefix));
    if (v) return v;
  }

  // 1. Exact name match (preferred female list)
  for (const name of preferred) {
    const v = voices.find(
      (v) => v.name.toLowerCase() === name.toLowerCase() && v.lang.startsWith(langPrefix)
    );
    if (v) return v;
  }

  // 2. Partial name match in preferred list
  for (const name of preferred) {
    const v = voices.find(
      (v) => v.name.toLowerCase().includes(name.toLowerCase()) && v.lang.startsWith(langPrefix)
    );
    if (v) return v;
  }

  // 3. Any voice whose name suggests female
  const femaleHints = /female|woman|girl|samantha|karen|victoria|anna|ting|mei|yaoyao/i;
  const guessed = voices.find((v) => femaleHints.test(v.name) && v.lang.startsWith(langPrefix));
  if (guessed) return guessed;

  // 4. Best lang match (any gender)
  return voices.find((v) => v.lang === langTag) ??
    voices.find((v) => v.lang.startsWith(langPrefix)) ??
    null;
}

export function supportsSpeechSynthesis(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function stopSpeaking(): void {
  if (!supportsSpeechSynthesis()) return;
  window.speechSynthesis.cancel();
}

export function speakText(text: string, language: AppLanguage): void {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized || !supportsSpeechSynthesis()) return;

  stopSpeaking();

  const utterance = new SpeechSynthesisUtterance(normalized);
  utterance.lang = toSpeechLanguage(language);
  utterance.rate = language === "zh" ? 1 : 0.96;

  // Voice selection: try female voice; voices may not be loaded yet on first
  // call, so use onvoiceschanged to retry once if the list is empty.
  const applyVoice = () => {
    const voice = pickFemaleVoice(language);
    if (voice) utterance.voice = voice;
    window.speechSynthesis.speak(utterance);
  };

  if (window.speechSynthesis.getVoices().length > 0) {
    applyVoice();
  } else {
    window.speechSynthesis.onvoiceschanged = () => {
      window.speechSynthesis.onvoiceschanged = null;
      applyVoice();
    };
  }
}

/**
 * Like speakText but fires callbacks for word-boundary highlighting.
 * onBoundary(charIndex, charLength) — called each time the synthesizer
 * starts a new word; charIndex/charLength map into the original `text`.
 * onEnd — called when utterance finishes or is cancelled.
 */
export function speakTextTracked(
  text: string,
  language: AppLanguage,
  onBoundary: (charIndex: number, charLength: number) => void,
  onEnd: () => void,
): void {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized || !supportsSpeechSynthesis()) { onEnd(); return; }

  stopSpeaking();

  const utterance = new SpeechSynthesisUtterance(normalized);
  utterance.lang = toSpeechLanguage(language);
  utterance.rate = language === "zh" ? 1 : 0.96;

  utterance.onboundary = (event: SpeechSynthesisEvent) => {
    if (event.name === "word") onBoundary(event.charIndex, event.charLength ?? 0);
  };
  utterance.onend = onEnd;
  utterance.onerror = onEnd;

  const applyVoice = () => {
    const voice = pickFemaleVoice(language);
    if (voice) utterance.voice = voice;
    window.speechSynthesis.speak(utterance);
  };

  if (window.speechSynthesis.getVoices().length > 0) {
    applyVoice();
  } else {
    window.speechSynthesis.onvoiceschanged = () => {
      window.speechSynthesis.onvoiceschanged = null;
      applyVoice();
    };
  }
}

export function getPreferredRecordingMimeType(): string {
  if (typeof window === "undefined" || typeof MediaRecorder === "undefined") {
    return "audio/webm";
  }

  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
  ];
  return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate)) ?? "audio/webm";
}
