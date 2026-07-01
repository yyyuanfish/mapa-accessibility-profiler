import type { AccessibilityProfile } from "./profiling-engine";
import type { AppLanguage } from "./runtime-context";

export type MapBarrierPoint = {
  lat: number;
  lon: number;
  severity: number;
  category: string;
};

export type MapAmenityPoint = {
  lat: number;
  lon: number;
  name: string;
  type: "toilet" | "parking";
  address?: string;
  free?: boolean;
  opening_hours?: string;
};

export interface BarrierHotspot extends MapBarrierPoint {
  id: string;
  title: string;
  distance_m: number;
  description: string;
  stepIndex?: number;
}

export interface PlanningTraceEntry {
  agent: string;
  action: string;
  result: string;
}

export interface OpenDataSourceItem {
  name: string;
  updated: string;
  affects: string;
  freshness: "current" | "reference";
}

export interface OpenDataSnapshot {
  routeLabel: string;
  summary: string;
  sourceLabel: string;
  updatedLabel: string;
  counts: {
    barriers: number;
    highSeverity: number;
    toilets: number;
    parking: number;
  };
  hotspots: BarrierHotspot[];
  nearbyAmenities: MapAmenityPoint[];
  alerts: string[];
  stepNotes: Record<number, string[]>;
  trace: PlanningTraceEntry[];
  sources: OpenDataSourceItem[];
}

const ROUTE_COORDS: Record<string, [number, number][]> = {
  route_with_stairs: [
    [47.3782, 8.5403],
    [47.3772, 8.5399],
    [47.3765, 8.5418],
    [47.3748, 8.5428],
    [47.3729, 8.5432],
  ],
  step_free_route: [
    [47.3778, 8.5402],
    [47.3775, 8.5401],
    [47.3764, 8.5410],
    [47.3745, 8.5418],
    [47.3728, 8.5431],
  ],
  long_walk_route: [
    [47.3702, 8.5430],
    [47.3686, 8.5441],
    [47.3671, 8.5467],
  ],
  zurich_hb_to_rathaus: [
    [47.3782, 8.5403],
    [47.3772, 8.5399],
    [47.3765, 8.5430],
    [47.3706, 8.5435],
  ],
  zurich_hb_to_rathaus_sf: [
    [47.3778, 8.5402],
    [47.3775, 8.5401],
    [47.3745, 8.5418],
    [47.3706, 8.5435],
  ],
};

function routeLabel(routeId: string, language: AppLanguage): string {
  const names = {
    route_with_stairs: {
      en: "Station to City Hall (fastest)",
      zh: "车站到市政厅（最快）",
      de: "Bahnhof zum Rathaus (schnellste Route)",
    },
    step_free_route: {
      en: "Station to City Hall (step-free)",
      zh: "车站到市政厅（无台阶）",
      de: "Bahnhof zum Rathaus (stufenfrei)",
    },
    long_walk_route: {
      en: "Park Loop (scenic)",
      zh: "公园环线（风景路线）",
      de: "Parkrunde (landschaftlich)",
    },
    zurich_hb_to_rathaus: {
      en: "Zürich HB to Rathaus",
      zh: "苏黎世火车总站到市政厅",
      de: "Zürich HB zum Rathaus",
    },
    zurich_hb_to_rathaus_sf: {
      en: "Zürich HB to Rathaus (step-free)",
      zh: "苏黎世火车总站到市政厅（无台阶）",
      de: "Zürich HB zum Rathaus (stufenfrei)",
    },
  } as const;
  return names[routeId as keyof typeof names]?.[language] ?? names.zurich_hb_to_rathaus[language];
}

function liveSummary(routeId: string, language: AppLanguage): string {
  const isZurich = routeId.startsWith("zurich_");
  if (language === "zh") {
    return isZurich
      ? "界面已把路线说明和苏黎世开放数据的障碍点、无障碍厕所与残障停车位关联起来。"
      : "当前为演示性开放数据视图，用于展示障碍点和附近设施如何进入路线解释。";
  }
  if (language === "de") {
    return isZurich
      ? "Die Wegbeschreibung ist jetzt mit Zürcher Open-Data-Hindernissen, barrierefreien Toiletten und Parkplätzen verknüpft."
      : "Dies ist eine demonstrative Open-Data-Ansicht, die zeigt, wie Hindernisse und nahe Einrichtungen in die Routenbeschreibung eingehen.";
  }
  return isZurich
    ? "This route view is now tied to Zurich open-data barriers, accessible toilets, and disabled parking."
    : "This is a demo open-data view showing how barriers and nearby amenities can shape route guidance.";
}

function sourceLabel(language: AppLanguage): string {
  if (language === "zh") return "苏黎世开放数据参考快照";
  if (language === "de") return "Zurich-OGD-Referenzsnapshot";
  return "Zurich OGD reference snapshot";
}

function updatedLabel(language: AppLanguage): string {
  if (language === "zh") return "刚刚更新";
  if (language === "de") return "eben aktualisiert";
  return "just now";
}

