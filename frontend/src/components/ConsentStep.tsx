import { useCallback, useState } from "react";
import { Accessibility, Camera, Check, Mic, Shield, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import PageSpeechControl from "@/components/PageSpeechControl";
import { useRuntime, t } from "@/lib/runtime-context";
import { stopSpeaking } from "@/lib/speech";

interface ConsentState {
  cameraStream: MediaStream | null;
  microphoneGranted: boolean;
}

interface ConsentStepProps {
  initialMicrophoneGranted?: boolean;
  onContinue: (state: ConsentState) => void;
  onBack: () => void;
}

const stopStream = (stream: MediaStream | null) => {
  stream?.getTracks().forEach((track) => track.stop());
};

const ConsentStep = ({ initialMicrophoneGranted = false, onContinue, onBack }: ConsentStepProps) => {
  const { language, setLanguage } = useRuntime();
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null);
  const [microphoneGranted, setMicrophoneGranted] = useState(initialMicrophoneGranted);
  const [cameraDenied, setCameraDenied] = useState(false);
  const [microphoneDenied, setMicrophoneDenied] = useState(false);
  const [isRequestingCamera, setIsRequestingCamera] = useState(false);
  const [isRequestingMic, setIsRequestingMic] = useState(false);

  const listenForLanguage = useCallback(() => {
    const SpeechRecognitionAPI =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognitionAPI) return;

    stopSpeaking();
    const recognition = new SpeechRecognitionAPI();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const command = Array.from(event.results)
        .map((result) => result[0].transcript)
        .join(" ")
        .trim()
        .toLowerCase();
      if (/english|英语|英文|englisch/.test(command)) setLanguage("en");
      else if (/chinese|mandarin|中文|汉语|chinesisch/.test(command)) setLanguage("zh");
      else if (/german|deutsch|德语|德文/.test(command)) setLanguage("de");
    };
    recognition.start();
  }, [setLanguage]);

  const requestCamera = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraDenied(true);
      return;
    }
    setIsRequestingCamera(true);
    setCameraDenied(false);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      stopStream(cameraStream);
      setCameraStream(stream);
    } catch {
      setCameraDenied(true);
    } finally {
      setIsRequestingCamera(false);
    }
  }, [cameraStream]);

  const requestMicrophone = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setMicrophoneDenied(true);
      return;
    }
    setIsRequestingMic(true);
    setMicrophoneDenied(false);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      setMicrophoneGranted(true);
      window.setTimeout(listenForLanguage, 150);
    } catch {
      setMicrophoneDenied(true);
    } finally {
      setIsRequestingMic(false);
    }
  }, [listenForLanguage]);

  return (
    <div className="min-h-screen gradient-hero flex flex-col">
      <nav className="flex items-center justify-between px-8 py-5">
        <div className="flex items-center gap-2">
          <Accessibility className="w-7 h-7 text-primary-foreground" />
          <span className="text-lg font-bold text-primary-foreground">{t(language, "nav_brand")}</span>
        </div>
        <div className="flex items-center gap-2">
          <PageSpeechControl narration={t(language, "consent_narration")} />
          <button
            onClick={() => {
              stopStream(cameraStream);
              onBack();
            }}
            className="text-sm text-primary-foreground/80 hover:text-primary-foreground transition-colors"
          >
            {t(language, "consent_back")}
          </button>
        </div>
      </nav>

      <main className="flex-1 flex items-center justify-center px-6 py-10">
        <section className="w-full max-w-2xl rounded-2xl bg-primary-foreground/14 border border-primary-foreground/20 backdrop-blur-md p-6 sm:p-8 text-primary-foreground shadow-warm">
          <div className="flex items-start gap-4 mb-6">
            <div className="w-11 h-11 rounded-xl bg-primary-foreground/18 flex items-center justify-center shrink-0">
              <Shield className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">{t(language, "consent_title")}</h1>
              <p className="mt-2 text-sm sm:text-base text-primary-foreground/80 leading-relaxed">
                {t(language, "consent_desc")}
              </p>
            </div>
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            <div className="rounded-xl bg-primary-foreground/12 border border-primary-foreground/20 p-4">
              <div className="flex items-center gap-3 mb-2">
                <Camera className="w-5 h-5" />
                <h2 className="font-semibold">{t(language, "consent_camera")}</h2>
              </div>
              <p className="text-sm text-primary-foreground/75 mb-4">{t(language, "consent_camera_desc")}</p>
              <Button
                type="button"
                variant="secondary"
                onClick={cameraStream ? () => { stopStream(cameraStream); setCameraStream(null); } : requestCamera}
                disabled={isRequestingCamera}
                className="w-full"
              >
                {cameraStream ? <Check className="w-4 h-4 mr-2" /> : <Camera className="w-4 h-4 mr-2" />}
                {cameraStream ? t(language, "consent_enabled") : t(language, "consent_enable_camera")}
              </Button>
              {cameraDenied && (
                <p className="mt-3 text-xs text-primary-foreground/80 flex items-center gap-1">
                  <X className="w-3.5 h-3.5" />
                  {t(language, "consent_cam_denied")}
                </p>
              )}
            </div>

            <div className="rounded-xl bg-primary-foreground/12 border border-primary-foreground/20 p-4">
              <div className="flex items-center gap-3 mb-2">
                <Mic className="w-5 h-5" />
                <h2 className="font-semibold">{t(language, "consent_mic")}</h2>
              </div>
              <p className="text-sm text-primary-foreground/75 mb-4">{t(language, "consent_mic_desc")}</p>
              <Button
                type="button"
                variant="secondary"
                onClick={requestMicrophone}
                disabled={isRequestingMic || microphoneGranted}
                className="w-full"
              >
                {microphoneGranted ? <Check className="w-4 h-4 mr-2" /> : <Mic className="w-4 h-4 mr-2" />}
                {microphoneGranted ? t(language, "consent_enabled") : t(language, "consent_enable_mic")}
              </Button>
              {microphoneDenied && (
                <p className="mt-3 text-xs text-primary-foreground/80 flex items-center gap-1">
                  <X className="w-3.5 h-3.5" />
                  {t(language, "consent_mic_denied")}
                </p>
              )}
            </div>
          </div>

          <div className="mt-6 flex flex-col sm:flex-row items-center justify-between gap-3">
            <p className="text-xs text-primary-foreground/75">{t(language, "consent_still_continue")}</p>
            <Button
              type="button"
              variant="hero"
              size="lg"
              onClick={() => onContinue({ cameraStream, microphoneGranted })}
              className="w-full sm:w-auto px-8"
            >
              {t(language, "consent_continue")}
            </Button>
          </div>
        </section>
      </main>
    </div>
  );
};

export default ConsentStep;
