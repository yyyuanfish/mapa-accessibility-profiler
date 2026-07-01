from __future__ import annotations

from abc import ABC, abstractmethod

from backend.app.models import RawRoute


ROUTE_FIXTURES: dict[str, dict] = {
    "route_with_stairs": {
        "route_id": "route_with_stairs",
        "name": "Station to City Hall (fastest)",
        "step_free": False,
        "total_distance_m": 1200,
        "total_duration_min": 18,
        "steps": [
            {
                "instruction": "Walk 250m to Central Station Exit B.",
                "distance_m": 250,
                "duration_min": 4,
                "landmark": "Central Station"
            },
            {
                "instruction": "Take stairs up to Platform Bridge.",
                "distance_m": 80,
                "duration_min": 3,
                "has_stairs": True
            },
            {
                "instruction": "Listen for platform announcements before boarding Bus 9.",
                "distance_m": 500,
                "duration_min": 7,
                "audio_only_cue": True
            },
            {
                "instruction": "Walk 370m to City Hall main entrance.",
                "distance_m": 370,
                "duration_min": 4,
                "landmark": "City Hall"
            }
        ]
    },
    "step_free_route": {
        "route_id": "step_free_route",
        "name": "Station to City Hall (step-free)",
        "step_free": True,
        "total_distance_m": 1450,
        "total_duration_min": 24,
        "steps": [
            {
                "instruction": "Go 300m to Elevator Lobby at Central Station.",
                "distance_m": 300,
                "duration_min": 5,
                "landmark": "Elevator Lobby"
            },
            {
                "instruction": "Use elevator to street level.",
                "distance_m": 20,
                "duration_min": 2
            },
            {
                "instruction": "Continue 760m on flat sidewalk to Bus Stop C.",
                "distance_m": 760,
                "duration_min": 12,
                "landmark": "Bus Stop C"
            },
            {
                "instruction": "Go 370m to City Hall accessible entrance.",
                "distance_m": 370,
                "duration_min": 5,
                "landmark": "Accessible entrance"
            }
        ]
    },
    "long_walk_route": {
        "route_id": "long_walk_route",
        "name": "Park Loop (scenic)",
        "step_free": True,
        "total_distance_m": 3200,
        "total_duration_min": 46,
        "steps": [
            {
                "instruction": "Walk 1200m through Riverside Park path.",
                "distance_m": 1200,
                "duration_min": 17,
                "landmark": "Riverside Park"
            },
            {
                "instruction": "Continue 1100m along the promenade.",
                "distance_m": 1100,
                "duration_min": 16,
                "landmark": "Promenade"
            },
            {
                "instruction": "Walk 900m to destination plaza.",
                "distance_m": 900,
                "duration_min": 13,
                "landmark": "Destination plaza"
            }
        ]
    },
    # ── Real Zurich routes (Hauptbahnhof → Rathaus) ───────────────────────────
    "zurich_hb_to_rathaus": {
        "route_id": "zurich_hb_to_rathaus",
        "name": "Zürich HB → Rathaus (fastest)",
        "step_free": False,
        "total_distance_m": 950,
        "total_duration_min": 15,
        "steps": [
            {
                "instruction": "Walk from Zürich Hauptbahnhof main exit through Bahnhofplatz.",
                "distance_m": 200,
                "duration_min": 3,
                "landmark": "Zürich Hauptbahnhof"
            },
            {
                "instruction": "Take stairs down to Tram Stop Bahnhofquai (Tram 4/15 direction City).",
                "distance_m": 60,
                "duration_min": 2,
                "has_stairs": True
            },
            {
                "instruction": "Listen for tram announcements; board Tram 4 to Central (2 stops).",
                "distance_m": 400,
                "duration_min": 5,
                "audio_only_cue": True,
                "landmark": "Central"
            },
            {
                "instruction": "Walk 290m along Limmatquai to Zürich Rathaus (City Hall).",
                "distance_m": 290,
                "duration_min": 5,
                "landmark": "Zürich Rathaus"
            }
        ]
    },
    "zurich_hb_to_rathaus_sf": {
        "route_id": "zurich_hb_to_rathaus_sf",
        "name": "Zürich HB → Rathaus (step-free)",
        "step_free": True,
        "total_distance_m": 1150,
        "total_duration_min": 18,
        "steps": [
            {
                "instruction": "From HB main hall take the lift (Aufzug) to Bahnhofquai underground crossing.",
                "distance_m": 80,
                "duration_min": 3,
                "landmark": "HB Bahnhofquai Lift"
            },
            {
                "instruction": "Exit lift to street level at Bahnhofquai; turn left onto flat riverside path.",
                "distance_m": 120,
                "duration_min": 2,
                "landmark": "Bahnhofquai"
            },
            {
                "instruction": "Walk 600m along flat Limmatquai riverside path toward Rathaus.",
                "distance_m": 600,
                "duration_min": 9,
                "landmark": "Limmatquai"
            },
            {
                "instruction": "Arrive at Zürich Rathaus (Limmatquai 55). Ramp access from riverside.",
                "distance_m": 350,
                "duration_min": 4,
                "landmark": "Zürich Rathaus (accessible entrance)"
            }
        ]
    },
    "indoor_station_transfer_stairs": {
        "route_id": "indoor_station_transfer_stairs",
        "name": "Indoor Station Transfer (stairs)",
        "step_free": False,
        "total_distance_m": 420,
        "total_duration_min": 9,
        "steps": [
            {
                "instruction": "Enter the station concourse and look for the blue transfer signs.",
                "distance_m": 90,
                "duration_min": 2,
                "landmark": "Station concourse",
                "visual_only_cue": True
            },
            {
                "instruction": "Take the stairs down to the lower platform corridor.",
                "distance_m": 40,
                "duration_min": 2,
                "has_stairs": True
            },
            {
                "instruction": "Listen for the platform announcement before entering Track 4.",
                "distance_m": 160,
                "duration_min": 3,
                "audio_only_cue": True,
                "landmark": "Track 4"
            },
            {
                "instruction": "Look for the green exit sign at the end of the corridor.",
                "distance_m": 130,
                "duration_min": 2,
                "landmark": "Exit corridor",
                "visual_only_cue": True
            }
        ]
    },
    "indoor_station_transfer_elevator": {
        "route_id": "indoor_station_transfer_elevator",
        "name": "Indoor Station Transfer (elevator)",
        "step_free": True,
        "total_distance_m": 520,
        "total_duration_min": 12,
        "steps": [
            {
                "instruction": "Go to the staffed information desk beside the main concourse.",
                "distance_m": 110,
                "duration_min": 3,
                "landmark": "Information desk"
            },
            {
                "instruction": "Use the elevator beside the ticket machines to reach the lower corridor.",
                "distance_m": 50,
                "duration_min": 3,
                "landmark": "Elevator beside ticket machines"
            },
            {
                "instruction": "Follow the flat corridor to Track 4 and check the electronic board.",
                "distance_m": 220,
                "duration_min": 4,
                "landmark": "Electronic board"
            },
            {
                "instruction": "Continue to the accessible exit beside the service counter.",
                "distance_m": 140,
                "duration_min": 2,
                "landmark": "Service counter"
            }
        ]
    },
    "indoor_museum_visual_signage": {
        "route_id": "indoor_museum_visual_signage",
        "name": "Museum Entrance to Gallery Wing",
        "step_free": True,
        "total_distance_m": 360,
        "total_duration_min": 8,
        "steps": [
            {
                "instruction": "Look for the red Gallery B sign above the main hall doorway.",
                "distance_m": 80,
                "duration_min": 2,
                "landmark": "Main hall doorway",
                "visual_only_cue": True
            },
            {
                "instruction": "Walk through the quiet sculpture hall to the tactile floor strip.",
                "distance_m": 150,
                "duration_min": 3,
                "landmark": "Sculpture hall"
            },
            {
                "instruction": "See the glass wall and turn right toward Gallery B.",
                "distance_m": 130,
                "duration_min": 3,
                "landmark": "Glass wall",
                "visual_only_cue": True
            }
        ]
    },
    "indoor_noisy_platform_audio": {
        "route_id": "indoor_noisy_platform_audio",
        "name": "Noisy Platform Transfer",
        "step_free": True,
        "total_distance_m": 300,
        "total_duration_min": 7,
        "steps": [
            {
                "instruction": "Walk to the central platform waiting zone.",
                "distance_m": 90,
                "duration_min": 2,
                "landmark": "Central waiting zone"
            },
            {
                "instruction": "Listen for the gate change announcement in the noisy hall.",
                "distance_m": 80,
                "duration_min": 2,
                "audio_only_cue": True,
                "landmark": "Announcement speaker"
            },
            {
                "instruction": "Continue to the boarding gate beside the display board.",
                "distance_m": 130,
                "duration_min": 3,
                "landmark": "Display board"
            }
        ]
    },
    "indoor_university_long_corridor": {
        "route_id": "indoor_university_long_corridor",
        "name": "University Building Long Corridor",
        "step_free": True,
        "total_distance_m": 980,
        "total_duration_min": 16,
        "steps": [
            {
                "instruction": "Enter the main lobby and go to the information screen.",
                "distance_m": 120,
                "duration_min": 2,
                "landmark": "Main lobby"
            },
            {
                "instruction": "Continue 620m along the long east corridor.",
                "distance_m": 620,
                "duration_min": 10,
                "landmark": "East corridor"
            },
            {
                "instruction": "Turn right at the seminar room cluster.",
                "distance_m": 240,
                "duration_min": 4,
                "landmark": "Seminar rooms"
            }
        ]
    },
    "indoor_hospital_complex_instructions": {
        "route_id": "indoor_hospital_complex_instructions",
        "name": "Hospital Reception to Clinic Desk",
        "step_free": True,
        "total_distance_m": 540,
        "total_duration_min": 11,
        "steps": [
            {
                "instruction": "Proceed from reception through the atrium, then continue past the pharmacy and outpatient waiting area.",
                "distance_m": 180,
                "duration_min": 4,
                "landmark": "Reception"
            },
            {
                "instruction": "After the second glass door, turn left, pass two corridor junctions, and continue toward Clinic C.",
                "distance_m": 220,
                "duration_min": 5,
                "landmark": "Clinic C corridor"
            },
            {
                "instruction": "Check in at the clinic desk beside the blue seating area.",
                "distance_m": 140,
                "duration_min": 2,
                "landmark": "Clinic desk"
            }
        ]
    }
}


