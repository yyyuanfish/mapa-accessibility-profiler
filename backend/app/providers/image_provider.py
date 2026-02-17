from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod

import requests
from requests import RequestException

from backend.app.models import ImageHazardsSummary, RiskLevel
from backend.app.utils.json_extract import JSONExtractionError, extract_first_json


class ImageProvider(ABC):
    @abstractmethod
    def summarize_hazards(self, image_bytes: bytes) -> ImageHazardsSummary:
        raise NotImplementedError


class OllamaImageProvider(ImageProvider):
    def __init__(
        self,
        model: str = "llava:7b",
        base_url: str = "http://localhost:11434",
        timeout_sec: int = 180,
    ) -> None:
        self.model = model
        normalized = base_url.strip()
        if "://" not in normalized:
            normalized = f"http://{normalized}"
        self.base_url = normalized.rstrip("/")
        self.timeout_sec = timeout_sec
        self._session = requests.Session()
        self._session.trust_env = False

    def is_available(self) -> bool:
        try:
            response = self._session.get(
                f"{self.base_url}/api/tags",
                timeout=(10, self.timeout_sec),
            )
            response.raise_for_status()
            return True
        except RequestException:
            return False

    def summarize_hazards(self, image_bytes: bytes) -> ImageHazardsSummary:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = (
            "You are an accessibility hazard detector. "
            "Return ONLY JSON with this schema: "
            '{"stairs":"none|low|medium|high","slope":"none|low|medium|high","crowd":"none|low|medium|high","notes":["..."]}. '
            "Be conservative and avoid hallucination."
        )
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "user", "content": prompt, "images": [image_b64]},
            ],
            "options": {"temperature": 0},
        }

        try:
            response = self._session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=(10, self.timeout_sec),
            )
            if response.status_code >= 400:
                body = response.text.strip().replace("\n", " ")
                raise RuntimeError(
                    f"Ollama /api/chat returned HTTP {response.status_code}. "
                    f"Body: {body[:300]}"
                )

            data = response.json()
            content = str(data.get("message", {}).get("content", "")).strip()
            if not content:
                raise RuntimeError("Ollama returned empty message content for image analysis.")

            try:
                parsed = extract_first_json(content)
                return self._normalize_hazards(parsed)
            except (JSONExtractionError, ValueError):
                return self._fallback_from_text(content)
        except (RequestException, RuntimeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Ollama image analysis failed for model '{self.model}'. "
                f"Detail: {exc}"
            ) from exc

    def _normalize_hazards(self, payload: object) -> ImageHazardsSummary:
        if not isinstance(payload, dict):
            raise ValueError("Hazard payload is not a JSON object.")

        def level_of(key: str) -> RiskLevel:
            raw = str(payload.get(key, "low")).strip().lower()
            if raw in {"none", "low", "medium", "high"}:
                return RiskLevel(raw)
            return RiskLevel.LOW

        notes_raw = payload.get("notes", [])
        notes = [str(note) for note in notes_raw] if isinstance(notes_raw, list) else []
        return ImageHazardsSummary(
            stairs=level_of("stairs"),
            slope=level_of("slope"),
            crowd=level_of("crowd"),
            notes=notes,
        )

    def _fallback_from_text(self, content: str) -> ImageHazardsSummary:
        lowered = content.lower()

        def stairs_level() -> RiskLevel:
            if any(term in lowered for term in {"many stairs", "long staircase", "steep stairs"}):
                return RiskLevel.HIGH
            if any(term in lowered for term in {"stairs", "stair", "steps", "staircase"}):
                return RiskLevel.MEDIUM
            return RiskLevel.LOW

        def slope_level() -> RiskLevel:
            if any(term in lowered for term in {"steep slope", "steep incline", "steep hill"}):
                return RiskLevel.HIGH
            if any(term in lowered for term in {"slope", "incline", "hill", "ramp"}):
                return RiskLevel.MEDIUM
            return RiskLevel.LOW

        def crowd_level() -> RiskLevel:
            if any(term in lowered for term in {"very crowded", "heavy crowd", "dense crowd", "packed"}):
                return RiskLevel.HIGH
            if any(term in lowered for term in {"crowd", "crowded", "busy", "queue", "many people"}):
                return RiskLevel.MEDIUM
            return RiskLevel.LOW

        short_note = " ".join(content.split())[:180]
        notes = [
            "Parsed from non-JSON vision output.",
            short_note or "No additional notes.",
        ]
        return ImageHazardsSummary(
            stairs=stairs_level(),
            slope=slope_level(),
            crowd=crowd_level(),
            notes=notes,
        )


class MockImageProvider(ImageProvider):
    """Consent-gated stub: deterministic hazards derived from input length."""

    def summarize_hazards(self, image_bytes: bytes) -> ImageHazardsSummary:
        length = len(image_bytes)
        stairs = RiskLevel.HIGH if length % 3 == 0 else RiskLevel.LOW
        slope = RiskLevel.MEDIUM if length % 5 == 0 else RiskLevel.LOW
        crowd = RiskLevel.MEDIUM if length % 2 == 0 else RiskLevel.LOW
        notes = [
            "Mock image analysis only.",
            "Use route metadata as the primary accessibility signal.",
        ]
        return ImageHazardsSummary(stairs=stairs, slope=slope, crowd=crowd, notes=notes)
