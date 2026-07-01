import { useState, useEffect, useRef } from "react";
import { useRuntime, type RuntimeMode, LANGUAGES, t } from "@/lib/runtime-context";
import { Settings, X, Cpu, RefreshCw, Server } from "lucide-react";
import { Input } from "@/components/ui/input";

const FALLBACK_TEXT_MODELS = [
  "shmily_006/Qw3:4b_4bit",
  "qwen3.5:4b",
  "llama3.1:8b",
];
const FALLBACK_VISION_MODELS = ["llava:7b"];
const SPEECH_MODELS = ["tiny", "base", "small", "medium", "large-v3"];

const unique = (values: string[]) => [...new Set(values.filter(Boolean))];
const isVisionModel = (name: string) => /llava|vision|bakllava|minicpm-v/i.test(name);

/** Fetch installed Ollama model names from /api/tags */
async function fetchOllamaModels(baseUrl: string): Promise<string[]> {
  try {
    const res = await fetch(`${baseUrl.replace(/\/$/, "")}/api/tags`, { signal: AbortSignal.timeout(4000) });
    if (!res.ok) return [];
    const data = await res.json() as { models?: { name: string }[] };
    return (data.models ?? []).map((m) => m.name).filter(Boolean);
  } catch {
    return [];
  }
}

