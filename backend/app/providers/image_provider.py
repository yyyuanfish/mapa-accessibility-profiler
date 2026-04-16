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
            "You are an accessibility vision feedback agent. "
            "Return ONLY JSON with this schema: "
            '{"stairs":"none|low|medium|high","slope":"none|low|medium|high","crowd":"none|low|medium|high",'
            '"scene_summary":"...",'
            '"visible_objects":["..."],'
            '"accessibility_cues":["..."],'
            '"reasoning_steps":["..."],'
            '"evidence":["..."],'
            '"notes":["..."]}. '
            "Use conservative, grounded visual descriptions only. "
            "Do not claim that a place is accessible unless the image directly supports a narrow visual cue."
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

        scene_summary_raw = payload.get("scene_summary")
        scene_summary = str(scene_summary_raw).strip() if scene_summary_raw not in {None, ""} else None

        visible_objects_raw = payload.get("visible_objects", [])
        visible_objects = self._normalize_string_list(visible_objects_raw)

        accessibility_cues_raw = payload.get("accessibility_cues", [])
        accessibility_cues = self._normalize_string_list(accessibility_cues_raw)

        reasoning_steps_raw = payload.get("reasoning_steps", [])
        reasoning_steps = self._normalize_string_list(reasoning_steps_raw)

        evidence_raw = payload.get("evidence", [])
        evidence = self._normalize_string_list(evidence_raw)

        notes_raw = payload.get("notes", [])
        notes = self._normalize_string_list(notes_raw)
        return ImageHazardsSummary(
            stairs=level_of("stairs"),
            slope=level_of("slope"),
            crowd=level_of("crowd"),
            scene_summary=scene_summary,
            visible_objects=visible_objects,
            accessibility_cues=accessibility_cues,
            reasoning_steps=reasoning_steps,
            evidence=evidence,
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
        visible_objects = self._terms_present(
            lowered,
            [
                "stairs",
                "staircase",
                "ramp",
                "handrail",
                "elevator",
                "queue barrier",
                "sidewalk",
                "doorway",
                "sign",
                "platform",
            ],
        )
        accessibility_cues = self._terms_present(
            lowered,
            [
                "stairs visible",
                "ramp-like path",
                "handrail visible",
                "elevator sign visible",
                "narrow passage",
                "crowded walkway",
            ],
        )
        if not accessibility_cues:
            if any(term in lowered for term in {"stairs", "stair", "steps", "staircase"}):
                accessibility_cues.append("stairs visible")
            if any(term in lowered for term in {"slope", "incline", "hill", "ramp"}):
                accessibility_cues.append("sloped or ramp-like surface visible")
            if any(term in lowered for term in {"crowd", "crowded", "busy", "queue", "many people"}):
                accessibility_cues.append("crowd near the visible path")
        evidence = []
        if visible_objects:
            evidence.append("visible objects: " + ", ".join(visible_objects[:4]))
        if accessibility_cues:
            evidence.append("accessibility cues: " + ", ".join(accessibility_cues[:4]))
        reasoning_steps = [
            "Captured a visual scene description from the image.",
            "Extracted symbolic objects and accessibility-related cues.",
            f"Mapped cues to hazard levels: stairs={stairs_level().value}, slope={slope_level().value}, crowd={crowd_level().value}.",
        ]
        notes = [
            "Parsed from non-JSON vision output.",
            short_note or "No additional notes.",
        ]
        return ImageHazardsSummary(
            stairs=stairs_level(),
            slope=slope_level(),
            crowd=crowd_level(),
            scene_summary=short_note or None,
            visible_objects=visible_objects,
            accessibility_cues=accessibility_cues,
            reasoning_steps=reasoning_steps,
            evidence=evidence,
            notes=notes,
        )

    @staticmethod
    def _normalize_string_list(raw: object) -> list[str]:
        if not isinstance(raw, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in raw:
            value = str(item).strip()
            key = value.lower()
            if not value or key in seen:
                continue
            seen.add(key)
            normalized.append(value)
        return normalized[:6]

    @staticmethod
    def _terms_present(content: str, terms: list[str]) -> list[str]:
        results: list[str] = []
        for term in terms:
            if term in content:
                results.append(term)
        return results


class MockImageProvider(ImageProvider):
    """Consent-gated stub: deterministic hazards derived from input length."""

    def summarize_hazards(self, image_bytes: bytes) -> ImageHazardsSummary:
        length = len(image_bytes)
        stairs = RiskLevel.HIGH if length % 3 == 0 else RiskLevel.LOW
        slope = RiskLevel.MEDIUM if length % 5 == 0 else RiskLevel.LOW
        crowd = RiskLevel.MEDIUM if length % 2 == 0 else RiskLevel.LOW
        visible_objects: list[str] = []
        accessibility_cues: list[str] = []
        if stairs in {RiskLevel.MEDIUM, RiskLevel.HIGH}:
            visible_objects.append("stairs")
            accessibility_cues.append("stairs visible")
        if slope in {RiskLevel.MEDIUM, RiskLevel.HIGH}:
            visible_objects.append("ramp")
            accessibility_cues.append("sloped path visible")
        if crowd in {RiskLevel.MEDIUM, RiskLevel.HIGH}:
            visible_objects.append("queue")
            accessibility_cues.append("crowd near the walkway")
        evidence = []
        if visible_objects:
            evidence.append("visible objects: " + ", ".join(visible_objects[:4]))
        if accessibility_cues:
            evidence.append("accessibility cues: " + ", ".join(accessibility_cues[:4]))
        notes = [
            "Mock image analysis only.",
            "Use route metadata as the primary accessibility signal.",
        ]
        scene_summary = "Mock symbolic vision feedback generated from uploaded image bytes."
        reasoning_steps = [
            "Accepted the captured image and converted it to symbolic vision feedback.",
            "Estimated conservative hazard levels from deterministic mock rules.",
            f"Prepared plan-ready hazard summary: stairs={stairs.value}, slope={slope.value}, crowd={crowd.value}.",
        ]
        return ImageHazardsSummary(
            stairs=stairs,
            slope=slope,
            crowd=crowd,
            scene_summary=scene_summary,
            visible_objects=visible_objects,
            accessibility_cues=accessibility_cues,
            reasoning_steps=reasoning_steps,
            evidence=evidence,
            notes=notes,
        )