export function getMockRouteCoords(routeId: string): [number, number][] {
  return ROUTE_COORDS[routeId] ?? ROUTE_COORDS.zurich_hb_to_rathaus;
}

export function buildOpenDataSnapshot(
  routeId: string,
  profile: AccessibilityProfile,
  language: AppLanguage,
): OpenDataSnapshot {
  const isZurich = routeId.startsWith("zurich_");
  const needsStepFree =
    profile.mobility.wheelchair_user === true || profile.mobility.step_free_route === true;
  const simpleLanguage = profile.cognitive.simple_language === true;
  const trace: PlanningTraceEntry[] = isZurich
    ? [
        { agent: "input_validator_node", action: "validate_profile", result: "schema valid" },
        { agent: "zurich_data_fetcher_node", action: "load_reference_context", result: "293 barriers · 59 toilets · 127 parking" },
        { agent: "route_reasoner_node", action: "select_route", result: needsStepFree ? "switched to step-free Zurich route" : "kept requested Zurich route" },
        { agent: "amenity_locator_node", action: "score_hotspots", result: "2 hotspot steps and 2 nearby amenities surfaced" },
        { agent: "hazard_fusion_node", action: "merge_route_and_city_data", result: "barrier severity merged into alerts" },
        { agent: "planner_node", action: "draft_plan", result: simpleLanguage ? "simple-language route plan" : "standard route plan" },
        { agent: "synthesis_node", action: "format_output", result: language },
      ]
    : [
        { agent: "input_validator_node", action: "validate_profile", result: "schema valid" },
        { agent: "zurich_data_fetcher_node", action: "attach_demo_context", result: "demo barriers and amenities loaded" },
        { agent: "route_reasoner_node", action: "select_route", result: needsStepFree ? "step-free route selected" : "default route selected" },
        { agent: "amenity_locator_node", action: "surface_nearby_help", result: "1 toilet and 1 parking candidate" },
        { agent: "hazard_fusion_node", action: "merge_context", result: "route metadata + mock OGD alerts" },
        { agent: "planner_node", action: "draft_plan", result: simpleLanguage ? "simple-language route plan" : "standard route plan" },
      ];

  const snapshot: OpenDataSnapshot = isZurich
    ? {
        routeLabel: routeLabel(routeId, language),
        summary: liveSummary(routeId, language),
        sourceLabel: sourceLabel(language),
        updatedLabel: updatedLabel(language),
        counts: {
          barriers: 293,
          highSeverity: 97,
          toilets: 59,
          parking: 127,
        },
        hotspots: [
          {
            id: "bahnhofquai-stairs",
            title: language === "zh" ? "Bahnhofquai 台阶与路缘热点" : language === "de" ? "Hotspot Bahnhofquai Treppe" : "Bahnhofquai stairs hotspot",
            category: "stairs / curb",
            severity: 5,
            distance_m: 42,
            lat: 47.3772,
            lon: 8.5399,
            stepIndex: 1,
            description: language === "zh" ? "在第 2 步附近检测到不可通行级别障碍。" : language === "de" ? "Nahe Schritt 2 wurde ein unpassierbares Hindernis markiert." : "An impassable barrier cluster is flagged near step 2.",
          },
          {
            id: "limmatquai-surface",
            title: language === "zh" ? "Limmatquai 路面问题" : language === "de" ? "Oberflächenproblem am Limmatquai" : "Limmatquai surface issue",
            category: "surface problem",
            severity: 4,
            distance_m: 68,
            lat: 47.3745,
            lon: 8.5418,
            stepIndex: 2,
            description: language === "zh" ? "第 3 步附近有高严重度路面障碍，需要减速。" : language === "de" ? "Nahe Schritt 3 liegt ein hochgradiges Oberflächenhindernis." : "A high-severity surface problem sits near step 3.",
          },
        ],
        nearbyAmenities: [
          {
            lat: 47.3777,
            lon: 8.5408,
            name: language === "zh" ? "HB 南翼无障碍厕所" : language === "de" ? "Barrierefreie Toilette HB Südtrakt" : "HB South Wing accessible toilet",
            type: "toilet",
            address: "Zürich HB",
            free: true,
            opening_hours: "24h",
          },
          {
            lat: 47.3779,
            lon: 8.5395,
            name: language === "zh" ? "Museumstrasse 残障停车位" : language === "de" ? "Behindertenparkplatz Museumstrasse" : "Museumstrasse disabled parking",
            type: "parking",
            address: "Museumstrasse 1",
            free: true,
          },
        ],
        alerts: [
          language === "zh"
            ? "ZüriACT 显示 Bahnhofquai 周边有 2 处不可通行障碍，建议走无台阶替代段。"
            : language === "de"
            ? "ZüriACT meldet 2 unpassierbare Hindernisse im Bereich Bahnhofquai; die stufenfreie Umgehung wird empfohlen."
            : "ZüriACT reports 2 impassable barriers near Bahnhofquai; the step-free segment is recommended.",
          language === "zh"
            ? "最近的无障碍厕所位于 HB 南翼，约 120 米。"
            : language === "de"
            ? "Die nächste barrierefreie Toilette liegt im Südtrakt des HB, etwa 120 m entfernt."
            : "The nearest accessible toilet is in the HB south wing, about 120 m away.",
        ],
        stepNotes: {
          1: [
            language === "zh"
              ? "开放数据提示：此处附近存在不可通行级别路缘与台阶障碍。"
              : language === "de"
              ? "Open-Data-Hinweis: Hier liegen unpassierbare Bordstein- und Treppenhindernisse."
              : "Open-data note: impassable curb and stair barriers are clustered here.",
          ],
          2: [
            language === "zh"
              ? "开放数据提示：Limmatquai 路面不平整，轮椅与助行器需减速。"
              : language === "de"
              ? "Open-Data-Hinweis: unebene Oberfläche am Limmatquai; Tempo reduzieren."
              : "Open-data note: uneven surface on Limmatquai; slow down for wheelchairs and walkers.",
          ],
        },
        sources: [
          {
            name: "ZüriACT barriers",
            updated: "2024-09-25",
            affects: language === "zh" ? "障碍提醒与步骤注释" : language === "de" ? "Warnungen und Schritt-Hinweise" : "alerts and step notes",
            freshness: "reference",
          },
          {
            name: "Züri WC",
            updated: "2026-04-14",
            affects: language === "zh" ? "最近无障碍厕所" : language === "de" ? "nahe barrierefreie Toiletten" : "nearby accessible toilets",
            freshness: "current",
          },
          {
            name: "Disabled parking",
            updated: "2017-10-09",
            affects: language === "zh" ? "附近停车位参考" : language === "de" ? "nahe Parkplätze als Referenz" : "nearby parking reference",
            freshness: "reference",
          },
        ],
        trace,
      }
    : {
        routeLabel: routeLabel(routeId, language),
        summary: liveSummary(routeId, language),
        sourceLabel: sourceLabel(language),
        updatedLabel: updatedLabel(language),
        counts: {
          barriers: 7,
          highSeverity: 2,
          toilets: 1,
          parking: 1,
        },
        hotspots: [
          {
            id: "demo-detour",
            title: language === "zh" ? "Main St 施工绕行" : language === "de" ? "Baustellen-Umleitung Main St" : "Main St construction detour",
            category: "construction",
            severity: 4,
            distance_m: 55,
            lat: 47.3772,
            lon: 8.5399,
            stepIndex: 2,
            description: language === "zh" ? "演示性障碍点，用于体现 route plan 如何接收数据更新。" : language === "de" ? "Demonstrations-Hotspot, um datenbasierte Routenanpassung zu zeigen." : "Demo hotspot showing how route guidance reacts to data changes.",
          },
        ],
        nearbyAmenities: [
          {
            lat: 47.3779,
            lon: 8.5404,
            name: language === "zh" ? "示例无障碍厕所" : language === "de" ? "Beispiel-Toilette" : "Example accessible toilet",
            type: "toilet",
            address: language === "zh" ? "站厅旁" : language === "de" ? "neben der Halle" : "next to the concourse",
            free: true,
          },
          {
            lat: 47.3780,
            lon: 8.5400,
            name: language === "zh" ? "示例残障停车位" : language === "de" ? "Beispiel-Parkplatz" : "Example disabled parking",
            type: "parking",
            address: language === "zh" ? "主街入口" : language === "de" ? "Eingang Main St" : "Main St entrance",
            free: true,
          },
        ],
        alerts: [
          language === "zh"
            ? "演示性开放数据提示：Main St 正在施工，系统已把绕行写入提醒。"
            : language === "de"
            ? "Demo-Open-Data-Hinweis: Auf der Main St gibt es eine Baustelle; die Umleitung wurde in die Hinweise übernommen."
            : "Demo open-data note: Main St has construction and the detour has been injected into the alerts.",
        ],
        stepNotes: {
          2: [
            language === "zh"
              ? "开放数据模拟：此步附近有施工障碍。"
              : language === "de"
              ? "Open-Data-Mock: In der Nähe dieses Schritts liegt eine Baustelle."
              : "Open-data mock: a construction barrier is close to this step.",
          ],
        },
        sources: [
          {
            name: "Mock barrier feed",
            updated: "demo",
            affects: language === "zh" ? "提醒与绕行说明" : language === "de" ? "Warnungen und Umleitung" : "alerts and detour copy",
            freshness: "current",
          },
          {
            name: "Mock amenity feed",
            updated: "demo",
            affects: language === "zh" ? "附近设施卡片" : language === "de" ? "nahe Einrichtungen" : "nearby amenity cards",
            freshness: "current",
          },
        ],
        trace,
      };

  if (needsStepFree) {
    snapshot.alerts.unshift(
      language === "zh"
        ? "由于检测到行动相关需求，路线已优先切换到无台阶方案。"
        : language === "de"
        ? "Wegen mobilitätsbezogener Bedürfnisse wurde eine stufenfreie Route priorisiert."
        : "Because a mobility-related need was detected, a step-free route was prioritized.",
    );
  }

  return snapshot;
}