# ── Step-level WGS-84 coordinates (lat, lon) for spatial barrier analysis ─────
# Routes without entries here fall back to route-midpoint scoring.
ROUTE_STEP_COORDS: dict[str, list[tuple[float, float]]] = {
    "zurich_hb_to_rathaus": [
        (47.3782, 8.5403),   # Step 1 — HB Haupthalle / Bahnhofplatz
        (47.3772, 8.5399),   # Step 2 — Tram Stop Bahnhofquai (stairs here)
        (47.3765, 8.5430),   # Step 3 — Tram ride midpoint / Central stop
        (47.3706, 8.5435),   # Step 4 — Rathaus / Limmatquai 55
    ],
    "zurich_hb_to_rathaus_sf": [
        (47.3778, 8.5402),   # Step 1 — HB underground → Bahnhofquai lift
        (47.3775, 8.5401),   # Step 2 — Bahnhofquai street level (exit lift)
        (47.3745, 8.5418),   # Step 3 — Limmatquai flat path (midpoint)
        (47.3706, 8.5435),   # Step 4 — Rathaus accessible entrance
    ],
}

# ── Preferred step-free alternative per route ─────────────────────────────────
# Overrides the generic "first step-free fixture" fallback.
STEP_FREE_ALTERNATIVES: dict[str, str] = {
    "route_with_stairs":        "step_free_route",
    "zurich_hb_to_rathaus":     "zurich_hb_to_rathaus_sf",
    "indoor_station_transfer_stairs": "indoor_station_transfer_elevator",
}


