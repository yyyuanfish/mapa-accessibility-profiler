"""Zurich Open Data WFS client.

Fetches live accessibility data from the Stadt Zürich WFS geoportal (CC0 licence):
  - ZüriACT accessibility barriers (auspraegung severity 1–5)
  - Züri WC accessible toilets (wheelchair-filtered layer)
  - Disabled parking spots (Behindertenparkplätze)

Network calls are cached for 5 minutes. Falls back gracefully to empty lists
if any API is unreachable, so the pipeline always continues.

Coordinate handling:
  GeoJSON spec (RFC 7946) requires WGS84 lon/lat.  Stadt Zürich WFS sometimes
  returns Swiss LV95 (EPSG:2056) coordinates even in GeoJSON output format.
  _parse_geometry_coords() handles both cases automatically.
"""
from __future__ import annotations

import concurrent.futures
import json
import math
import time
import urllib.error
import urllib.request
from typing import Any

# ── WFS endpoints (Stadt Zürich, CC0) ─────────────────────────────────────────
_ZUERIACT_URL = (
    "https://www.ogd.stadt-zuerich.ch/wfs/geoportal/ZueriACT_barrierefreie_Mobilitaet"
)
_ZUERIWC_URL = (
    "https://www.ogd.stadt-zuerich.ch/wfs/geoportal/Zueri_WC"
)
_PARKING_URL = (
    "https://www.ogd.stadt-zuerich.ch/wfs/geoportal/Behindertenparkplaetze"
)

# WFS 1.0.0 — Stadt Zürich does NOT support WFS 2.0.0.
# Parameters: TYPENAME (singular, not TYPENAMES) and maxFeatures (not COUNT).
# BBOX filtering returns 0 results on this server; we fetch all and post-filter.
_WFS_BASE = "SERVICE=WFS&VERSION=1.0.0&REQUEST=GetFeature&OUTPUTFORMAT=application%2Fjson"
_FETCH_TIMEOUT = 15  # seconds per WFS call
_CACHE_TTL = 300.0   # 5 minutes

# ── Zurich area defaults ───────────────────────────────────────────────────────
#: HB = Zürich Hauptbahnhof (WGS84 lat, lon)
ZURICH_HB_CENTER = (47.3782, 8.5403)

#: Per-route Zurich area centres for spatial queries  (lat, lon)
ROUTE_ZURICH_CENTERS: dict[str, tuple[float, float]] = {
    "route_with_stairs":        (47.3782, 8.5403),   # generic HB area
    "step_free_route":          (47.3782, 8.5403),   # generic HB area
    "long_walk_route":          (47.3700, 8.5430),   # Bellevue / Limmatquai
    "zurich_hb_to_rathaus":     (47.3745, 8.5417),   # HB → Rathaus midpoint
    "zurich_hb_to_rathaus_sf":  (47.3745, 8.5417),   # same midpoint
}

# ── ZüriACT severity labels ────────────────────────────────────────────────────
SEVERITY_LABELS: dict[int, str] = {
    1: "passable",          # passierbar
    2: "conditional",       # bedingt passierbar
    3: "restricted",        # eingeschränkt passierbar
    4: "barely_passable",   # kaum passierbar
    5: "impassable",        # nicht passierbar
}

# ── In-memory TTL cache: key → (timestamp_s, payload) ─────────────────────────
_wfs_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _cache_get(key: str) -> list[dict[str, Any]] | None:
    entry = _wfs_cache.get(key)
    if entry and (time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, data: list[dict[str, Any]]) -> None:
    _wfs_cache[key] = (time.time(), data)


# ── Coordinate helpers ─────────────────────────────────────────────────────────

def _lv95_to_wgs84(east: float, north: float) -> tuple[float, float]:
    """Approximate Swiss LV95 → WGS84 conversion (Swisstopo formula, <1m error)."""
    E = (east  - 2_600_000) / 1_000_000
    N = (north - 1_200_000) / 1_000_000
    lon_deg = (
        2.6779094
        + 4.728982 * E
        + 0.791484 * E * N
        + 0.1306   * E * N**2
        - 0.0436   * E**3
    ) * 100 / 36
    lat_deg = (
        16.9023892
        + 3.238272 * N
        - 0.270978 * E**2
        - 0.002528 * N**2
        - 0.0447   * E**2 * N
        - 0.0140   * N**3
    ) * 100 / 36
    return lat_deg, lon_deg


