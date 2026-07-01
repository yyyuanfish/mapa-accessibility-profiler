import { useCallback, useEffect } from "react";
import { Volume2, VolumeX } from "lucide-react";
import { useRuntime, t } from "@/lib/runtime-context";
import { speakText, stopSpeaking } from "@/lib/speech";

interface PageSpeechControlProps {
  narration: string;
  className?: string;
}

const PageSpeechControl = ({ narration, className = "" }: PageSpeechControlProps) => {
  const { language, speechOutputEnabled, setSpeechOutputEnabled } = useRuntime();

  const readPage = useCallback(() => {
    speakText(narration, language);
  }, [language, narration]);

  useEffect(() => {
    if (!speechOutputEnabled) return;
    const timer = window.setTimeout(readPage, 100);
    return () => {
      window.clearTimeout(timer);
      stopSpeaking();
    };
  }, [readPage, speechOutputEnabled]);

  const toggleSpeech = () => {
    if (speechOutputEnabled) {
      stopSpeaking();
      setSpeechOutputEnabled(false);
      return;
    }
    setSpeechOutputEnabled(true);
  };

  return (
    <button
      type="button"
      onClick={toggleSpeech}
      className={`w-10 h-10 rounded-lg inline-flex items-center justify-center transition-colors ${
        speechOutputEnabled
          ? "bg-primary-foreground text-primary shadow-sm hover:bg-primary-foreground/90"
          : "bg-primary-foreground/15 text-primary-foreground/70 hover:bg-primary-foreground/25"
      } ${className}`}
      aria-pressed={speechOutputEnabled}
      aria-label={speechOutputEnabled ? t(language, "page_speech_stop") : t(language, "page_speech_read")}
      title={speechOutputEnabled ? t(language, "page_speech_stop") : t(language, "page_speech_read")}
    >
      {speechOutputEnabled ? <Volume2 className="w-5 h-5" /> : <VolumeX className="w-5 h-5" />}
    </button>
  );
};

export default PageSpeechControl;