class RouteProvider(ABC):
    @abstractmethod
    def get_route(self, route_id: str) -> RawRoute:
        raise NotImplementedError

    @abstractmethod
    def list_routes(self) -> list[RawRoute]:
        raise NotImplementedError

    @abstractmethod
    def find_step_free_alternative(self, route_id: str) -> RawRoute | None:
        raise NotImplementedError


class MockRouteProvider(RouteProvider):
    def __init__(self, fixtures: dict[str, dict] | None = None) -> None:
        self.fixtures = fixtures or ROUTE_FIXTURES

    def get_route(self, route_id: str) -> RawRoute:
        if route_id not in self.fixtures:
            raise KeyError(f"Unknown route_id: {route_id}")
        return RawRoute.model_validate(self.fixtures[route_id])

    def list_routes(self) -> list[RawRoute]:
        return [RawRoute.model_validate(route) for route in self.fixtures.values()]

    def find_step_free_alternative(self, route_id: str) -> RawRoute | None:
        route = self.get_route(route_id)
        if route.step_free:
            return route  # already step-free — return as-is

        # 1. Check the explicit semantic-pair mapping first
        preferred_id = STEP_FREE_ALTERNATIVES.get(route_id)
        if preferred_id and preferred_id in self.fixtures:
            candidate = self.get_route(preferred_id)
            if candidate.step_free:
                return candidate

        # 2. Fallback: first step-free fixture in the collection
        for candidate in self.list_routes():
            if candidate.step_free:
                return candidate
        return None