def _parse_geometry_coords(coords: list) -> tuple[float, float] | None:
    """Return (lat, lon) from GeoJSON coordinates array.

    Handles:
      • WGS84 [lon, lat]  — standard GeoJSON
      • LV95  [East, North] — non-compliant Stadt Zürich WFS output
    """
    if len(coords) < 2:
        return None
    x, y = float(coords[0]), float(coords[1])
    # LV95 easting for Switzerland: ~2,480,000 – 2,840,000
    if x > 400_000:
        return _lv95_to_wgs84(x, y)
    # Standard GeoJSON: [longitude, latitude]
    return y, x  # (lat, lon)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres between two WGS-84 points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi   = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def bbox_from_center(
    lat: float,
    lon: float,
    radius_m: float = 1000.0,
) -> tuple[float, float, float, float]:
    """Return (minLon, minLat, maxLon, maxLat) bounding box."""
    lat_delta = radius_m / 111_000
    lon_delta = radius_m / (111_000 * math.cos(math.radians(lat)))
    return (lon - lon_delta, lat - lat_delta, lon + lon_delta, lat + lat_delta)


# ── Core WFS fetcher ───────────────────────────────────────────────────────────

def _fetch_wfs_geojson(
    base_url: str,
    typename: str,
    max_features: int = 500,
) -> list[dict[str, Any]]:
    """Fetch a WFS layer as GeoJSON and return normalised feature dicts.

    Each returned dict has keys: ``lat``, ``lon``, ``properties``.

    Stadt Zürich WFS notes:
      • Supports WFS 1.0.0 only (2.0.0 returns HTTP 500)
      • Uses ``TYPENAME`` (singular) and ``maxFeatures``
      • BBOX filtering returns 0 features — fetch all, post-filter by distance

    Returns an empty list on any network, HTTP, or parse error.
    """
    cache_key = f"{typename}|{max_features}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    params = f"{_WFS_BASE}&TYPENAME={typename}&maxFeatures={max_features}"
    url = f"{base_url}?{params}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
        fc = json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError, OSError, Exception) as exc:
        print(f"[zurich_data_provider] WFS fetch failed ({typename}): {exc}")
        return []

    features: list[dict[str, Any]] = []
    for feat in fc.get("features", []):
        geom  = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        parsed = _parse_geometry_coords(geom.get("coordinates", []))
        if parsed is None:
            continue
        lat, lon = parsed
        features.append({"lat": lat, "lon": lon, "properties": props})

    _cache_set(cache_key, features)
    return features


# ── Public fetch functions ─────────────────────────────────────────────────────

def fetch_zueriact_barriers(
    center_lat: float = ZURICH_HB_CENTER[0],
    center_lon: float = ZURICH_HB_CENTER[1],
    radius_m: float = 1000.0,
) -> list[dict[str, Any]]:
    """Return ZüriACT barrier points within *radius_m* of centre.

    Fetches up to 500 features city-wide and post-filters by distance.
    Each dict has keys:
      ``lat``, ``lon``, ``category``, ``severity`` (1–5), ``severity_label``,
      ``tags``, ``quartier``, ``temporary`` (bool), ``distance_m`` (from centre).
    """
    raw = _fetch_wfs_geojson(_ZUERIACT_URL, "zueriact_daten_aufbereitet", max_features=500)

    barriers: list[dict[str, Any]] = []
    for feat in raw:
        dist = haversine_m(feat["lat"], feat["lon"], center_lat, center_lon)
        if dist > radius_m:
            continue
        props = feat["properties"]
        raw_sev = props.get("auspraegung")
        try:
            severity = int(round(float(raw_sev))) if raw_sev is not None else 3
        except (TypeError, ValueError):
            severity = 3
        severity = max(1, min(5, severity))

        barriers.append({
            "lat": feat["lat"],
            "lon": feat["lon"],
            "category": (
                props.get("beschriftungs_kategorie")
                or props.get("kategorie")
                or "unknown"
            ),
            "severity": severity,
            "severity_label": SEVERITY_LABELS[severity],
            "tags": props.get("tags") or "",
            "quartier": props.get("quartier") or "",
            "temporary": bool(props.get("temporaer", 0)),
            "distance_m": round(dist),
        })

    # Sort by severity desc so worst barriers appear first
    barriers.sort(key=lambda b: -b["severity"])
    return barriers


