from __future__ import annotations

import json
import re
from typing import Any

from backend.app.models import (
    AccessibilityProfile,
    ConfidenceScores,
    DomainConfidence,
    OutputMode,
    ProfilePatch,
    ProfilerAgentOutput,
    ProfilerLLMResponse,
)
from backend.app.providers.llm_provider import LLMProvider
from backend.app.utils.json_extract import JSONExtractionError, extract_first_json


class ProfilerAgent:
    SYSTEM_PROMPT = (
        "TASK=PROFILER\n"
        "Infer functional accessibility needs only. "
        "Never diagnose conditions. Return JSON with profile_patch."
    )
    _SUPPORTED_LANGS = {"en", "zh", "de"}
    _QUESTION_TEXTS = {
        "en": {
            "vision": "Do you have any vision-related access needs, such as blind or low-vision support? (yes/no/skip)",
            "hearing": "Do you have hearing-related needs, including Deaf/HoH support? (yes/no/skip)",
            "hearing_sign": "Do you want sign-language style text output? (yes/no/skip)",
            "mobility": "Do you use a wheelchair or need step-free routes without stairs? (yes/no/skip)",
            "cognitive": "Would Simple English, shorter steps, or memory reminders help you? (yes/no/skip)",
        },
        "zh": {
            "vision": "你是否有视觉相关的出行需求（如盲人/低视力支持）？（有/没有/是/否/跳过）",
            "hearing": "你是否有听力相关需求（如听障支持）？（有/没有/是/否/跳过）",
            "hearing_sign": "你是否希望使用手语风格文本输出？（有/没有/是/否/跳过）",
            "mobility": "你是否使用轮椅，或需要无台阶路线？（有/没有/是/否/跳过）",
            "cognitive": "你是否需要简明语言、更短步骤或记忆提醒？（有/没有/是/否/跳过）",
        },
        "de": {
            "vision": "Haben Sie visuelle Zugangsbedarfe, z. B. Unterstützung bei Blindheit/Sehbehinderung? (ja/nein/überspringen)",
            "hearing": "Haben Sie hörbezogene Bedarfe, einschließlich Unterstützung für Gehörlos/Schwerhörig? (ja/nein/überspringen)",
            "hearing_sign": "Möchten Sie eine gebärdensprachnahe Textausgabe? (ja/nein/überspringen)",
            "mobility": "Nutzen Sie einen Rollstuhl oder benötigen Sie stufenfreie Routen ohne Treppen? (ja/nein/überspringen)",
            "cognitive": "Würden Einfaches Deutsch, kurze Schritte oder Erinnerungshilfen helfen? (ja/nein/überspringen)",
        },
    }

    def __init__(self, llm_provider: LLMProvider) -> None:
        self.llm_provider = llm_provider

    def process_turn(
        self,
        user_message: str,
        current_patch: dict[str, Any] | None = None,
        skipped_domains: list[str] | None = None,
        question_context: str | None = None,
        response_language: str = "en",
    ) -> ProfilerAgentOutput:
        language = self._normalize_language(response_language)
        skipped = set(skipped_domains or [])
        current = ProfilePatch.model_validate(current_patch or {})

        llm_patch_dict = self._request_patch(
            user_message=user_message,
            current_patch=current,
            question_context=question_context,
        )
        context_patch_dict = self._contextual_patch(
            user_message=user_message,
            question_context=question_context,
        )
        merged_dict = self._deep_merge_dicts(current.model_dump(), llm_patch_dict)
        merged_dict = self._deep_merge_dicts(merged_dict, context_patch_dict)
        merged_dict = self._enforce_output_mode_rules(merged_dict)
        merged_patch = ProfilePatch.model_validate(merged_dict)

        confidence = self._compute_confidence(merged_patch, skipped)
        missing = self._missing_critical_fields(merged_patch, skipped)
        next_question, next_question_context = self._next_question(merged_patch, skipped, language)
        confirmation_text = self._confirmation_text(merged_patch, language)

        return ProfilerAgentOutput(
            profile_patch=merged_patch,
            confidence=confidence,
            missing_critical_fields=missing,
            next_question=next_question,
            next_question_context=next_question_context,
            confirmation_text=confirmation_text,
        )

    def build_profile(
        self,
        profile_patch: dict[str, Any] | ProfilePatch,
        consent_to_profile: bool = True,
        skipped_domains: list[str] | None = None,
    ) -> AccessibilityProfile:
        patch = profile_patch if isinstance(profile_patch, ProfilePatch) else ProfilePatch.model_validate(profile_patch)
        confidence = self._compute_confidence(patch, set(skipped_domains or []))
        return AccessibilityProfile(
            consent_to_profile=consent_to_profile,
            needs=patch.needs,
            communication=patch.communication,
            preferences=patch.preferences,
            confidence=confidence,
        )

    def _request_patch(
        self,
        user_message: str,
        current_patch: ProfilePatch,
        question_context: str | None,
    ) -> dict[str, Any]:
        payload = {
            "user_message": user_message,
            "current_patch": current_patch.model_dump(exclude_none=True),
            "question_context": question_context,
        }

        user_prompt = json.dumps(payload)
        raw = self.llm_provider.complete(self.SYSTEM_PROMPT, user_prompt)

        try:
            parsed = extract_first_json(raw)
            validated = ProfilerLLMResponse.model_validate(parsed)
            return validated.profile_patch.model_dump(exclude_defaults=True, exclude_none=True)
        except (JSONExtractionError, ValueError):
            retry_system_prompt = self.SYSTEM_PROMPT + "\nReturn ONLY JSON."
            raw_retry = self.llm_provider.complete(retry_system_prompt, user_prompt)
            parsed_retry = extract_first_json(raw_retry)
            validated_retry = ProfilerLLMResponse.model_validate(parsed_retry)
            return validated_retry.profile_patch.model_dump(exclude_defaults=True, exclude_none=True)

    def _missing_critical_fields(self, patch: ProfilePatch, skipped_domains: set[str]) -> list[str]:
        missing: list[str] = []

        if "vision" not in skipped_domains and patch.needs.vision.blind_or_low_vision is None:
            missing.append("needs.vision.blind_or_low_vision")

        if "hearing" not in skipped_domains and patch.needs.hearing.deaf_or_hard_of_hearing is None:
            missing.append("needs.hearing.deaf_or_hard_of_hearing")
        if (
            "hearing" not in skipped_domains
            and patch.needs.hearing.deaf_or_hard_of_hearing is True
            and patch.needs.hearing.sign_language_user is None
        ):
            missing.append("needs.hearing.sign_language_user")

        if "mobility" not in skipped_domains and patch.needs.mobility.wheelchair_user is None:
            missing.append("needs.mobility.wheelchair_user")

        if "mobility" not in skipped_domains and patch.needs.mobility.needs_step_free_route is None:
            missing.append("needs.mobility.needs_step_free_route")

        if "cognitive" not in skipped_domains and patch.needs.cognitive.needs_simple_language is None:
            missing.append("needs.cognitive.needs_simple_language")

        if "cognitive" not in skipped_domains and patch.needs.cognitive.needs_memory_support is None:
            missing.append("needs.cognitive.needs_memory_support")

        return missing

    @staticmethod
    def _domain_known(values: list[bool | None]) -> int:
        return sum(1 for value in values if value is not None)

    def _compute_confidence(self, patch: ProfilePatch, skipped_domains: set[str]) -> ConfidenceScores:
        vision_total = 1
        hearing_total = 2
        mobility_total = 2
        cognitive_total = 3

        vision_known = self._domain_known([patch.needs.vision.blind_or_low_vision])
        hearing_known = self._domain_known(
            [patch.needs.hearing.deaf_or_hard_of_hearing, patch.needs.hearing.sign_language_user]
        )
        mobility_known = self._domain_known(
            [patch.needs.mobility.wheelchair_user, patch.needs.mobility.needs_step_free_route]
        )
        cognitive_known = self._domain_known(
            [
                patch.needs.cognitive.needs_simple_language,
                patch.needs.cognitive.needs_memory_support,
                patch.needs.cognitive.reading_or_memory_difficulty_or_child,
            ]
        )

        def score(known: int, total: int, domain: str) -> float:
            if domain in skipped_domains and known == 0:
                return 0.3
            return round(known / total, 2)

        per_domain = DomainConfidence(
            vision=score(vision_known, vision_total, "vision"),
            hearing=score(hearing_known, hearing_total, "hearing"),
            mobility=score(mobility_known, mobility_total, "mobility"),
            cognitive=score(cognitive_known, cognitive_total, "cognitive"),
        )
        overall = round(
            (per_domain.vision + per_domain.hearing + per_domain.mobility + per_domain.cognitive) / 4,
            2,
        )
        return ConfidenceScores(overall=overall, per_domain=per_domain)

    def _next_question(
        self,
        patch: ProfilePatch,
        skipped_domains: set[str],
        language: str,
    ) -> tuple[str | None, str | None]:
        if "vision" not in skipped_domains and patch.needs.vision.blind_or_low_vision is None:
            return self._question("vision", language), "vision"

        if "hearing" not in skipped_domains and patch.needs.hearing.deaf_or_hard_of_hearing is None:
            return self._question("hearing", language), "hearing"

        if (
            "hearing" not in skipped_domains
            and patch.needs.hearing.deaf_or_hard_of_hearing is True
            and patch.needs.hearing.sign_language_user is None
        ):
            return self._question("hearing_sign", language), "hearing_sign"

        if "mobility" not in skipped_domains and (
            patch.needs.mobility.wheelchair_user is None or patch.needs.mobility.needs_step_free_route is None
        ):
            return self._question("mobility", language), "mobility"

        if "cognitive" not in skipped_domains and (
            patch.needs.cognitive.needs_simple_language is None
            or patch.needs.cognitive.needs_memory_support is None
        ):
            return self._question("cognitive", language), "cognitive"

        return None, None

    def _confirmation_text(self, patch: ProfilePatch, language: str) -> str:
        if language == "zh":
            prefix = "我的理解是："
            suffix = "这样对吗？"
            vision = self._bool_statement(
                patch.needs.vision.blind_or_low_vision,
                yes_text="你需要盲人/低视力支持。",
                no_text="你不需要盲人/低视力支持。",
                unknown_text="视觉支持未说明或已跳过。",
            )
            hearing = self._bool_statement(
                patch.needs.hearing.deaf_or_hard_of_hearing,
                yes_text="你需要听障沟通支持。",
                no_text="你不需要听障沟通支持。",
                unknown_text="听力支持未说明或已跳过。",
            )
            sign = self._bool_statement(
                patch.needs.hearing.sign_language_user,
                yes_text="你希望使用手语风格文本输出。",
                no_text="你不需要手语风格输出。",
                unknown_text="手语偏好未说明或已跳过。",
            )
            mobility = self._bool_statement(
                patch.needs.mobility.needs_step_free_route,
                yes_text="你需要无台阶路线。",
                no_text="你不需要无台阶路线。",
                unknown_text="行动路线偏好未说明或已跳过。",
            )
            cognitive = self._bool_statement(
                patch.needs.cognitive.needs_simple_language,
                yes_text="你需要简明语言输出。",
                no_text="标准语言输出可以接受。",
                unknown_text="语言简化偏好未说明或已跳过。",
            )
            return f"{prefix}{vision} {hearing} {sign} {mobility} {cognitive} {suffix}"

        if language == "de":
            prefix = "Ich habe Folgendes verstanden: "
            suffix = "Ist das korrekt?"
            vision = self._bool_statement(
                patch.needs.vision.blind_or_low_vision,
                yes_text="Sie benötigen Unterstützung für blind/Sehbehinderung.",
                no_text="Sie benötigen keine Unterstützung für blind/Sehbehinderung.",
                unknown_text="Seh-Unterstützung wurde übersprungen oder nicht angegeben.",
            )
            hearing = self._bool_statement(
                patch.needs.hearing.deaf_or_hard_of_hearing,
                yes_text="Sie benötigen Unterstützung für Gehörlos/Schwerhörig.",
                no_text="Sie benötigen keine Hör-Unterstützung.",
                unknown_text="Hör-Unterstützung wurde übersprungen oder nicht angegeben.",
            )
            sign = self._bool_statement(
                patch.needs.hearing.sign_language_user,
                yes_text="Sie möchten gebärdensprachnahe Textausgabe.",
                no_text="Sie benötigen keine gebärdensprachnahe Ausgabe.",
                unknown_text="Gebärdensprach-Präferenz wurde übersprungen oder nicht angegeben.",
            )
            mobility = self._bool_statement(
                patch.needs.mobility.needs_step_free_route,
                yes_text="Sie benötigen stufenfreie Routen.",
                no_text="Stufenfreie Routen sind nicht erforderlich.",
                unknown_text="Mobilitätspräferenz wurde übersprungen oder nicht angegeben.",
            )
            cognitive = self._bool_statement(
                patch.needs.cognitive.needs_simple_language,
                yes_text="Sie möchten einfache Sprache.",
                no_text="Standardsprache ist in Ordnung.",
                unknown_text="Sprachvereinfachung wurde übersprungen oder nicht angegeben.",
            )
            return f"{prefix}{vision} {hearing} {sign} {mobility} {cognitive} {suffix}"

        statements = [
            self._bool_statement(
                patch.needs.vision.blind_or_low_vision,
                yes_text="You prefer blind/low-vision support.",
                no_text="No blind/low-vision support was requested.",
                unknown_text="Vision support was skipped or not specified.",
            ),
            self._bool_statement(
                patch.needs.hearing.deaf_or_hard_of_hearing,
                yes_text="You requested Deaf/HoH communication support.",
                no_text="No Deaf/HoH support was requested.",
                unknown_text="Hearing support was skipped or not specified.",
            ),
            self._bool_statement(
                patch.needs.hearing.sign_language_user,
                yes_text="You requested sign-language style text output.",
                no_text="No sign-language style output was requested.",
                unknown_text="Sign-language preference was skipped or not specified.",
            ),
            self._bool_statement(
                patch.needs.mobility.needs_step_free_route,
                yes_text="You requested step-free routing.",
                no_text="Step-free routing is not required.",
                unknown_text="Mobility routing preference was skipped or not specified.",
            ),
            self._bool_statement(
                patch.needs.cognitive.needs_simple_language,
                yes_text="You requested Simple English output.",
                no_text="Standard language output is acceptable.",
                unknown_text="Language simplicity preference was skipped or not specified.",
            ),
        ]
        return "Here is what I understood: " + " ".join(statements) + " Is this correct?"

    @staticmethod
    def _bool_statement(value: bool | None, yes_text: str, no_text: str, unknown_text: str) -> str:
        if value is True:
            return yes_text
        if value is False:
            return no_text
        return unknown_text

    def _normalize_language(self, language: str | None) -> str:
        if not language:
            return "en"
        normalized = language.strip().lower()
        if normalized in {"zh-cn", "zh-hans", "chinese"}:
            return "zh"
        if normalized in {"german", "deutsch"}:
            return "de"
        if normalized not in self._SUPPORTED_LANGS:
            return "en"
        return normalized

    def _question(self, context: str, language: str) -> str:
        lang = self._normalize_language(language)
        return self._QUESTION_TEXTS.get(lang, self._QUESTION_TEXTS["en"])[context]

    def _contextual_patch(self, user_message: str, question_context: str | None) -> dict[str, Any]:
        if not question_context:
            return {}

        answer = self._classify_short_answer(user_message)
        if answer not in {"yes", "no"}:
            return {}
        yes = answer == "yes"

        if question_context == "vision":
            return {
                "needs": {
                    "vision": {
                        "blind_or_low_vision": yes,
                        "prefers_landmarks": yes,
                    }
                }
            }

        if question_context == "hearing":
            if yes:
                return {"needs": {"hearing": {"deaf_or_hard_of_hearing": True}}}
            return {
                "needs": {
                    "hearing": {
                        "deaf_or_hard_of_hearing": False,
                        "sign_language_user": False,
                    }
                }
            }

        if question_context == "hearing_sign":
            if yes:
                return {
                    "needs": {"hearing": {"sign_language_user": True}},
                    "communication": {"output_mode": OutputMode.SIGN_GLOSS_TEXT.value},
                }
            return {"needs": {"hearing": {"sign_language_user": False}}}

        if question_context == "mobility":
            return {
                "needs": {
                    "mobility": {
                        "wheelchair_user": yes,
                        "needs_step_free_route": yes,
                        "avoid_long_walks": yes,
                    }
                }
            }

        if question_context == "cognitive":
            if yes:
                return {
                    "needs": {
                        "cognitive": {
                            "needs_simple_language": True,
                            "needs_memory_support": True,
                            "reading_or_memory_difficulty_or_child": True,
                        }
                    },
                    "communication": {"output_mode": OutputMode.SIMPLE_TEXT.value},
                }
            return {
                "needs": {
                    "cognitive": {
                        "needs_simple_language": False,
                        "needs_memory_support": False,
                        "reading_or_memory_difficulty_or_child": False,
                    }
                }
            }

        return {}

    @staticmethod
    def _classify_short_answer(user_message: str) -> str | None:
        raw = user_message.strip().lower()
        if not raw:
            return None

        compact = re.sub(r"[\s\.,!?;:，。！？；：\-_]+", "", raw)
        if not compact:
            return None

        skip_tokens = {
            "skip",
            "pass",
            "none",
            "na",
            "n/a",
            "跳过",
            "略过",
            "先跳过",
            "überspringen",
            "skippen",
            "keineangabe",
        }
        yes_tokens = {
            "yes",
            "y",
            "yeah",
            "yep",
            "sure",
            "ok",
            "okay",
            "ja",
            "有",
            "是",
            "对",
            "好",
            "可以",
            "需要",
            "需要的",
        }
        no_tokens = {
            "no",
            "n",
            "nope",
            "nein",
            "否",
            "没有",
            "不用",
            "不需要",
            "不是",
            "不",
            "kein",
            "nicht",
        }

        if compact in skip_tokens:
            return "skip"
        if compact in yes_tokens:
            return "yes"
        if compact in no_tokens:
            return "no"
        return None

    def _enforce_output_mode_rules(self, patch_dict: dict[str, Any]) -> dict[str, Any]:
        merged = self._deep_merge_dicts({}, patch_dict)
        needs = merged.setdefault("needs", {})
        cognitive = needs.setdefault("cognitive", {})
        hearing = needs.setdefault("hearing", {})
        communication = merged.setdefault("communication", {})

        sign_user = hearing.get("sign_language_user") is True
        needs_simple = (
            cognitive.get("needs_simple_language") is True
            or cognitive.get("reading_or_memory_difficulty_or_child") is True
        )

        if sign_user:
            communication["output_mode"] = OutputMode.SIGN_GLOSS_TEXT.value
        elif needs_simple:
            communication["output_mode"] = OutputMode.SIMPLE_TEXT.value

        return merged

    def _deep_merge_dicts(self, base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in incoming.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge_dicts(merged[key], value)
            elif isinstance(value, dict):
                merged[key] = self._deep_merge_dicts({}, value)
            elif value is not None:
                merged[key] = value
        return merged
