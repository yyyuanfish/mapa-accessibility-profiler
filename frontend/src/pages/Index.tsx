import { useState, useCallback, useEffect } from "react";
import HeroSection from "@/components/HeroSection";
import ConsentStep from "@/components/ConsentStep";
import ProfilingChat, { type ProfilingSession } from "@/components/ProfilingChat";
import ResultsView from "@/components/ResultsView";
import { type AccessibilityProfile } from "@/lib/profiling-engine";

// Flow:
//   hero → consent → profiling → results
type AppStep = "hero" | "consent" | "profiling" | "results";

// Distance in km between two WGS-84 coords (Haversine)
function haversineKm(a: [number, number], b: [number, number]): number {
  const R = 6371;
  const dLat = ((b[0] - a[0]) * Math.PI) / 180;
  const dLon = ((b[1] - a[1]) * Math.PI) / 180;
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((a[0] * Math.PI) / 180) *
      Math.cos((b[0] * Math.PI) / 180) *
      Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.asin(Math.sqrt(s));
}

const ZURICH_HB: [number, number] = [47.3782, 8.5403];

/** Return route_id best matching the user's location (within 5 km of Zürich HB → Zurich routes). */
export function locationToRouteId(
  loc: [number, number] | null,
  needsStepFree: boolean
): string {
  if (!loc) {
    return needsStepFree ? "zurich_hb_to_rathaus_sf" : "zurich_hb_to_rathaus";
  }
  if (loc && haversineKm(loc, ZURICH_HB) <= 5) {
    return needsStepFree ? "zurich_hb_to_rathaus_sf" : "zurich_hb_to_rathaus";
  }
  return needsStepFree ? "step_free_route" : "route_with_stairs";
}

const Index = () => {
  const [step, setStep] = useState<AppStep>("hero");
  const [profile, setProfile] = useState<AccessibilityProfile | null>(null);
  const [profilingSession, setProfilingSession] = useState<ProfilingSession | null>(null);
  const [resumeProfiling, setResumeProfiling] = useState(false);
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null);
  const [microphoneGranted, setMicrophoneGranted] = useState(false);

  // ── GPS location — reused only when the browser has already granted it ─
  const [userLocation, setUserLocation] = useState<[number, number] | null>(null);

  const requestLocation = useCallback(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => setUserLocation([pos.coords.latitude, pos.coords.longitude]),
      () => { /* silently ignore — user can locate later in map tab */ },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 300_000 }
    );
  }, []);

  // Also try silently on mount if permission was already granted
  useEffect(() => {
    if (!navigator.geolocation || !navigator.permissions) return;
    navigator.permissions
      .query({ name: "geolocation" })
      .then((r) => { if (r.state === "granted") requestLocation(); });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stopCamera = useCallback(() => {
    cameraStream?.getTracks().forEach((track) => track.stop());
    setCameraStream(null);
  }, [cameraStream]);

  return (
    <>
      {step === "hero" && (
        <HeroSection
          onStart={() => {
            setResumeProfiling(false);
            setStep("consent");
          }}
        />
      )}

      {step === "consent" && (
        <ConsentStep
          initialMicrophoneGranted={microphoneGranted}
          onContinue={({ cameraStream: nextCameraStream, microphoneGranted: nextMicrophoneGranted }) => {
            setCameraStream(nextCameraStream);
            setMicrophoneGranted(nextMicrophoneGranted);
            setStep("profiling");
          }}
          onBack={() => {
            stopCamera();
            setStep("hero");
          }}
        />
      )}

      {step === "profiling" && (
        <ProfilingChat
          session={profilingSession}
          resumeForRevision={resumeProfiling}
          cameraStream={cameraStream}
          microphoneGranted={microphoneGranted}
          onStopCamera={stopCamera}
          onSessionChange={setProfilingSession}
          onComplete={(p) => {
            setProfile(p);
            setResumeProfiling(false);
            stopCamera();
            setStep("results");
          }}
          onBack={() => {
            setResumeProfiling(false);
            stopCamera();
            setStep("hero");
          }}
        />
      )}

      {step === "results" && profile && (
        <ResultsView
          profile={profile}
          userLocation={userLocation}
          onRefine={() => {
            setResumeProfiling(true);
            setStep("profiling");
          }}
          onRestart={() => {
            setProfile(null);
            setProfilingSession(null);
            setResumeProfiling(false);
            setMicrophoneGranted(false);
            setStep("consent");
          }}
        />
      )}
    </>
  );
};

export default Index;
