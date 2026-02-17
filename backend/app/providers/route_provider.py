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
    }
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
            return route
        for candidate in self.list_routes():
            if candidate.step_free:
                return candidate
        return None
