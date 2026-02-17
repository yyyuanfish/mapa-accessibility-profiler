from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests
from requests import RequestException


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError


class OllamaLLMProvider(LLMProvider):
    def __init__(
        self,
        model: str = "llama3.1:8b",
        base_url: str = "http://localhost:11434",
        timeout_sec: int = 300,
    ) -> None:
        self.model = model
        normalized = base_url.strip()
        if "://" not in normalized:
            normalized = f"http://{normalized}"
        self.base_url = normalized.rstrip("/")
        self.timeout_sec = timeout_sec
        self._session = requests.Session()
        # Avoid environment proxy settings breaking localhost calls.
        self._session.trust_env = False

    def is_available(self) -> bool:
        ok, _, _, _ = self.health_check()
        return ok

    def health_check(self) -> tuple[bool, str, str, list[str]]:
        errors: list[str] = []
        for candidate in self._candidate_base_urls():
            try:
                response = self._session.get(
                    f"{candidate}/api/tags",
                    timeout=(10, self.timeout_sec),
                )
                response.raise_for_status()
                payload = response.json()
                models_raw = payload.get("models", [])
                models = [
                    str(item.get("name", ""))
                    for item in models_raw
                    if isinstance(item, dict) and item.get("name")
                ]
                return (
                    True,
                    f"Ollama reachable at {candidate}",
                    candidate,
                    models,
                )
            except RequestException as exc:
                errors.append(f"{candidate} -> {exc.__class__.__name__}")
            except ValueError as exc:
                errors.append(f"{candidate} -> invalid JSON response: {exc}")
        msg = (
            "Ollama server not reachable. Tried: "
            + ", ".join(errors)
            + ". Please run `ollama serve` and verify URL."
        )
        return False, msg, self.base_url, []

    def _candidate_base_urls(self) -> list[str]:
        candidates = [self.base_url]
        parsed = urlparse(self.base_url)
        host = parsed.hostname or ""
        if host == "localhost":
            replaced = parsed._replace(netloc=parsed.netloc.replace("localhost", "127.0.0.1"))
            candidates.append(urlunparse(replaced).rstrip("/"))
        elif host == "127.0.0.1":
            replaced = parsed._replace(netloc=parsed.netloc.replace("127.0.0.1", "localhost"))
            candidates.append(urlunparse(replaced).rstrip("/"))
        deduped: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            if item and item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": 0,
            },
        }
        last_exc: RequestException | None = None
        for candidate in self._candidate_base_urls():
            try:
                response = self._session.post(
                    f"{candidate}/api/chat",
                    json=payload,
                    timeout=(10, self.timeout_sec),
                )
                response.raise_for_status()
                data = response.json()
                content = str(data.get("message", {}).get("content", "")).strip()
                if candidate != self.base_url:
                    self.base_url = candidate
                return content
            except RequestException as exc:
                last_exc = exc

        ok, status_msg, resolved_url, available_models = self.health_check()
        missing_model_hint = ""
        if ok and available_models and self.model not in available_models:
            missing_model_hint = f" Model '{self.model}' not found on server; run `ollama pull {self.model}`."

        detail = last_exc.__class__.__name__ if last_exc else "UnknownError"
        raise RuntimeError(
            f"Ollama request failed (model='{self.model}', base_url='{resolved_url}'). "
            f"Last error: {detail}. Health: {status_msg}.{missing_model_hint}"
        ) from last_exc


