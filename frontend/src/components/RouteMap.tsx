/**
 * RouteMap — Leaflet-based interactive map for MAPA Accessibility Profiler.
 *
 * Shows:
 *  • User's GPS location (blue pulsing dot)
 *  • Route polyline (step coords from backend ROUTE_STEP_COORDS)
 *  • Step markers numbered 1…N
 *  • ZüriACT barrier markers (severity-coloured)
 *  • Nearest accessible toilet marker (green)
 *  • Nearest disabled parking marker (blue)
 *
 * Uses OpenStreetMap tiles — no API key required.
 */

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Fix the broken default Leaflet marker icon paths that Vite/webpack break
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

export interface BarrierPoint {
  lat: number;
  lon: number;
  severity: number; // 1–5
  category: string;
}

export interface AmenityPoint {
  lat: number;
  lon: number;
  name: string;
  type: "toilet" | "parking";
  address?: string;
  free?: boolean;
  opening_hours?: string;
}

interface RouteMapProps {
  /** [lat, lon] pairs for each route step */
  stepCoords?: [number, number][];
  /** User's current GPS location [lat, lon] */
  userLocation?: [number, number] | null;
  /** ZüriACT barrier points */
  barriers?: BarrierPoint[];
  /** Nearest toilet / parking amenities */
  amenities?: AmenityPoint[];
  /** Map height in pixels (default 400) */
  height?: number;
}

// Severity → marker colour
function severityColor(s: number): string {
  if (s >= 5) return "#dc2626"; // impassable — red
  if (s >= 4) return "#f97316"; // barely passable — orange
  if (s >= 3) return "#eab308"; // restricted — yellow
  return "#22c55e";             // passable / conditional — green
}

function makeCircleMarker(color: string, title: string): L.CircleMarker {
  return L.circleMarker([0, 0], {
    radius: 7,
    color,
    fillColor: color,
    fillOpacity: 0.7,
    weight: 1.5,
    title,
  });
}

export default function RouteMap({
  stepCoords = [],
  userLocation = null,
  barriers = [],
  amenities = [],
  height = 400,
}: RouteMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Initialise once
    if (!mapRef.current) {
      const map = L.map(containerRef.current, { zoomControl: true });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(map);
      mapRef.current = map;
    }

    const map = mapRef.current;

    // Clear existing layers (except tile layer)
    map.eachLayer((layer) => {
      if (!(layer instanceof L.TileLayer)) map.removeLayer(layer);
    });

    const bounds: L.LatLng[] = [];

    // ── Route polyline + step markers ──────────────────────────────────────
    if (stepCoords.length > 0) {
      const latlngs = stepCoords.map(([lat, lon]) => L.latLng(lat, lon));
      bounds.push(...latlngs);

      // Draw route line
      L.polyline(latlngs, {
        color: "#6366f1", // indigo
        weight: 4,
        opacity: 0.85,
        lineCap: "round",
        lineJoin: "round",
      }).addTo(map);

      // Numbered step markers
      stepCoords.forEach(([lat, lon], idx) => {
        const icon = L.divIcon({
          className: "",
          html: `<div style="
            width:26px;height:26px;border-radius:50%;
            background:#6366f1;color:#fff;
            font-size:12px;font-weight:700;
            display:flex;align-items:center;justify-content:center;
            border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);
          ">${idx + 1}</div>`,
          iconSize: [26, 26],
          iconAnchor: [13, 13],
        });
        L.marker([lat, lon], { icon })
          .bindPopup(`<b>Step ${idx + 1}</b>`)
          .addTo(map);
      });
    }

    // ── Barrier markers ────────────────────────────────────────────────────
    // Only show high-severity ones (≥ 4) to avoid cluttering at scale
    const highBarriers = barriers.filter((b) => b.severity >= 4);
    highBarriers.forEach((b) => {
      const m = makeCircleMarker(
        severityColor(b.severity),
        `${b.category} (severity ${b.severity})`
      );
      m.setLatLng([b.lat, b.lon]);
      m.bindPopup(
        `<b>${b.category}</b><br>Severity: ${b.severity}/5`
      );
      m.addTo(map);
    });

    // ── Amenity markers ────────────────────────────────────────────────────
    amenities.forEach((a) => {
      const color = a.type === "toilet" ? "#10b981" : "#3b82f6";
      const icon = L.divIcon({
        className: "",
        html: `<div style="
          width:22px;height:22px;border-radius:4px;
          background:${color};color:#fff;font-size:13px;
          display:flex;align-items:center;justify-content:center;
          border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);
        ">${a.type === "toilet" ? "🚻" : "🅿"}</div>`,
        iconSize: [22, 22],
        iconAnchor: [11, 11],
      });
      L.marker([a.lat, a.lon], { icon })
        .bindPopup(
          `<b>${a.name}</b><br>` +
          (a.address ? `${a.address}<br>` : "") +
          (a.opening_hours ? `Open: ${a.opening_hours}<br>` : "") +
          (a.free !== undefined ? (a.free ? "Free" : "Paid") : "")
        )
        .addTo(map);
      bounds.push(L.latLng(a.lat, a.lon));
    });

    // ── User GPS location ──────────────────────────────────────────────────
    if (userLocation) {
      const [lat, lon] = userLocation;
      const icon = L.divIcon({
        className: "",
        html: `<div style="
          width:16px;height:16px;border-radius:50%;
          background:#3b82f6;border:3px solid #fff;
          box-shadow:0 0 0 3px rgba(59,130,246,.4);
        "></div>`,
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      });
      L.marker([lat, lon], { icon })
        .bindPopup("<b>Your location</b>")
        .addTo(map);
      bounds.push(L.latLng(lat, lon));
    }

    // ── Fit view ───────────────────────────────────────────────────────────
    if (bounds.length > 0) {
      map.fitBounds(L.latLngBounds(bounds), { padding: [40, 40], maxZoom: 16 });
    } else {
      // Default to Zürich HB if no data
      map.setView([47.3782, 8.5403], 14);
    }

    // Leaflet needs a resize nudge after the DOM settles
    requestAnimationFrame(() => map.invalidateSize());
  }, [stepCoords, userLocation, barriers, amenities]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{ height, width: "100%", borderRadius: "12px", overflow: "hidden" }}
      aria-label="Route map"
    />
  );
}
