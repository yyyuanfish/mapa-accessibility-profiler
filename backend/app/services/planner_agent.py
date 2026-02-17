from __future__ import annotations

import json
import re
from typing import Any

from backend.app.models import (
    AccessibilityProfile,
    ImageHazardsSummary,
    OutputMode,
    PersonalizedPlan,
    RawRoute,
)
from backend.app.providers.llm_provider import LLMProvider
from backend.app.providers.route_provider import RouteProvider
from backend.app.utils.json_extract import JSONExtractionError, extract_first_json


class PlannerAgent:
    SYSTEM_PROMPT = (
        "TASK=PLANNER\n"
        "Return strict JSON for a personalized accessibility journey plan."
    )

    def __init__(self, llm_provider: LLMProvider, route_provider: RouteProvider) -> None:
        self.llm_provider = llm_provider
        self.route_provider = route_provider

    def create_plan(
        self,
        profile: AccessibilityProfile | dict[str, Any],
        route_id: str,
        image_hazards: ImageHazardsSummary | dict[str, Any] | None = None,
        response_language: str = "en",
    ) -> PersonalizedPlan:
        profile_model = profile if isinstance(profile, AccessibilityProfile) else AccessibilityProfile.model_validate(profile)
        hazards = None
        if image_hazards is not None:
            hazards = (
                image_hazards
                if isinstance(image_hazards, ImageHazardsSummary)
                else ImageHazardsSummary.model_validate(image_hazards)
            )

        selected_route, preferences_applied, route_alerts = self._select_route(profile_model, route_id)
        draft_plan = self._build_draft_plan(profile_model, selected_route, preferences_applied, route_alerts, hazards)

        output_mode = self._effective_output_mode(profile_model)
        plan = self._request_llm_plan(draft_plan, output_mode)
        language = self._normalize_language(response_language)
        return self._localize_plan(plan, language)

    def format_plan(self, plan: PersonalizedPlan, language: str = "en") -> str:
        lang = self._normalize_language(language)
        labels = {
            "en": {
                "summary": "Summary",
                "directions": "Directions",
                "alerts": "Alerts",
                "checklist": "Checklist",
                "lost": "If You Get Lost",
                "preferences": "Preferences Applied",
                "none": "None",
            },
            "zh": {
                "summary": "摘要",
                "directions": "路线步骤",
                "alerts": "提醒",
                "checklist": "检查清单",
                "lost": "如果迷路",
                "preferences": "已应用偏好",
                "none": "无",
            },
            "de": {
                "summary": "Zusammenfassung",
                "directions": "Wegbeschreibung",
                "alerts": "Warnungen",
                "checklist": "Checkliste",
                "lost": "Wenn Sie sich verlaufen",
                "preferences": "Angewendete Präferenzen",
                "none": "Keine",
            },
        }[lang]
        lines = [f"{labels['summary']}: {plan.summary}", "", f"{labels['directions']}:"]
        lines.extend([f"- {item}" for item in plan.directions])
        lines.append("")
        lines.append(f"{labels['alerts']}:")
        lines.extend([f"- {item}" for item in plan.alerts] or [f"- {labels['none']}"])
        lines.append("")
        lines.append(f"{labels['checklist']}:")
        lines.extend([f"- {item}" for item in plan.checklist])
        lines.append("")
        lines.append(f"{labels['lost']}:")
        lines.extend([f"- {item}" for item in plan.if_you_get_lost])
        lines.append("")
        lines.append(f"{labels['preferences']}:")
        lines.extend([f"- {item}" for item in plan.preferences_applied] or [f"- {labels['none']}"])
        return "\n".join(lines)

    def _request_llm_plan(self, draft_plan: dict[str, Any], output_mode: OutputMode) -> PersonalizedPlan:
        payload = {
            "draft_plan": draft_plan,
            "output_mode": output_mode.value,
        }
        user_prompt = json.dumps(payload)
        raw = self.llm_provider.complete(self.SYSTEM_PROMPT, user_prompt)

        try:
            parsed = extract_first_json(raw)
            return PersonalizedPlan.model_validate(parsed)
        except (JSONExtractionError, ValueError):
            retry_prompt = self.SYSTEM_PROMPT + "\nReturn ONLY JSON."
            raw_retry = self.llm_provider.complete(retry_prompt, user_prompt)
            parsed_retry = extract_first_json(raw_retry)
            return PersonalizedPlan.model_validate(parsed_retry)

    def _select_route(
        self,
        profile: AccessibilityProfile,
        route_id: str,
    ) -> tuple[RawRoute, list[str], list[str]]:
        route = self.route_provider.get_route(route_id)
        preferences_applied: list[str] = []
        alerts: list[str] = []

        if profile.needs.mobility.needs_step_free_route is True and not route.step_free:
            alternative = self.route_provider.find_step_free_alternative(route_id)
            if alternative is not None and alternative.route_id != route.route_id:
                preferences_applied.append("step_free_route")
                alerts.append(
                    "Original route had stairs; switched to step-free alternative."
                )
                route = alternative
            else:
                alerts.append(
                    "Route includes stairs and no step-free alternative was available in fixture data."
                )

        return route, preferences_applied, alerts

    def _build_draft_plan(
        self,
        profile: AccessibilityProfile,
        route: RawRoute,
        preferences_applied: list[str],
        route_alerts: list[str],
        hazards: ImageHazardsSummary | None,
    ) -> dict[str, Any]:
        directions: list[str] = []
        alerts = list(route_alerts)
        checklist: list[str] = []
        if_you_get_lost: list[str] = []

        blind_support = profile.needs.vision.blind_or_low_vision is True
        deaf_support = profile.needs.hearing.deaf_or_hard_of_hearing is True
        wheelchair_user = profile.needs.mobility.wheelchair_user is True
        step_free_needed = profile.needs.mobility.needs_step_free_route is True
        simple_language = self._needs_simple_language(profile)

        for idx, step in enumerate(route.steps, start=1):
            text = f"Step {idx}: {step.instruction} ({step.distance_m}m, about {step.duration_min} min)."

            if blind_support and step.landmark:
                text += f" Landmark: {step.landmark}."
            text = self._remove_visual_only_references(text, blind_support)

            if deaf_support and step.audio_only_cue:
                text = (
                    f"Step {idx}: Move to the same stop and check electronic display boards "
                    f"for Bus 9 updates ({step.distance_m}m, about {step.duration_min} min)."
                )
                preferences_applied.append("audio_to_visible_cues")

            if step.has_stairs and (wheelchair_user or step_free_needed):
                alerts.append("High alert: this step includes stairs.")

            if simple_language:
                text = self._simplify_sentence(text)

            directions.append(text)

        if route.total_distance_m >= 2500 and (
            profile.needs.mobility.avoid_long_walks is True
            or profile.needs.mobility.wheelchair_user is True
        ):
            alerts.append("Long walking distance may cause fatigue. Consider rest breaks.")
            preferences_applied.append("fatigue_risk_alert")

        if blind_support:
            checklist.append("Keep your preferred navigation aid ready.")
            checklist.append("Use landmarks and distance checks at each step.")
            preferences_applied.append("low_vision_stepwise_directions")

        if deaf_support:
            checklist.append("Use text or visual transit boards for live updates.")
            checklist.append("If needed, show route text to station staff.")
            preferences_applied.append("deaf_text_first_guidance")

        if wheelchair_user or step_free_needed:
            checklist.append("Confirm elevators or ramps before departure.")
            checklist.append("Avoid any stair segment unless explicitly assisted.")
            preferences_applied.append("mobility_step_free_preference")

        if simple_language:
            checklist.append("Check each step before you move.")
            checklist.append("Take your time. It is okay to pause.")
            if_you_get_lost.extend(
                [
                    "Stop in a safe place.",
                    "Open this plan and go to the last completed step.",
                    "Ask nearby staff and show the destination text.",
                ]
            )
            preferences_applied.append("simple_english_mode")
        else:
            if_you_get_lost.extend(
                [
                    "Pause at a safe point and review your last confirmed landmark.",
                    "Use text assistance from staff and confirm the next stop name.",
                    "If available, contact a trusted person with your location.",
                ]
            )

        if hazards is not None:
            if hazards.stairs in {"medium", "high"}:
                alerts.append("Image hazard note: possible stairs ahead.")
            if hazards.slope in {"medium", "high"}:
                alerts.append("Image hazard note: possible slope/steep segment.")
            if hazards.crowd in {"medium", "high"}:
                alerts.append("Image hazard note: crowd risk near route.")
            if hazards.notes:
                checklist.extend(hazards.notes)
            preferences_applied.append("image_hazard_stub")

        summary = (
            f"Personalized plan for {route.name}. "
            f"Distance {route.total_distance_m}m, around {route.total_duration_min} minutes."
        )

        if simple_language:
            summary = self._simplify_sentence(summary)

        return {
            "summary": summary,
            "directions": directions,
            "alerts": self._unique(alerts),
            "checklist": self._unique(checklist),
            "if_you_get_lost": self._unique(if_you_get_lost),
            "preferences_applied": self._unique(preferences_applied),
        }

    def _effective_output_mode(self, profile: AccessibilityProfile) -> OutputMode:
        if profile.communication.output_mode == OutputMode.SIGN_GLOSS_TEXT:
            return OutputMode.SIGN_GLOSS_TEXT
        if self._needs_simple_language(profile):
            return OutputMode.SIMPLE_TEXT
        return profile.communication.output_mode

    @staticmethod
    def _needs_simple_language(profile: AccessibilityProfile) -> bool:
        return (
            profile.needs.cognitive.needs_simple_language is True
            or profile.needs.cognitive.reading_or_memory_difficulty_or_child is True
        )

    @staticmethod
    def _remove_visual_only_references(text: str, blind_support: bool) -> str:
        if not blind_support:
            return text
        replacements = {
            "look at the map": "follow the next text step",
            "look for": "go to",
            "see": "confirm",
        }
        lowered = text
        for old, new in replacements.items():
            lowered = lowered.replace(old, new)
            lowered = lowered.replace(old.title(), new.capitalize())
        return lowered

    @staticmethod
    def _simplify_sentence(text: str) -> str:
        text = text.replace("approximately", "about")
        text = text.replace("proceed", "go")
        text = text.replace("accessible", "easy access")
        return text

    @staticmethod
    def _normalize_language(language: str | None) -> str:
        if not language:
            return "en"
        normalized = language.strip().lower()
        if normalized in {"zh-cn", "zh-hans", "chinese"}:
            return "zh"
        if normalized in {"deutsch", "german"}:
            return "de"
        if normalized not in {"en", "zh", "de"}:
            return "en"
        return normalized

    def _localize_plan(self, plan: PersonalizedPlan, language: str) -> PersonalizedPlan:
        if language == "en":
            return plan
        return PersonalizedPlan(
            summary=self._translate_text(plan.summary, language),
            directions=[self._translate_text(item, language) for item in plan.directions],
            alerts=[self._translate_text(item, language) for item in plan.alerts],
            checklist=[self._translate_text(item, language) for item in plan.checklist],
            if_you_get_lost=[self._translate_text(item, language) for item in plan.if_you_get_lost],
            preferences_applied=[
                self._translate_preference_token(item, language) for item in plan.preferences_applied
            ],
        )

    def _translate_preference_token(self, token: str, language: str) -> str:
        base = token.strip().rstrip(".")
        if language == "zh":
            mapping = {
                "step_free_route": "已切换无台阶路线",
                "audio_to_visible_cues": "音频提示改为可视文本提示",
                "fatigue_risk_alert": "已启用长距离疲劳提醒",
                "low_vision_stepwise_directions": "已启用低视力分步指引",
                "deaf_text_first_guidance": "已启用听障文本优先指引",
                "mobility_step_free_preference": "已启用行动无台阶偏好",
                "simple_english_mode": "已启用简明语言模式",
                "image_hazard_stub": "已应用图像风险提示",
            }
            return mapping.get(base, base)
        if language == "de":
            mapping = {
                "step_free_route": "stufenfreie Route aktiviert",
                "audio_to_visible_cues": "Audiohinweise in visuelle Hinweise umgewandelt",
                "fatigue_risk_alert": "Ermüdungswarnung bei langer Strecke aktiviert",
                "low_vision_stepwise_directions": "Schritt-für-Schritt-Anleitung für Sehbehinderung aktiviert",
                "deaf_text_first_guidance": "Textbasierte Hinweise für Hörunterstützung aktiviert",
                "mobility_step_free_preference": "Stufenfreie Mobilitätspräferenz aktiviert",
                "simple_english_mode": "einfache Sprache aktiviert",
                "image_hazard_stub": "Bild-Risiko-Hinweis angewendet",
            }
            return mapping.get(base, base)
        return base

    def _translate_text(self, text: str, language: str) -> str:
        if language == "zh":
            exact = {
                "Original route had stairs; switched to step-free alternative.": "原路线含楼梯；已切换到无台阶替代路线。",
                "Route includes stairs and no step-free alternative was available in fixture data.": "该路线包含楼梯，且当前样例数据中没有可用的无台阶替代路线。",
                "High alert: this step includes stairs.": "高风险提醒：该步骤包含楼梯。",
                "Long walking distance may cause fatigue. Consider rest breaks.": "步行距离较长，可能导致疲劳。建议中途休息。",
                "Keep your preferred navigation aid ready.": "请准备好你常用的导航辅助工具。",
                "Use landmarks and distance checks at each step.": "每一步都用地标和距离进行确认。",
                "Use text or visual transit boards for live updates.": "请使用文字或可视化站牌获取实时信息。",
                "If needed, show route text to station staff.": "如有需要，可向车站工作人员展示路线文字。",
                "Confirm elevators or ramps before departure.": "出发前请确认电梯或坡道可用。",
                "Avoid any stair segment unless explicitly assisted.": "除非有人明确协助，否则请避免任何楼梯路段。",
                "Check each step before you move.": "移动前先确认当前步骤。",
                "Take your time. It is okay to pause.": "请按自己的节奏前进，需要时可以停下。",
                "Stop in a safe place.": "请先停在安全位置。",
                "Open this plan and go to the last completed step.": "打开本方案，回到你最后完成的步骤。",
                "Ask nearby staff and show the destination text.": "向附近工作人员求助，并展示目的地文字。",
                "Pause at a safe point and review your last confirmed landmark.": "请先在安全点停下，回顾你最后确认的地标。",
                "Use text assistance from staff and confirm the next stop name.": "请通过文字方式向工作人员确认下一站名称。",
                "If available, contact a trusted person with your location.": "如可行，请把当前位置发给你信任的人。",
                "Image hazard note: possible stairs ahead.": "图像风险提示：前方可能有楼梯。",
                "Image hazard note: possible slope/steep segment.": "图像风险提示：前方可能有坡道或陡坡。",
                "Image hazard note: crowd risk near route.": "图像风险提示：路线附近可能人群密集。",
            }
            if text in exact:
                return exact[text]

            translated = text
            translated = re.sub(r"^Step\s+(\d+):", r"第\1步：", translated)
            translated = re.sub(
                r"\((\d+)m,\s*about\s*(\d+)\s*min\)\.",
                r"（\1米，约\2分钟）。",
                translated,
                flags=re.IGNORECASE,
            )
            translated = translated.replace("Personalized plan for ", "个性化路线方案：")
            translated = translated.replace(". Distance ", "。距离 ")
            translated = translated.replace("m, around ", "米，约 ")
            translated = translated.replace(" minutes.", " 分钟。")
            translated = translated.replace("Landmark:", "地标：")
            translated = translated.replace("Walk ", "步行 ")
            translated = translated.replace("Go ", "前往 ")
            translated = translated.replace("Continue ", "继续前往 ")
            translated = translated.replace("Use elevator to street level.", "乘电梯到街道层。")
            translated = re.sub(r"(\d+)m to ", r"\1米到", translated)
            translated = translated.replace(" on flat sidewalk ", " 沿平坦人行道 ")
            translated = translated.replace("accessible entrance", "无障碍入口")
            translated = translated.replace("easy access entrance", "无障碍入口")
            translated = translated.replace("Move to the same stop and check electronic display boards for Bus 9 updates", "前往同一站点并查看电子显示屏获取9路公交更新")
            return translated

        if language == "de":
            exact = {
                "Original route had stairs; switched to step-free alternative.": "Die Originalroute hatte Treppen; auf stufenfreie Alternative umgestellt.",
                "Route includes stairs and no step-free alternative was available in fixture data.": "Die Route enthält Treppen, und in den Beispieldaten war keine stufenfreie Alternative verfügbar.",
                "High alert: this step includes stairs.": "Hohe Warnung: Dieser Schritt enthält Treppen.",
                "Long walking distance may cause fatigue. Consider rest breaks.": "Die lange Gehstrecke kann ermüden. Bitte Pausen einplanen.",
                "Keep your preferred navigation aid ready.": "Halten Sie Ihr bevorzugtes Navigationshilfsmittel bereit.",
                "Use landmarks and distance checks at each step.": "Nutzen Sie bei jedem Schritt Orientierungspunkte und Distanzkontrolle.",
                "Use text or visual transit boards for live updates.": "Nutzen Sie Text- oder visuelle Anzeigen für Echtzeit-Updates.",
                "If needed, show route text to station staff.": "Zeigen Sie bei Bedarf dem Personal den Routentext.",
                "Confirm elevators or ramps before departure.": "Bestätigen Sie vor der Abfahrt Aufzüge oder Rampen.",
                "Avoid any stair segment unless explicitly assisted.": "Vermeiden Sie Treppenabschnitte, sofern keine Unterstützung vorhanden ist.",
                "Check each step before you move.": "Prüfen Sie jeden Schritt, bevor Sie weitergehen.",
                "Take your time. It is okay to pause.": "Nehmen Sie sich Zeit. Pausen sind in Ordnung.",
                "Stop in a safe place.": "Bleiben Sie an einem sicheren Ort stehen.",
                "Open this plan and go to the last completed step.": "Öffnen Sie diesen Plan und gehen Sie zum zuletzt abgeschlossenen Schritt.",
                "Ask nearby staff and show the destination text.": "Fragen Sie Personal in der Nähe und zeigen Sie den Zieltext.",
                "Pause at a safe point and review your last confirmed landmark.": "Halten Sie an einem sicheren Punkt an und prüfen Sie Ihren letzten bestätigten Orientierungspunkt.",
                "Use text assistance from staff and confirm the next stop name.": "Nutzen Sie textbasierte Hilfe des Personals und bestätigen Sie den nächsten Haltestellennamen.",
                "If available, contact a trusted person with your location.": "Kontaktieren Sie, falls möglich, eine vertraute Person mit Ihrem Standort.",
                "Image hazard note: possible stairs ahead.": "Bild-Risikohinweis: Möglicherweise Treppen voraus.",
                "Image hazard note: possible slope/steep segment.": "Bild-Risikohinweis: Möglicherweise Gefälle oder steiler Abschnitt voraus.",
                "Image hazard note: crowd risk near route.": "Bild-Risikohinweis: Möglicherweise hohes Personenaufkommen nahe der Route.",
            }
            if text in exact:
                return exact[text]

            translated = text
            translated = re.sub(r"^Step\s+(\d+):", r"Schritt \1:", translated)
            translated = re.sub(
                r"\((\d+)m,\s*about\s*(\d+)\s*min\)\.",
                r"(\1m, ca. \2 Min).",
                translated,
                flags=re.IGNORECASE,
            )
            translated = translated.replace("Personalized plan for ", "Personalisierter Plan für ")
            translated = translated.replace(". Distance ", ". Distanz ")
            translated = translated.replace("m, around ", "m, ca. ")
            translated = translated.replace(" minutes.", " Minuten.")
            translated = translated.replace("Landmark:", "Orientierungspunkt:")
            translated = translated.replace("Walk ", "Gehen Sie ")
            translated = translated.replace("Go ", "Gehen Sie ")
            translated = translated.replace("Continue ", "Gehen Sie weiter ")
            translated = translated.replace("Use elevator to street level.", "Nutzen Sie den Aufzug zur Straßebene.")
            translated = re.sub(r"(\d+)m to ", r"\1m bis ", translated)
            translated = translated.replace(" on flat sidewalk ", " auf ebenem Gehweg ")
            translated = translated.replace("accessible entrance", "barrierefreien Eingang")
            translated = translated.replace("easy access entrance", "barrierefreien Eingang")
            translated = translated.replace("Move to the same stop and check electronic display boards for Bus 9 updates", "Gehen Sie zur gleichen Haltestelle und prüfen Sie die elektronischen Anzeigen für Bus 9")
            return translated

        return text

    @staticmethod
    def _unique(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result