const RuntimeSelector = () => {
  const {
    mode,
    setMode,
    ollamaUrl,
    setOllamaUrl,
    ollamaModel,
    setOllamaModel,
    speechModel,
    setSpeechModel,
    visionModel,
    setVisionModel,
    backendUrl,
    setBackendUrl,
    language,
    setLanguage,
  } = useRuntime();

  const [showSettings, setShowSettings] = useState(false);
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const [fetchingModels, setFetchingModels] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  // Close panel on outside click
  useEffect(() => {
    if (!showSettings) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setShowSettings(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showSettings]);

  // Backend mode can discover locally installed Ollama models.
  useEffect(() => {
    if (!showSettings || mode !== "backend") return;
    setFetchingModels(true);
    fetchOllamaModels(ollamaUrl).then((models) => {
      setOllamaModels(models);
      setFetchingModels(false);
    });
  }, [showSettings, mode, ollamaUrl]);

  const refreshModels = () => {
    setFetchingModels(true);
    fetchOllamaModels(ollamaUrl).then((models) => {
      setOllamaModels(models);
      setFetchingModels(false);
    });
  };

  const modeOptions: { value: RuntimeMode; label: string; icon: typeof Cpu }[] = [
    { value: "mock", label: t(language, "mock_label"), icon: Cpu },
    { value: "backend", label: t(language, "backend_label"), icon: Server },
  ];
  const textModels = unique([
    ollamaModel,
    ...ollamaModels.filter((name) => !isVisionModel(name)),
    ...FALLBACK_TEXT_MODELS,
  ]);
  const visionModels = unique([
    visionModel,
    ...ollamaModels.filter(isVisionModel),
    ...FALLBACK_VISION_MODELS,
  ]);

  return (
    <div className="relative flex items-center gap-2" ref={panelRef}>
      {/* ── Language selector ── */}
      <div className="flex items-center gap-1 p-1 rounded-xl bg-primary-foreground/10 backdrop-blur-sm">
        {LANGUAGES.map((lang) => (
          <button
            key={lang.value}
            onClick={() => setLanguage(lang.value)}
            className={`px-2 py-1.5 rounded-lg text-xs font-medium transition-all ${
              language === lang.value
                ? "bg-primary-foreground text-primary shadow-sm"
                : "text-primary-foreground/70 hover:text-primary-foreground"
            }`}
            title={lang.label}
          >
            {lang.flag}
          </button>
        ))}
      </div>

      {/* ── Settings gear (larger, prominent) ── */}
      <button
        onClick={() => setShowSettings(!showSettings)}
        aria-label={t(language, "settings_title")}
        className={`p-2.5 rounded-xl backdrop-blur-sm transition-all ${
          showSettings
            ? "bg-primary-foreground text-primary shadow-sm"
            : "bg-primary-foreground/10 text-primary-foreground/80 hover:bg-primary-foreground/20 hover:text-primary-foreground"
        }`}
      >
        <Settings className="w-4 h-4" />
      </button>

      {/* ── Settings panel ── */}
      {showSettings && (
        <div className="absolute right-0 top-full mt-2 w-80 bg-card rounded-2xl shadow-xl border border-border p-5 z-50 animate-slide-up">
          <div className="flex items-center justify-between mb-4">
            <h4 className="text-sm font-semibold text-foreground">{t(language, "settings_title")}</h4>
            <button
              onClick={() => setShowSettings(false)}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Runtime: browser mock or FastAPI backend. */}
          <div className="mb-4">
            <label className="text-xs font-medium text-muted-foreground mb-2 block">
              {t(language, "settings_mode")}
            </label>
            <div className="flex gap-2">
              {modeOptions.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setMode(opt.value)}
                  className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl border-2 text-sm font-medium transition-all ${
                    mode === opt.value
                      ? "border-primary bg-primary/5 text-foreground"
                      : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground"
                  }`}
                >
                  <opt.icon className="w-4 h-4" />
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Backend settings */}
          {mode === "backend" && (
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 block">
                  {t(language, "settings_backend_url")}
                </label>
                <Input
                  value={backendUrl}
                  onChange={(e) => setBackendUrl(e.target.value)}
                  placeholder="http://localhost:8000"
                  className="text-xs h-8 rounded-lg"
                />
                <p className="text-[10px] text-muted-foreground mt-1">
                  {t(language, "settings_backend_hint")}
                </p>
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 block">
                  {t(language, "settings_ollama_url")}
                </label>
                <Input
                  value={ollamaUrl}
                  onChange={(e) => setOllamaUrl(e.target.value)}
                  onBlur={refreshModels}
                  placeholder="http://localhost:11434"
                  className="text-xs h-8 rounded-lg"
                />
                <p className="text-[10px] text-muted-foreground mt-1">
                  {t(language, "settings_ollama_hint")}
                </p>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs font-medium text-muted-foreground">
                    {t(language, "settings_text_model")}
                  </label>
                  <button
                    onClick={refreshModels}
                    disabled={fetchingModels}
                    className="text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
                    title="Refresh models"
                  >
                    <RefreshCw className={`w-3 h-3 ${fetchingModels ? "animate-spin" : ""}`} />
                  </button>
                </div>

                <select
                  value={ollamaModel}
                  onChange={(e) => setOllamaModel(e.target.value)}
                  className="w-full h-9 rounded-lg border border-border bg-background px-3 text-xs text-foreground"
                >
                  {textModels.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 block">
                  {t(language, "settings_speech_model")}
                </label>
                <select
                  value={speechModel}
                  onChange={(e) => setSpeechModel(e.target.value)}
                  className="w-full h-9 rounded-lg border border-border bg-background px-3 text-xs text-foreground"
                >
                  {SPEECH_MODELS.map((name) => (
                    <option key={name} value={name}>faster-whisper {name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 block">
                  {t(language, "settings_vision_model")}
                </label>
                <select
                  value={visionModel}
                  onChange={(e) => setVisionModel(e.target.value)}
                  className="w-full h-9 rounded-lg border border-border bg-background px-3 text-xs text-foreground"
                >
                  {visionModels.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
              </div>
            </div>
          )}

          {/* Status indicator */}
          <div className="flex items-center gap-2 mt-4 pt-3 border-t border-border">
            <span className={`w-2 h-2 rounded-full ${mode === "mock" ? "bg-primary" : "bg-green-500"}`} />
            <span className="text-xs text-muted-foreground">
              {mode === "mock"
                ? t(language, "settings_offline")
                : t(language, "settings_backend_req")}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

export default RuntimeSelector;