def fetch_accessible_toilets(
    center_lat: float = ZURICH_HB_CENTER[0],
    center_lon: float = ZURICH_HB_CENTER[1],
    radius_m: float = 1000.0,
) -> list[dict[str, Any]]:
    """Return Züri WC accessible toilets within *radius_m* of centre.

    Fetches the ``poi_zueriwc_rs_view`` layer (wheelchair-filtered by Stadt Zürich).
    Post-filters by distance.  Each dict has keys:
      ``lat``, ``lon``, ``name``, ``address``, ``category``,
      ``wheelchair_accessible`` (True — guaranteed by layer), ``opening_hours``,
      ``free`` (bool), ``distance_m``.
    """
    # poi_zueriwc_rs_view is the wheelchair-filtered layer — all entries are accessible
    raw = _fetch_wfs_geojson(_ZUERIWC_URL, "poi_zueriwc_rs_view", max_features=200)

    toilets: list[dict[str, Any]] = []
    for feat in raw:
        dist = haversine_m(feat["lat"], feat["lon"], center_lat, center_lon)
        if dist > radius_m:
            continue
        props = feat["properties"]

        # "gebuehren" field is a text description; check for "kostenlos" / "gebührenfrei"
        fee_text = (props.get("gebuehren") or props.get("infrastruktur") or "").lower()
        is_free = "kostenlos" in fee_text or "gebührenfrei" in fee_text

        toilets.append({
            "lat": feat["lat"],
            "lon": feat["lon"],
            "name": props.get("name") or "Züri WC",
            "address": props.get("adresse") or props.get("standort") or "",
            "category": props.get("kategorie") or "WC (rollstuhlgängig)",
            "wheelchair_accessible": True,  # layer is wheelchair-filtered
            "opening_hours": props.get("oeffnungsz") or "",
            "free": is_free,
            "distance_m": round(dist),
        })

    toilets.sort(key=lambda t: t["distance_m"])
    return toilets


def fetch_disabled_parking(
    center_lat: float = ZURICH_HB_CENTER[0],
    center_lon: float = ZURICH_HB_CENTER[1],
    radius_m: float = 1500.0,
) -> list[dict[str, Any]]:
    """Return disabled parking spots within *radius_m* of centre.

    Post-filters by distance.  Each dict has keys:
      ``lat``, ``lon``, ``address``, ``type``, ``fee_required`` (bool),
      ``distance_m``.
    """
    raw = _fetch_wfs_geojson(_PARKING_URL, "behindertenparkplaetze_dav_p", max_features=200)

    spots: list[dict[str, Any]] = []
    for feat in raw:
        dist = haversine_m(feat["lat"], feat["lon"], center_lat, center_lon)
        if dist > radius_m:
            continue
        props = feat["properties"]
        # "gebpflicht" is "0" (no fee) or "1" (fee required) as a string
        gebpflicht = props.get("gebpflicht", "0")
        fee_required = str(gebpflicht).strip() not in ("0", "", "false", "False", None)

        spots.append({
            "lat": feat["lat"],
            "lon": feat["lon"],
            "address": props.get("adresse") or "",
            "type": props.get("art") or "Behindertenparkplatz",
            "fee_required": fee_required,
            "distance_m": round(dist),
        })

    spots.sort(key=lambda s: s["distance_m"])
    return spots


# ── Parallel fetch convenience ─────────────────────────────────────────────────

def fetch_all_zurich_data(
    center_lat: float = ZURICH_HB_CENTER[0],
    center_lon: float = ZURICH_HB_CENTER[1],
    barrier_radius_m: float = 1000.0,
    amenity_radius_m: float = 1000.0,
) -> dict[str, Any]:
    """Fetch ZüriACT barriers, toilets, and parking in three parallel WFS calls.

    Uses an internal thread pool so that 15 s I/O waits overlap.
    All failures are caught; the pipeline always receives at least empty lists.

    Returns::

        {
          "barriers": [...],   # ZüriACT accessibility barriers
          "toilets":  [...],   # Züri WC (wheelchair-filtered layer)
          "parking":  [...],   # Disabled parking spots
          "errors":   [...]    # any fetch error messages
        }
    """
    errors: list[str] = []

    def _safe_fetch(fn, *args):
        try:
            return fn(*args)
        except Exception as exc:
            errors.append(f"{fn.__name__}: {exc}")
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        f_barriers = pool.submit(_safe_fetch, fetch_zueriact_barriers,
                                  center_lat, center_lon, barrier_radius_m)
        f_toilets  = pool.submit(_safe_fetch, fetch_accessible_toilets,
                                  center_lat, center_lon, amenity_radius_m)
        f_parking  = pool.submit(_safe_fetch, fetch_disabled_parking,
                                  center_lat, center_lon, amenity_radius_m)

    return {
        "barriers": f_barriers.result(),
        "toilets":  f_toilets.result(),
        "parking":  f_parking.result(),
        "errors":   errors,
    }


