import { Button } from "@/components/ui/button";
import { Accessibility, Camera, MessageSquare, Shield } from "lucide-react";
import RuntimeSelector from "@/components/RuntimeSelector";
import PageSpeechControl from "@/components/PageSpeechControl";
import { useRuntime, t } from "@/lib/runtime-context";

interface HeroSectionProps {
  onStart: () => void;
}

const HeroSection = ({ onStart }: HeroSectionProps) => {
  const { language, mode, ollamaModel, speechModel, visionModel } = useRuntime();
  const runtimeDescription =
    mode === "mock"
      ? t(language, "hero_runtime_mock")
      : t(language, "hero_runtime_backend_ollama", {
          text: ollamaModel,
          speech: `faster-whisper ${speechModel}`,
          vision: visionModel,
        });
  const narration = t(language, "hero_narration", { runtime: runtimeDescription });

  const agents = [
    { icon: Shield, label: t(language, "agent_consent_guard") },
    { icon: MessageSquare, label: t(language, "agent_profiler") },
    { icon: Accessibility, label: t(language, "agent_profile_mgr") },
    { icon: Camera, label: t(language, "agent_hazard") },
  ];

  return (
    <div className="min-h-screen gradient-hero flex flex-col">
      <nav className="flex items-center justify-between px-8 py-5">
        <div className="flex items-center gap-2">
          <Accessibility className="w-7 h-7 text-primary-foreground" />
          <span className="text-lg font-bold text-primary-foreground">{t(language, "nav_brand")}</span>
        </div>
        <div className="flex items-center gap-2">
          <PageSpeechControl narration={narration} />
          <RuntimeSelector />
        </div>
      </nav>

      <div className="flex-1 flex items-center justify-center px-6">
        <div className="max-w-3xl text-center animate-fade-in">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-primary-foreground/15 text-primary-foreground/90 text-sm font-medium mb-8 backdrop-blur-sm">
            <Shield className="w-4 h-4" />
            {t(language, "hero_badge")}
          </div>

          <h1 className="text-4xl sm:text-6xl font-black text-primary-foreground leading-tight mb-6 tracking-tight">
            {t(language, "hero_title_1")}<br />
            <span className="opacity-90">{t(language, "hero_title_2")}</span>
          </h1>

          <p className="text-lg sm:text-xl text-primary-foreground/80 mb-10 max-w-2xl mx-auto leading-relaxed">
            {t(language, "hero_subtitle")}
          </p>

          <div className="flex justify-center">
            <Button variant="hero" size="lg" className="text-lg px-8 py-6 rounded-xl" onClick={onStart}>
              <MessageSquare className="w-5 h-5 mr-2" />
              {t(language, "hero_cta")}
            </Button>
          </div>

          <div className="mt-16 grid grid-cols-2 sm:grid-cols-4 gap-4 max-w-2xl mx-auto">
            {agents.map((agent) => (
              <div
                key={agent.label}
                className="flex flex-col items-center gap-2 p-4 rounded-xl bg-primary-foreground/10 backdrop-blur-sm"
              >
                <agent.icon className="w-6 h-6 text-primary-foreground/80" />
                <span className="text-xs font-medium text-primary-foreground/70">{agent.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default HeroSection;
