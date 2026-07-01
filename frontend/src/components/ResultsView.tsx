import { useState, useEffect, useCallback, useMemo, useRef, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  Accessibility,
  Route,
  AlertTriangle,
  CheckCircle,
  FileJson,
  RotateCcw,
  ChevronRight,
  Volume2,
  VolumeX,
  MapPin,
  LocateFixed,
  Database,
} from "lucide-react";
import {
  type AccessibilityProfile,
  getDetectedNeeds,
  generatePlan,
  type RoutePlan,
} from "@/lib/profiling-engine";
import { useRuntime, t as tr } from "@/lib/runtime-context";
import { speakTextTracked, stopSpeaking } from "@/lib/speech";
import RouteMap from "@/components/RouteMap";
import { locationToRouteId } from "@/pages/Index";
import {
  buildOpenDataSnapshot,
  getMockRouteCoords,
  type OpenDataSnapshot,
} from "@/lib/route-context";

interface ResultsViewProps {
  profile: AccessibilityProfile;
  userLocation?: [number, number] | null;
  onRefine: () => void;
  onRestart: () => void;
}

type TabKey = "plan" | "map" | "profile" | "json";
type ReadSectionKey = "route" | "alerts" | "checklist";

type ReadQueueItem = {
  section: ReadSectionKey;
  itemIndex: number;
  text: string;
};

type ActiveReadState = ReadQueueItem & {
  start: number;
  end: number;
};

function renderHighlightedText(
  text: string,
  active: ActiveReadState | null,
  section: ReadSectionKey,
  itemIndex: number,
): ReactNode {
  if (!active || active.section !== section || active.itemIndex !== itemIndex) {
    return text;
  }

  return (
    <>
      {text.slice(0, active.start)}
      <span className="bg-primary/15 text-primary rounded px-0.5 transition-all">
        {text.slice(active.start, active.end)}
      </span>
      {text.slice(active.end)}
    </>
  );
}

function uniqueLines(items: string[]): string[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const normalized = item.trim();
    if (!normalized || seen.has(normalized)) return false;
    seen.add(normalized);
    return true;
  });
}