# ── Scoring / analytics ────────────────────────────────────────────────────────

def score_route_barriers(
    barriers: list[dict[str, Any]],
    route_center_lat: float,
    route_center_lon: float,
    threshold_m: float = 400.0,
) -> dict[str, Any]:
    """Score ZüriACT barriers against a route centre point.

    Returns a summary dict suitable for embedding in the plan pipeline:
    ``total_barriers``, ``high_severity_count``, ``impassable_count``,
    ``categories``, ``worst_severity``, ``alerts``.
    """
    nearby = [
        b for b in barriers
        if haversine_m(b["lat"], b["lon"], route_center_lat, route_center_lon) <= threshold_m
    ]

    if not nearby:
        return {
            "total_barriers": 0,
            "high_severity_count": 0,
            "impassable_count": 0,
            "categories": [],
            "worst_severity": 0,
            "alerts": [],
        }

    worst      = max(b["severity"] for b in nearby)
    high_sev   = [b for b in nearby if b["severity"] >= 4]
    impassable = [b for b in nearby if b["severity"] == 5]
    categories = list({b["category"] for b in nearby if b["category"] != "unknown"})

    alerts: list[str] = []
    if impassable:
        cats = ", ".join(list({b["category"] for b in impassable})[:2])
        alerts.append(
            f"ZüriACT: {len(impassable)} impassable barrier(s) in this area ({cats})."
        )
    elif high_sev:
        cats = ", ".join(list({b["category"] for b in high_sev})[:2])
        alerts.append(
            f"ZüriACT: {len(high_sev)} high-severity barrier(s) near route ({cats})."
        )

    return {
        "total_barriers":      len(nearby),
        "high_severity_count": len(high_sev),
        "impassable_count":    len(impassable),
        "categories":          categories,
        "worst_severity":      worst,
        "alerts":              alerts,
    }


def score_barriers_per_step(
    barriers: list[dict[str, Any]],
    step_coords: list[tuple[float, float]],
    step_radius_m: float = 80.0,
) -> list[dict[str, Any]]:
    """Score ZüriACT barriers for each individual route step.

    For each (lat, lon) in *step_coords*, collect barriers within *step_radius_m*
    and return a per-step summary.  This is more informative than a single
    route-midpoint score because it pinpoints exactly which steps have
    accessibility obstacles nearby.

    Returns a list parallel to *step_coords*::

        [
          {
            "step_index": 0,
            "lat": 47.378, "lon": 8.540,
            "barrier_count": 3,
            "worst_severity": 4,
            "worst_label": "barely_passable",
            "categories": ["Oberflächenproblem", "Hindernis im Weg"],
            "alerts": ["..."]   # non-empty when severity ≥ 4
          },
          ...
        ]
    """
    result: list[dict[str, Any]] = []
    for i, (lat, lon) in enumerate(step_coords):
        nearby = [
            b for b in barriers
            if haversine_m(b["lat"], b["lon"], lat, lon) <= step_radius_m
        ]
        worst = max((b["severity"] for b in nearby), default=0)
        high   = [b for b in nearby if b["severity"] >= 4]
        cats   = list({b["category"] for b in nearby if b["category"] != "unknown"})

        step_alerts: list[str] = []
        if any(b["severity"] == 5 for b in nearby):
            impass = [b for b in nearby if b["severity"] == 5]
            step_alerts.append(
                f"Step {i+1}: {len(impass)} impassable barrier(s) nearby"
                f" ({', '.join(list({b['category'] for b in impass})[:2])})."
            )
        elif high:
            step_alerts.append(
                f"Step {i+1}: {len(high)} high-severity barrier(s) nearby"
                f" ({', '.join(list({b['category'] for b in high})[:2])})."
            )

        result.append({
            "step_index":    i,
            "lat":           lat,
            "lon":           lon,
            "barrier_count": len(nearby),
            "worst_severity": worst,
            "worst_label":   SEVERITY_LABELS.get(worst, "none"),
            "categories":    cats,
            "alerts":        step_alerts,
        })
    return result


def find_nearest_amenity(
    amenities: list[dict[str, Any]],
    center_lat: float,
    center_lon: float,
    max_distance_m: float = 600.0,
) -> dict[str, Any] | None:
    """Return the amenity closest to *center* that is within *max_distance_m*."""
    best: dict[str, Any] | None = None
    best_dist = float("inf")
    for a in amenities:
        d = haversine_m(a["lat"], a["lon"], center_lat, center_lon)
        if d < best_dist and d <= max_distance_m:
            best_dist = d
            best = {**a, "distance_m": round(d)}
    return best