class MockLLMProvider(LLMProvider):
    """Deterministic offline mock with optional forced first-response parse failure."""

    def __init__(self, invalid_first_for_tasks: set[str] | None = None) -> None:
        self.invalid_first_for_tasks = invalid_first_for_tasks or set()
        self._task_calls: dict[str, int] = {}

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        task = self._detect_task(system_prompt)
        call_number = self._task_calls.get(task, 0) + 1
        self._task_calls[task] = call_number

        if task in self.invalid_first_for_tasks and call_number == 1:
            return "This is not JSON. Please try again."

        if task == "profiler":
            return self._complete_profiler(user_prompt)
        if task == "planner":
            return self._complete_planner(user_prompt)
        return "{}"

    @staticmethod
    def _detect_task(system_prompt: str) -> str:
        if "TASK=PROFILER" in system_prompt:
            return "profiler"
        if "TASK=PLANNER" in system_prompt:
            return "planner"
        return "unknown"

    def _complete_profiler(self, user_prompt: str) -> str:
        payload = self._safe_json_load(user_prompt)
        user_message = str(payload.get("user_message", "")).lower()

        if "skip" in user_message:
            return json.dumps({"profile_patch": {}})

        needs: dict[str, Any] = {}
        communication: dict[str, Any] = {}

        vision_val = self._detect_bool(
            user_message,
            positives=["blind", "low vision", "low-vision", "screen reader", "cannot see", "can't see"],
            negatives=["no vision support", "no vision needs", "not blind"],
        )
        if vision_val is not None:
            needs.setdefault("vision", {})["blind_or_low_vision"] = vision_val
            if vision_val:
                needs.setdefault("vision", {})["prefers_landmarks"] = True

        hearing_val = self._detect_bool(
            user_message,
            positives=["deaf", "hard of hearing", "hoh", "cannot hear", "can't hear"],
            negatives=["not deaf", "no hearing needs", "hearing is fine"],
        )
        if hearing_val is not None:
            needs.setdefault("hearing", {})["deaf_or_hard_of_hearing"] = hearing_val

        sign_val = self._detect_bool(
            user_message,
            positives=["sign language", "asl", "signed", "sign user"],
            negatives=["no sign language", "do not sign"],
        )
        if sign_val is not None:
            needs.setdefault("hearing", {})["sign_language_user"] = sign_val
            if sign_val:
                communication["output_mode"] = "sign_gloss_text"

        wheelchair_val = self._detect_bool(
            user_message,
            positives=["wheelchair", "walker", "cannot climb stairs", "can't climb stairs", "mobility support"],
            negatives=[
                "no mobility support",
                "not a wheelchair user",
                "no wheelchair",
                "no wheelchair needs",
                "without wheelchair support",
            ],
        )
        if wheelchair_val is not None:
            needs.setdefault("mobility", {})["wheelchair_user"] = wheelchair_val
            if wheelchair_val:
                needs.setdefault("mobility", {})["needs_step_free_route"] = True
                needs.setdefault("mobility", {})["avoid_long_walks"] = True

        step_free_val = self._detect_bool(
            user_message,
            positives=["step free", "step-free", "avoid stairs", "no stairs"],
            negatives=["stairs are fine", "steps are okay"],
        )
        if step_free_val is not None:
            needs.setdefault("mobility", {})["needs_step_free_route"] = step_free_val

        simple_val = self._detect_bool(
            user_message,
            positives=[
                "simple english",
                "easy words",
                "short sentences",
                "child",
                "kid",
                "reading difficulty",
                "memory difficulty",
                "i forget",
                "hard to read",
            ],
            negatives=["no simple language", "standard language is fine"],
        )
        if simple_val is not None:
            needs.setdefault("cognitive", {})["needs_simple_language"] = simple_val
            if simple_val:
                needs.setdefault("cognitive", {})["reading_or_memory_difficulty_or_child"] = True
                communication.setdefault("output_mode", "simple_text")

        memory_val = self._detect_bool(
            user_message,
            positives=["memory", "reminders", "forget"],
            negatives=["no memory issues", "memory is fine"],
        )
        if memory_val is not None:
            needs.setdefault("cognitive", {})["needs_memory_support"] = memory_val
            if memory_val:
                needs.setdefault("cognitive", {})["reading_or_memory_difficulty_or_child"] = True
                communication.setdefault("output_mode", "simple_text")

        patch: dict[str, Any] = {}
        if needs:
            patch["needs"] = needs
        if communication:
            patch["communication"] = communication
        return json.dumps({"profile_patch": patch})

    def _complete_planner(self, user_prompt: str) -> str:
        payload = self._safe_json_load(user_prompt)
        draft = payload.get("draft_plan", {})
        output_mode = payload.get("output_mode", "standard_text")

        if output_mode == "sign_gloss_text":
            return json.dumps(self._to_sign_gloss_plan(draft))
        if output_mode == "simple_text":
            return json.dumps(self._to_simple_text_plan(draft))
        return json.dumps(draft)

    @staticmethod
    def _safe_json_load(raw: str) -> dict[str, Any]:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            pass
        return {}

    @staticmethod
    def _detect_bool(text: str, positives: list[str], negatives: list[str]) -> bool | None:
        for neg in negatives:
            if neg in text:
                return False
        for pos in positives:
            if pos in text:
                return True
        return None

    def _to_sign_gloss_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        transformed = dict(plan)
        for key in ["summary"]:
            value = transformed.get(key)
            if isinstance(value, str):
                transformed[key] = self._gloss(value)
        for key in ["directions", "alerts", "checklist", "if_you_get_lost"]:
            value = transformed.get(key)
            if isinstance(value, list):
                transformed[key] = [self._gloss(str(item)) for item in value]
        return transformed

    def _to_simple_text_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        transformed = dict(plan)
        for key in ["summary"]:
            value = transformed.get(key)
            if isinstance(value, str):
                transformed[key] = self._simplify(value)
        for key in ["directions", "alerts", "checklist", "if_you_get_lost"]:
            value = transformed.get(key)
            if isinstance(value, list):
                transformed[key] = [self._simplify(str(item)) for item in value]
        return transformed

    @staticmethod
    def _gloss(text: str) -> str:
        text = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text.upper()

    @staticmethod
    def _simplify(text: str) -> str:
        text = re.sub(r"\bapproximately\b", "about", text, flags=re.IGNORECASE)
        text = re.sub(r"\bproceed\b", "go", text, flags=re.IGNORECASE)
        text = re.sub(r"\butilize\b", "use", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()
        if not text.endswith("."):
            text += "."
        return text