const ResultsView = ({
  profile,
  userLocation: initialLocation,
  onRefine,
  onRestart,
}: ResultsViewProps) => {
  const { language, setSpeechOutputEnabled } = useRuntime();
  const [tab, setTab] = useState<TabKey>("plan");
  const needs = getDetectedNeeds(profile);

  const [userLocation, setUserLocation] = useState<[number, number] | null>(
    initialLocation ?? null,
  );
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);

  const [readingScope, setReadingScope] = useState<ReadSectionKey | "all" | null>(null);
  const [activeRead, setActiveRead] = useState<ActiveReadState | null>(null);
  const speechSessionRef = useRef(0);

  useEffect(() => {
    if (initialLocation) setUserLocation(initialLocation);
  }, [initialLocation]);

  const locateUser = useCallback(() => {
    if (!navigator.geolocation) {
      setLocationError("Geolocation is not supported by your browser.");
      return;
    }
    setLocating(true);
    setLocationError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setUserLocation([pos.coords.latitude, pos.coords.longitude]);
        setLocating(false);
      },
      (err) => {
        setLocationError(
          err.code === 1
            ? "Location permission denied. Please allow location access."
            : "Could not get your location. Please try again.",
        );
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 },
    );
  }, []);

  const needsStepFree =
    profile.mobility.wheelchair_user === true || profile.mobility.step_free_route === true;
  const routeId = locationToRouteId(userLocation, needsStepFree);

  const plan = useMemo<RoutePlan>(() => generatePlan(profile, routeId), [profile, routeId]);
  const openDataSnapshot = useMemo<OpenDataSnapshot>(
    () => buildOpenDataSnapshot(routeId, profile, language),
    [language, profile, routeId],
  );

  const planDirections = plan.directions;
  const mergedAlerts = useMemo(
    () => uniqueLines([...plan.alerts, ...openDataSnapshot.alerts]),
    [openDataSnapshot.alerts, plan.alerts],
  );
  const checklistItems = useMemo(
    () => uniqueLines(plan.checklist),
    [plan.checklist],
  );
  const routeCoords = plan.route_coords ?? getMockRouteCoords(routeId);

  const stopNarration = useCallback(
    (resetSpeechPreference: boolean = true) => {
      speechSessionRef.current += 1;
      stopSpeaking();
      setReadingScope(null);
      setActiveRead(null);
      if (resetSpeechPreference) {
        setSpeechOutputEnabled(false);
      }
    },
    [setSpeechOutputEnabled],
  );

  const buildReadQueue = useCallback(
    (scope: ReadSectionKey | "all"): ReadQueueItem[] => {
      const routeQueue: ReadQueueItem[] = [
        { section: "route", itemIndex: -1, text: plan.summary },
        ...planDirections.map((direction, index) => ({
          section: "route" as const,
          itemIndex: index,
          text: direction,
        })),
      ];
      const alertQueue: ReadQueueItem[] = mergedAlerts.map((alert, index) => ({
        section: "alerts" as const,
        itemIndex: index,
        text: alert,
      }));
      const checklistQueue: ReadQueueItem[] = checklistItems.map((item, index) => ({
        section: "checklist" as const,
        itemIndex: index,
        text: item,
      }));

      if (scope === "route") return routeQueue;
      if (scope === "alerts") return alertQueue;
      if (scope === "checklist") return checklistQueue;
      return [...routeQueue, ...alertQueue, ...checklistQueue];
    },
    [checklistItems, mergedAlerts, plan.summary, planDirections],
  );

  const startNarration = useCallback(
    (scope: ReadSectionKey | "all") => {
      const queue = buildReadQueue(scope);
      if (!queue.length) return;

      speechSessionRef.current += 1;
      const sessionId = speechSessionRef.current;
      setSpeechOutputEnabled(true);
      setReadingScope(scope);
      setActiveRead(null);

      const speakNext = (index: number) => {
        if (speechSessionRef.current !== sessionId) return;
        if (index >= queue.length) {
          setReadingScope(null);
          setActiveRead(null);
          setSpeechOutputEnabled(false);
          return;
        }

        const item = queue[index];
        speakTextTracked(
          item.text,
          language,
          (charIndex, charLength) => {
            if (speechSessionRef.current !== sessionId) return;
            setActiveRead({
              ...item,
              start: charIndex,
              end: charIndex + charLength,
            });
          },
          () => {
            if (speechSessionRef.current !== sessionId) return;
            speakNext(index + 1);
          },
        );
      };

      speakNext(0);
    },
    [buildReadQueue, language, setSpeechOutputEnabled],
  );

  useEffect(() => {
    return () => stopNarration(false);
  }, [stopNarration]);

  useEffect(() => {
    if (tab !== "plan") {
      stopNarration(false);
    }
  }, [stopNarration, tab]);

  const toggleSectionNarration = (section: ReadSectionKey) => {
    if (readingScope === section) {
      stopNarration();
      return;
    }
    startNarration(section);
  };

  const toggleAllNarration = () => {
    if (readingScope === "all") {
      stopNarration();
      return;
    }
    startNarration("all");
  };

  const sectionButton = (section: ReadSectionKey) => (
    <button
      onClick={() => toggleSectionNarration(section)}
      className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs transition-colors ${
        readingScope === section
          ? "bg-primary/10 text-primary"
          : "bg-muted text-muted-foreground hover:text-foreground"
      }`}
      aria-label={
        readingScope === section ? tr(language, "result_stop_reading") : tr(language, "chat_speech_replay")
      }
      title={
        readingScope === section ? tr(language, "result_stop_reading") : tr(language, "chat_speech_replay")
      }
    >
      {readingScope === section ? <VolumeX className="w-3.5 h-3.5" /> : <Volume2 className="w-3.5 h-3.5" />}
    </button>
  );

  const activeSection = activeRead?.section ?? null;

  return (
    <div className="min-h-screen bg-background">
      <div className="gradient-hero px-6 py-12">
        <div className="max-w-4xl mx-auto text-center animate-fade-in">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary-foreground/20 mb-4">
            <Accessibility className="w-8 h-8 text-primary-foreground" />
          </div>
          <h1 className="text-3xl font-bold text-primary-foreground mb-2">{tr(language, "result_title")}</h1>
          <p className="text-primary-foreground/80 mb-6">
            {tr(language, "result_confidence", { value: (profile.overall_confidence * 100).toFixed(0) })}
          </p>

          <button
            onClick={toggleAllNarration}
            className="mx-auto mb-6 inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary-foreground/15 text-primary-foreground hover:bg-primary-foreground/20 transition-colors"
          >
            {readingScope === "all" ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
            <span className="text-sm font-medium">
              {readingScope === "all" ? tr(language, "result_stop_reading") : tr(language, "result_read_all")}
            </span>
          </button>

          <div className="flex flex-wrap justify-center gap-2 mb-6">
            {needs.length > 0 ? (
              needs.map((need) => (
                <span
                  key={need}
                  className="px-3 py-1.5 rounded-full bg-primary-foreground/20 text-primary-foreground text-sm font-medium backdrop-blur-sm"
                >
                  {need}
                </span>
              ))
            ) : (
              <span className="px-3 py-1.5 rounded-full bg-primary-foreground/20 text-primary-foreground text-sm">
                {tr(language, "result_no_needs")}
              </span>
            )}
          </div>

          <div className="inline-flex gap-1 p-1 rounded-xl bg-primary-foreground/10">
            {(["plan", "map", "profile", "json"] as const).map((tabKey) => (
              <button
                key={tabKey}
                onClick={() => setTab(tabKey)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                  tab === tabKey
                    ? "bg-primary-foreground text-primary shadow-sm"
                    : "text-primary-foreground/70 hover:text-primary-foreground"
                }`}
              >
                {tabKey === "plan"
                  ? tr(language, "result_tab_plan")
                  : tabKey === "map"
                    ? (language === "zh" ? "地图" : language === "de" ? "Karte" : "Map")
                    : tabKey === "profile"
                      ? tr(language, "result_tab_profile")
                      : tr(language, "result_tab_json")}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-6 py-8 -mt-4">
        {tab === "plan" && (
          <div className="flex flex-col gap-6 animate-slide-up">
            <div className="order-2 bg-card rounded-2xl p-6 shadow-card border border-primary/10">
              <div className="flex items-start justify-between gap-4 mb-4">
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Database className="w-5 h-5 text-primary" />
                    <h3 className="font-semibold text-foreground">{tr(language, "result_open_data")}</h3>
                  </div>
                  <p className="text-sm text-muted-foreground">{openDataSnapshot.summary}</p>
                </div>
                <div className="flex flex-col items-end gap-2 shrink-0">
                  <span className="px-3 py-1 rounded-full bg-primary/10 text-primary text-xs font-medium">
                    {openDataSnapshot.sourceLabel}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {tr(language, "result_updated", { value: openDataSnapshot.updatedLabel })}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                <div className="rounded-xl bg-muted p-3">
                  <p className="text-xs text-muted-foreground mb-1">Barriers</p>
                  <p className="text-lg font-semibold text-foreground">{openDataSnapshot.counts.barriers}</p>
                </div>
                <div className="rounded-xl bg-muted p-3">
                  <p className="text-xs text-muted-foreground mb-1">High severity</p>
                  <p className="text-lg font-semibold text-foreground">{openDataSnapshot.counts.highSeverity}</p>
                </div>
                <div className="rounded-xl bg-muted p-3">
                  <p className="text-xs text-muted-foreground mb-1">Toilets</p>
                  <p className="text-lg font-semibold text-foreground">{openDataSnapshot.counts.toilets}</p>
                </div>
                <div className="rounded-xl bg-muted p-3">
                  <p className="text-xs text-muted-foreground mb-1">Parking</p>
                  <p className="text-lg font-semibold text-foreground">{openDataSnapshot.counts.parking}</p>
                </div>
              </div>

              <div className="rounded-xl bg-muted/60 p-4 mb-4">
                <h4 className="text-sm font-semibold text-foreground mb-3">{tr(language, "result_sources")}</h4>
                <div className="space-y-2">
                  {openDataSnapshot.sources.map((source, index) => (
                    <div
                      key={`${source.name}-${index}`}
                      className="grid gap-2 rounded-xl bg-background p-3 border border-border/70 md:grid-cols-[1.2fr_0.8fr_1fr]"
                    >
                      <div>
                        <p className="text-sm font-medium text-foreground">{source.name}</p>
                        <p className="text-xs text-muted-foreground">{tr(language, "result_affects")}: {source.affects}</p>
                      </div>
                      <p className="text-xs text-muted-foreground md:self-center">
                        {language === "zh" ? "更新于" : language === "de" ? "Aktualisiert" : "Updated"} {source.updated}
                      </p>
                      <div className="md:justify-self-end">
                        <span
                          className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${
                            source.freshness === "current"
                              ? "bg-primary/10 text-primary"
                              : "bg-muted text-muted-foreground"
                          }`}
                        >
                          {source.freshness === "current"
                            ? tr(language, "result_freshness_current")
                            : tr(language, "result_freshness_reference")}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="grid md:grid-cols-2 gap-4">
                <div className="rounded-xl bg-muted/60 p-4">
                  <h4 className="text-sm font-semibold text-foreground mb-3">{tr(language, "result_hotspots")}</h4>
                  <div className="space-y-3">
                    {openDataSnapshot.hotspots.map((hotspot) => (
                      <div key={hotspot.id} className="rounded-xl bg-background p-3 border border-border/70">
                        <div className="flex items-start justify-between gap-3 mb-1">
                          <p className="text-sm font-medium text-foreground">{hotspot.title}</p>
                          <span className="text-xs px-2 py-0.5 rounded-full bg-secondary/10 text-secondary">
                            S{hotspot.severity}
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground mb-1">
                          {hotspot.category} · {hotspot.distance_m}m
                        </p>
                        <p className="text-xs text-muted-foreground">{hotspot.description}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-xl bg-muted/60 p-4">
                  <h4 className="text-sm font-semibold text-foreground mb-3">{tr(language, "result_nearby")}</h4>
                  <div className="space-y-3">
                    {openDataSnapshot.nearbyAmenities.map((amenity, index) => (
                      <div key={`${amenity.type}-${index}`} className="rounded-xl bg-background p-3 border border-border/70">
                        <div className="flex items-start justify-between gap-3 mb-1">
                          <p className="text-sm font-medium text-foreground">{amenity.name}</p>
                          <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                            {amenity.type}
                          </span>
                        </div>
                        {amenity.address && (
                          <p className="text-xs text-muted-foreground">{amenity.address}</p>
                        )}
                        {amenity.opening_hours && (
                          <p className="text-xs text-muted-foreground">{amenity.opening_hours}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            <div className={`order-1 bg-card rounded-2xl p-6 shadow-card border ${activeSection === "route" ? "border-primary/30" : "border-transparent"}`}>
              <div className="flex items-center justify-between gap-3 mb-3">
                <div className="flex items-center gap-2">
                  <Route className="w-5 h-5 text-primary" />
                  <div>
                    <h3 className="font-semibold text-foreground">{tr(language, "result_route_plan")}</h3>
                    <p className="text-xs text-muted-foreground">{openDataSnapshot.routeLabel}</p>
                  </div>
                </div>
                {sectionButton("route")}
              </div>

              <div className={`rounded-xl px-4 py-3 mb-4 ${activeRead?.section === "route" && activeRead.itemIndex === -1 ? "bg-primary/5" : "bg-muted/60"}`}>
                <p className="text-sm text-muted-foreground">
                  {renderHighlightedText(plan.summary, activeRead, "route", -1)}
                </p>
              </div>

              <div className="space-y-3">
                {planDirections.map((direction, index) => (
                  <div
                    key={index}
                    className={`rounded-xl p-3 transition-colors ${
                      activeRead?.section === "route" && activeRead.itemIndex === index
                        ? "bg-primary/5 border border-primary/20"
                        : "bg-transparent"
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <div className="w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center text-xs font-bold shrink-0 mt-0.5">
                        {index + 1}
                      </div>
                      <div className="space-y-2">
                        <span className="text-sm text-foreground">
                          {renderHighlightedText(direction, activeRead, "route", index)}
                        </span>
                        {openDataSnapshot.stepNotes[index]?.map((note, noteIndex) => (
                          <div
                            key={noteIndex}
                            className="inline-flex items-center gap-2 rounded-full bg-secondary/10 px-3 py-1 text-xs text-secondary"
                          >
                            <AlertTriangle className="w-3 h-3" />
                            {note}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {mergedAlerts.length > 0 && (
              <div className={`order-3 bg-card rounded-2xl p-6 shadow-card border ${activeSection === "alerts" ? "border-primary/30" : "border-transparent"}`}>
                <div className="flex items-center justify-between gap-3 mb-3">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="w-5 h-5 text-secondary" />
                    <h3 className="font-semibold text-foreground">{tr(language, "result_alerts")}</h3>
                  </div>
                  {sectionButton("alerts")}
                </div>
                <div className="space-y-2">
                  {mergedAlerts.map((alert, index) => (
                    <div
                      key={index}
                      className={`rounded-xl px-3 py-2 text-sm text-foreground transition-colors ${
                        activeRead?.section === "alerts" && activeRead.itemIndex === index
                          ? "bg-primary/5 border border-primary/20"
                          : "bg-muted/50"
                      }`}
                    >
                      {renderHighlightedText(alert, activeRead, "alerts", index)}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {checklistItems.length > 0 && (
              <div className={`order-4 bg-card rounded-2xl p-6 shadow-card border ${activeSection === "checklist" ? "border-primary/30" : "border-transparent"}`}>
                <div className="flex items-center justify-between gap-3 mb-3">
                  <div className="flex items-center gap-2">
                    <CheckCircle className="w-5 h-5 text-primary" />
                    <h3 className="font-semibold text-foreground">{tr(language, "result_checklist")}</h3>
                  </div>
                  {sectionButton("checklist")}
                </div>
                <div className="space-y-2">
                  {checklistItems.map((item, index) => (
                    <div
                      key={index}
                      className={`rounded-xl px-3 py-2 text-sm text-foreground transition-colors ${
                        activeRead?.section === "checklist" && activeRead.itemIndex === index
                          ? "bg-primary/5 border border-primary/20"
                          : "bg-muted/50"
                      }`}
                    >
                      {renderHighlightedText(item, activeRead, "checklist", index)}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="order-5 bg-muted rounded-2xl p-6">
              <h3 className="text-sm font-semibold text-foreground mb-3">{tr(language, "result_trace_title")}</h3>
              <div className="space-y-2">
                {openDataSnapshot.trace.map((trace, index) => (
                  <div key={index} className="flex items-center gap-2 text-xs text-muted-foreground">
                    <ChevronRight className="w-3 h-3" />
                    <span className="font-mono text-primary font-medium">{trace.agent}</span>
                    <span>→ {trace.action}: {trace.result}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === "map" && (
          <div className="space-y-4 animate-slide-up">
            <div className="bg-card rounded-2xl p-4 shadow-card flex items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <MapPin className="w-5 h-5 text-primary shrink-0" />
                <div>
                  <p className="font-medium text-sm text-foreground">
                    {language === "zh" ? "我的位置" : language === "de" ? "Mein Standort" : "My Location"}
                  </p>
                  {userLocation ? (
                    <p className="text-xs text-muted-foreground">
                      {userLocation[0].toFixed(5)}, {userLocation[1].toFixed(5)}
                    </p>
                  ) : locationError ? (
                    <p className="text-xs text-destructive">{locationError}</p>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      {language === "zh" ? "点击定位" : language === "de" ? "Klicken zum Orten" : "Click to locate"}
                    </p>
                  )}
                </div>
              </div>
              <Button
                size="sm"
                variant={userLocation ? "outline" : "default"}
                onClick={locateUser}
                disabled={locating}
                className="rounded-xl shrink-0"
              >
                {locating ? <ChevronRight className="w-4 h-4 animate-pulse" /> : <LocateFixed className="w-4 h-4" />}
                <span className="ml-1.5 text-xs">
                  {userLocation
                    ? (language === "zh" ? "重新定位" : language === "de" ? "Neu orten" : "Re-locate")
                    : (language === "zh" ? "定位我" : language === "de" ? "Orten" : "Locate me")}
                </span>
              </Button>
            </div>

            <div className="rounded-2xl overflow-hidden shadow-card">
              <RouteMap
                stepCoords={routeCoords}
                userLocation={userLocation}
                barriers={openDataSnapshot.hotspots}
                amenities={openDataSnapshot.nearbyAmenities}
                height={420}
              />
            </div>

            <div className="bg-muted rounded-2xl p-4 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
              <div className="flex items-center gap-2">
                <span className="w-5 h-5 rounded-full bg-indigo-500 text-white flex items-center justify-center text-[10px] font-bold shrink-0">1</span>
                <span>{language === "zh" ? "路线步骤" : language === "de" ? "Route-Schritt" : "Route step"}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-blue-500 border-2 border-white shadow shrink-0" />
                <span>{language === "zh" ? "我的位置" : language === "de" ? "Mein Standort" : "My location"}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-4 h-4 rounded bg-orange-500 flex items-center justify-center text-[10px] shrink-0">!</span>
                <span>{language === "zh" ? "障碍热点" : language === "de" ? "Barriere-Hotspot" : "Barrier hotspot"}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-4 h-4 rounded bg-green-500 flex items-center justify-center text-[10px] shrink-0">🚻</span>
                <span>{language === "zh" ? "附近设施" : language === "de" ? "Nahe Einrichtung" : "Nearby amenity"}</span>
              </div>
            </div>
          </div>
        )}

        {tab === "profile" && (
          <div className="space-y-4 animate-slide-up">
            {(["mobility", "vision", "hearing", "cognitive"] as const).map((domain) => {
              const data = profile[domain];
              return (
                <div key={domain} className="bg-card rounded-2xl p-6 shadow-card">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-semibold text-foreground capitalize">{domain}</h3>
                    <span className="text-xs px-2 py-1 rounded-full bg-muted text-muted-foreground">
                      {(data.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {Object.entries(data)
                      .filter(([key]) => key !== "confidence")
                      .map(([key, value]) => (
                        <div key={key} className="flex items-center gap-2 text-sm">
                          <span className={`w-2 h-2 rounded-full ${value === true ? "bg-primary" : value === false ? "bg-muted-foreground/30" : "bg-muted-foreground/10"}`} />
                          <span className="text-muted-foreground">{key.replace(/_/g, " ")}</span>
                          <span className="ml-auto text-foreground font-medium">
                            {value === null ? "—" : value ? "Yes" : "No"}
                          </span>
                        </div>
                      ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {tab === "json" && (
          <div className="animate-slide-up">
            <div className="bg-card rounded-2xl p-6 shadow-card">
              <div className="flex items-center gap-2 mb-3">
                <FileJson className="w-5 h-5 text-primary" />
                <h3 className="font-semibold text-foreground">accessibility_profile</h3>
              </div>
              <pre className="bg-muted rounded-xl p-4 text-xs overflow-x-auto text-foreground font-mono leading-relaxed">
                {JSON.stringify(profile, null, 2)}
              </pre>
            </div>
          </div>
        )}

        <div className="mt-8 text-center">
          <div className="flex items-center justify-center gap-3">
            <Button variant="outline" onClick={onRefine} className="rounded-xl">
              {tr(language, "result_refine")}
            </Button>
            <Button variant="outline" onClick={onRestart} className="rounded-xl">
              <RotateCcw className="w-4 h-4 mr-2" />
              {tr(language, "result_restart")}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ResultsView;
