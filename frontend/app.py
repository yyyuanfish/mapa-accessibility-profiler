from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import streamlit as st

# Ensure project root is importable when Streamlit sets script dir as cwd.
ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

FIXTURE_IMAGE_DIR = ROOT / "frontend" / "fixtures" / "images"

DEFAULT_SAMPLE_HAZARDS: dict[str, dict[str, Any]] = {
    "default_stairs.png": {
        "stairs": "high",
        "slope": "none",
        "crowd": "none",
        "notes": ["Default sample fixture: stairs hazard."],
    },
    "default_slope.png": {
        "stairs": "none",
        "slope": "high",
        "crowd": "none",
        "notes": ["Default sample fixture: slope hazard."],
    },
    "default_crowd.png": {
        "stairs": "none",
        "slope": "none",
        "crowd": "high",
        "notes": ["Default sample fixture: crowd hazard."],
    },
    "default_none.png": {
        "stairs": "none",
        "slope": "none",
        "crowd": "none",
        "notes": ["Default sample fixture: no major hazard."],
    },
}

from backend.app.models import OutputMode
from backend.app.providers.image_provider import ImageProvider, MockImageProvider, OllamaImageProvider
from backend.app.providers.llm_provider import LLMProvider, MockLLMProvider, OllamaLLMProvider
from backend.app.providers.route_provider import MockRouteProvider
from backend.app.services.planner_agent import PlannerAgent
from backend.app.services.profiler_agent import ProfilerAgent


def init_state() -> None:
    defaults: dict[str, Any] = {
        "consent_profile": False,
        "consent_image": False,
        "profile_patch": {},
        "skipped_domains": [],
        "final_profile": None,
        "chat_history": [],
        "last_question_context": None,
        "response_language_choice": "Auto",
        "response_language": "en",
        "provider_mode": "Mock (offline)",
        "ollama_base_url": "http://localhost:11434",
        "ollama_text_model": "llama3.1:8b",
        "ollama_vision_model": "llava:7b",
        "ollama_timeout_sec": 300,
        "ollama_status": "",
        "ollama_available_models": [],
        "ollama_retry_nonce": 0,
        "plan_json": None,
        "plan_text": None,
        "hazards_json": None,
        "image_hazard_cache": {},
        "step_index": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_services() -> tuple[ProfilerAgent, PlannerAgent, MockRouteProvider, ImageProvider]:
    config = (
        st.session_state["provider_mode"],
        st.session_state["ollama_base_url"],
        st.session_state["ollama_text_model"],
        st.session_state["ollama_vision_model"],
        st.session_state["ollama_timeout_sec"],
        st.session_state["ollama_retry_nonce"],
    )
    if "_services" not in st.session_state or st.session_state.get("_services_config") != config:
        route_provider = MockRouteProvider()
        llm_provider: LLMProvider
        image_provider: ImageProvider

        if st.session_state["provider_mode"] == "Ollama (local)":
            try:
                normalized_url = normalize_ollama_base_url(st.session_state["ollama_base_url"])
                llm_provider = OllamaLLMProvider(
                    model=st.session_state["ollama_text_model"],
                    base_url=normalized_url,
                    timeout_sec=int(st.session_state["ollama_timeout_sec"]),
                )
                ok, status_msg, resolved_url, available_models = llm_provider.health_check()
                st.session_state["ollama_status"] = status_msg
                st.session_state["ollama_available_models"] = available_models

                if not ok:
                    raise RuntimeError(status_msg)

                st.session_state["ollama_base_url"] = resolved_url
                llm_provider.base_url = resolved_url

                image_provider = OllamaImageProvider(
                    model=st.session_state["ollama_vision_model"],
                    base_url=resolved_url,
                    timeout_sec=int(st.session_state["ollama_timeout_sec"]),
                )

                missing_models = [
                    model_name
                    for model_name in [
                        st.session_state["ollama_text_model"],
                        st.session_state["ollama_vision_model"],
                    ]
                    if model_name not in available_models
                ]
                if missing_models:
                    st.warning(
                        "Ollama connected, but model(s) not found: "
                        + ", ".join(missing_models)
                        + ". Run `ollama pull <model>`."
                    )
            except Exception as exc:
                st.error(f"Ollama unavailable: {exc}")
                st.info("Using Mock providers for this run. Keep Ollama mode selected and retry after `ollama serve`.")
                llm_provider = MockLLMProvider()
                image_provider = MockImageProvider()
        else:
            st.session_state["ollama_status"] = ""
            st.session_state["ollama_available_models"] = []
            llm_provider = MockLLMProvider()
            image_provider = MockImageProvider()

        profiler = ProfilerAgent(llm_provider=llm_provider)
        planner = PlannerAgent(llm_provider=llm_provider, route_provider=route_provider)
        st.session_state["_services"] = (profiler, planner, route_provider, image_provider)
        st.session_state["_services_config"] = config
    return st.session_state["_services"]


UI_TEXT = {
    "en": {
        "title": "Multimodal Accessibility Profiling Agent",
        "caption": "Offline-first prototype with mock providers.",
        "ui_mode": "UI mode",
        "chat_only": "Chat-only",
        "stepper": "Button-based stepper",
        "chat_mode": "Chat-Only Mode",
        "stepper_mode": "Button-Based Stepper",
        "consent_first": "Consent first. You can answer with yes/no/skip (or 有/没有/是/否, ja/nein).",
        "assistant_language": "Assistant language",
        "consent_profile": "I consent to functional accessibility profiling",
        "consent_image": "I consent to optional image hazard analysis (stub)",
        "image_source": "Image source",
        "image_source_upload": "Upload",
        "image_source_sample": "Sample images",
        "image_upload_label": "Optional image upload for hazard stub",
        "image_sample_select": "Choose a sample image",
        "image_sample_empty": "No sample images found.",
        "image_sample_default_note": "Default sample image: fixed hazard result for demo.",
        "image_preview": "Selected image",
        "image_failed": "Image analysis failed",
        "image_analyze": "Analyze image hazards",
        "image_analyzing": "Analyzing image hazards...",
        "image_waiting": "Select an image, then click 'Analyze image hazards'.",
        "image_cached": "Showing cached image hazard result.",
        "image_ollama_tip": "First Ollama vision run may take time while the model loads.",
        "enable_consent": "Enable consent to start profiling.",
        "reset_chat": "Reset chat session",
        "type_answer": "Type your answer",
        "next_prefix": "Next question: ",
        "done": "Profile looks complete. You can generate a personalized plan now.",
        "select_route": "Select route fixture",
        "generate_plan": "Generate Personalized Plan",
        "need_profile_first": "Finish at least one profiling turn first.",
        "profile_json": "Profile JSON",
        "plan_formatted": "Personalized Plan (formatted)",
        "plan_json": "Personalized Plan JSON",
        "runtime": "Runtime",
        "llm_backend": "LLM backend",
        "ollama_base_url": "Ollama base URL",
        "text_model": "Text model",
        "vision_model": "Vision model",
        "timeout_sec": "Timeout (sec)",
        "retry_ollama": "Retry Ollama connection",
        "available_models": "Available models",
        "mock_caption": "Using deterministic Mock providers (fully offline).",
        "profiler_failed": "Profiler failed",
        "planner_failed": "Planner failed",
        "fallback_mock": "Falling back to Mock provider for this turn.",
        "fallback_plan": "Falling back to Mock provider for plan generation.",
        "mock_note": "Note: Used Mock fallback for this turn due to an Ollama error.",
        "details": "Details",
        "step_current": "Current step",
        "step_names": ["Consent", "Profile", "Trip", "Review/Export"],
        "save_profile": "Save Profile",
        "profile_saved": "Profile saved.",
        "create_plan": "Create Personalized Plan",
        "plan_created": "Plan created.",
        "create_profile_first": "Create and save profile first.",
        "back": "Back",
        "next": "Next",
        "download_profile": "Download profile.json",
        "download_plan": "Download personalized_plan.json",
        "step_questions": {
            "vision": "Blind or low vision support needed?",
            "hearing": "Deaf or hard-of-hearing support needed?",
            "sign": "Sign-language style output needed?",
            "wheelchair": "Wheelchair user?",
            "step_free": "Need step-free route?",
            "simple": "Need Simple English?",
            "memory": "Need memory reminders?",
            "child_or_reading": "Reading/memory difficulty or child-focused support?",
        },
        "opener": (
            "I will ask a few short questions about functional access needs. "
            "You can skip any question. First: Do you have any vision-related access needs?"
        ),
    },
    "zh": {
        "title": "多模态无障碍画像助手",
        "caption": "离线优先原型（支持本地模型与 Mock）。",
        "ui_mode": "界面模式",
        "chat_only": "仅聊天",
        "stepper": "分步按钮",
        "chat_mode": "聊天模式",
        "stepper_mode": "分步模式",
        "consent_first": "请先同意。你可以回答 有/没有/是/否/跳过。",
        "assistant_language": "助手语言",
        "consent_profile": "我同意进行功能性无障碍画像",
        "consent_image": "我同意进行图片风险分析（可选）",
        "image_source": "图片来源",
        "image_source_upload": "上传",
        "image_source_sample": "示例图片",
        "image_upload_label": "可选图片上传（风险分析）",
        "image_sample_select": "选择示例图片",
        "image_sample_empty": "未找到示例图片。",
        "image_sample_default_note": "默认示例图：用于演示的固定风险结果。",
        "image_preview": "已选图片",
        "image_failed": "图片分析失败",
        "image_analyze": "分析图片风险",
        "image_analyzing": "正在分析图片风险...",
        "image_waiting": "先选择图片，再点击“分析图片风险”。",
        "image_cached": "已显示缓存的图片分析结果。",
        "image_ollama_tip": "Ollama 视觉模型首次运行加载较慢，请稍等。",
        "enable_consent": "需要先勾选同意才能开始。",
        "reset_chat": "重置聊天",
        "type_answer": "请输入回答",
        "next_prefix": "下一题：",
        "done": "用户画像已基本完成。现在可以生成个性化路线方案。",
        "select_route": "选择路线样例",
        "generate_plan": "生成个性化路线方案",
        "need_profile_first": "请先完成至少一轮画像。",
        "profile_json": "用户画像 JSON",
        "plan_formatted": "个性化方案（可读版）",
        "plan_json": "个性化方案 JSON",
        "runtime": "运行环境",
        "llm_backend": "LLM 后端",
        "ollama_base_url": "Ollama 地址",
        "text_model": "文本模型",
        "vision_model": "视觉模型",
        "timeout_sec": "超时（秒）",
        "retry_ollama": "重试 Ollama 连接",
        "available_models": "可用模型",
        "mock_caption": "使用本地 Mock（完全离线）。",
        "profiler_failed": "画像失败",
        "planner_failed": "规划失败",
        "fallback_mock": "本轮使用 Mock 兜底。",
        "fallback_plan": "本次规划使用 Mock 兜底。",
        "mock_note": "提示：本轮因 Ollama 错误使用了 Mock。",
        "details": "详情",
        "step_current": "当前步骤",
        "step_names": ["同意", "画像", "行程", "导出/复核"],
        "save_profile": "保存画像",
        "profile_saved": "画像已保存。",
        "create_plan": "生成个性化路线方案",
        "plan_created": "方案已生成。",
        "create_profile_first": "请先完成并保存画像。",
        "back": "上一步",
        "next": "下一步",
        "download_profile": "下载 profile.json",
        "download_plan": "下载 personalized_plan.json",
        "step_questions": {
            "vision": "是否需要盲人/低视力支持？",
            "hearing": "是否需要听力支持？",
            "sign": "是否需要手语风格输出？",
            "wheelchair": "是否使用轮椅？",
            "step_free": "是否需要无台阶路线？",
            "simple": "是否需要简明语言？",
            "memory": "是否需要记忆提醒？",
            "child_or_reading": "是否需要儿童/读写支持？",
        },
        "opener": "我会问你几个简短问题来了解功能性无障碍需求。你可以随时跳过。先问：你有视觉相关的出行需求吗？",
    },
    "de": {
        "title": "Multimodaler Barrierefreiheits-Profiling-Assistent",
        "caption": "Offline-First-Prototyp (lokale Modelle oder Mock).",
        "ui_mode": "UI-Modus",
        "chat_only": "Nur Chat",
        "stepper": "Schrittweise Buttons",
        "chat_mode": "Chat-Modus",
        "stepper_mode": "Schrittmodus",
        "consent_first": "Zuerst Einwilligung. Antworten: ja/nein/überspringen.",
        "assistant_language": "Assistentensprache",
        "consent_profile": "Ich stimme dem funktionalen Profiling zu",
        "consent_image": "Ich stimme der optionalen Bildanalyse zu",
        "image_source": "Bildquelle",
        "image_source_upload": "Upload",
        "image_source_sample": "Beispielbilder",
        "image_upload_label": "Optionaler Bild-Upload (Gefahrenanalyse)",
        "image_sample_select": "Beispielbild wählen",
        "image_sample_empty": "Keine Beispielbilder gefunden.",
        "image_sample_default_note": "Standard-Beispielbild: festes Gefahren-Ergebnis für Demo.",
        "image_preview": "Ausgewähltes Bild",
        "image_failed": "Bildanalyse fehlgeschlagen",
        "image_analyze": "Bildgefahren analysieren",
        "image_analyzing": "Bildgefahren werden analysiert...",
        "image_waiting": "Bild auswählen und dann auf 'Bildgefahren analysieren' klicken.",
        "image_cached": "Zwischengespeichertes Ergebnis wird angezeigt.",
        "image_ollama_tip": "Der erste Ollama-Visionslauf kann wegen Modell-Laden länger dauern.",
        "enable_consent": "Bitte Einwilligung aktivieren.",
        "reset_chat": "Chat zurücksetzen",
        "type_answer": "Antwort eingeben",
        "next_prefix": "Nächste Frage: ",
        "done": "Profil weitgehend vollständig. Sie können jetzt einen Plan erstellen.",
        "select_route": "Routen-Beispiel auswählen",
        "generate_plan": "Personalisierten Plan erstellen",
        "need_profile_first": "Bitte zuerst mindestens eine Profilrunde abschließen.",
        "profile_json": "Profil JSON",
        "plan_formatted": "Plan (lesbar)",
        "plan_json": "Plan JSON",
        "runtime": "Laufzeit",
        "llm_backend": "LLM-Backend",
        "ollama_base_url": "Ollama Basis-URL",
        "text_model": "Textmodell",
        "vision_model": "Visionsmodell",
        "timeout_sec": "Timeout (Sek.)",
        "retry_ollama": "Ollama-Verbindung erneut",
        "available_models": "Verfügbare Modelle",
        "mock_caption": "Deterministische Mock-Provider (voll offline).",
        "profiler_failed": "Profiling fehlgeschlagen",
        "planner_failed": "Planung fehlgeschlagen",
        "fallback_mock": "Für diese Runde Mock-Provider genutzt.",
        "fallback_plan": "Für die Planung Mock-Provider genutzt.",
        "mock_note": "Hinweis: Mock wurde wegen Ollama-Fehler genutzt.",
        "details": "Details",
        "step_current": "Aktueller Schritt",
        "step_names": ["Einwilligung", "Profil", "Route", "Review/Export"],
        "save_profile": "Profil speichern",
        "profile_saved": "Profil gespeichert.",
        "create_plan": "Plan erstellen",
        "plan_created": "Plan erstellt.",
        "create_profile_first": "Bitte zuerst Profil erstellen und speichern.",
        "back": "Zurück",
        "next": "Weiter",
        "download_profile": "profile.json herunterladen",
        "download_plan": "personalized_plan.json herunterladen",
        "step_questions": {
            "vision": "Unterstützung bei Sehbehinderung benötigt?",
            "hearing": "Unterstützung für Hörbeeinträchtigung benötigt?",
            "sign": "Gebärdensprachnahe Ausgabe benötigt?",
            "wheelchair": "Rollstuhlnutzer?",
            "step_free": "Stufenfreie Route benötigt?",
            "simple": "Einfache Sprache benötigt?",
            "memory": "Erinnerungshilfen benötigt?",
            "child_or_reading": "Unterstützung für Lesen/Kind benötigt?",
        },
        "opener": (
            "Ich stelle Ihnen ein paar kurze Fragen zu funktionalen Zugangsbedarfen. "
            "Sie können jede Frage überspringen. Zuerst: Haben Sie visuelle Zugangsbedarfe?"
        ),
    },
}


def detect_language(text: str) -> str:
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return "zh"
    lowered = text.lower()
    if re.search(r"\b(ja|nein|ich|bitte|möchte)\b", lowered) or any(ch in lowered for ch in ["ü", "ä", "ö", "ß"]):
        return "de"
    return "en"


def resolve_response_language(choice: str, user_input: str, last_language: str = "en") -> str:
    if choice == "English":
        return "en"
    if choice == "中文":
        return "zh"
    if choice == "Deutsch":
        return "de"
    # Auto: default English
    return "en"


def normalize_ollama_base_url(raw_url: str) -> str:
    value = raw_url.strip()
    if not value:
        return "http://localhost:11434"
    if "://" not in value:
        value = f"http://{value}"
    return value.rstrip("/")


def classify_short_answer(user_message: str) -> str | None:
    compact = "".join(ch.lower() for ch in user_message.strip() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    if compact in {"skip", "pass", "none", "na", "跳过", "略过", "先跳过", "überspringen", "skippen", "keineangabe"}:
        return "skip"
    if compact in {"yes", "y", "yeah", "yep", "ok", "okay", "sure", "ja", "有", "是", "对", "好", "可以", "需要"}:
        return "yes"
    if compact in {"no", "n", "nope", "nein", "否", "没有", "不用", "不需要", "不是", "不"}:
        return "no"
    return None


def context_to_domain(context: str | None) -> str | None:
    if context in {"vision", "hearing", "mobility", "cognitive"}:
        return context
    if context == "hearing_sign":
        return "hearing"
    return None


def list_fixture_images() -> list[Path]:
    if not FIXTURE_IMAGE_DIR.exists():
        return []
    images = [
        path
        for path in FIXTURE_IMAGE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    ]
    image_by_name = {path.name: path for path in images}
    ordered: list[Path] = []
    for name in DEFAULT_SAMPLE_HAZARDS:
        if name in image_by_name:
            ordered.append(image_by_name[name])
    extra = [path for path in images if path.name not in DEFAULT_SAMPLE_HAZARDS]
    ordered.extend(sorted(extra, key=lambda item: item.name.lower()))
    return ordered


def maybe_image_hazards(
    image_provider: ImageProvider,
    text: dict[str, Any],
    key_prefix: str = "image",
) -> dict | None:
    hazards = None
    if st.session_state["consent_image"]:
        if st.session_state.get("provider_mode") == "Ollama (local)":
            st.caption(text["image_ollama_tip"])

        source = st.radio(
            text["image_source"],
            options=[text["image_source_upload"], text["image_source_sample"]],
            horizontal=True,
            key=f"{key_prefix}_source",
        )
        image_bytes: bytes | None = None
        image_key: str | None = None
        selected_sample_name: str | None = None

        if source == text["image_source_upload"]:
            uploaded = st.file_uploader(
                text["image_upload_label"],
                type=["png", "jpg", "jpeg"],
                key=f"{key_prefix}_upload",
            )
            if uploaded is not None:
                image_bytes = uploaded.getvalue()
                digest = hashlib.sha256(image_bytes).hexdigest()
                image_key = f"upload:{uploaded.name}:{digest}"
                st.image(image_bytes, caption=text["image_preview"], width="stretch")
        else:
            fixtures = list_fixture_images()
            if not fixtures:
                st.info(text["image_sample_empty"])
            else:
                names = [path.name for path in fixtures]
                selected = st.selectbox(
                    text["image_sample_select"],
                    options=names,
                    key=f"{key_prefix}_sample",
                )
                if selected:
                    selected_sample_name = selected
                    path = next(item for item in fixtures if item.name == selected)
                    image_bytes = path.read_bytes()
                    image_key = f"sample:{selected}"
                    st.image(image_bytes, caption=path.name, width="stretch")
                    if selected in DEFAULT_SAMPLE_HAZARDS:
                        st.caption(text["image_sample_default_note"])

        if image_bytes is None or image_key is None:
            return hazards

        cache = st.session_state["image_hazard_cache"]
        if image_key in cache:
            hazards = cache[image_key]
            st.session_state["hazards_json"] = hazards
            st.info(text["image_cached"])
            st.json(hazards)
            return hazards

        if st.button(text["image_analyze"], key=f"{key_prefix}_analyze"):
            try:
                with st.spinner(text["image_analyzing"]):
                    if selected_sample_name and selected_sample_name in DEFAULT_SAMPLE_HAZARDS:
                        hazards = {
                            "stairs": DEFAULT_SAMPLE_HAZARDS[selected_sample_name]["stairs"],
                            "slope": DEFAULT_SAMPLE_HAZARDS[selected_sample_name]["slope"],
                            "crowd": DEFAULT_SAMPLE_HAZARDS[selected_sample_name]["crowd"],
                            "notes": list(DEFAULT_SAMPLE_HAZARDS[selected_sample_name]["notes"]),
                        }
                    else:
                        hazards_model = image_provider.summarize_hazards(image_bytes)
                        hazards = hazards_model.model_dump()
                cache[image_key] = hazards
                st.session_state["hazards_json"] = hazards
                st.json(hazards)
            except Exception as exc:
                st.error(f"{text['image_failed']}: {exc}")
        else:
            st.info(text["image_waiting"])
    return hazards


def render_chat_mode(
    profiler: ProfilerAgent,
    planner: PlannerAgent,
    route_provider: MockRouteProvider,
    image_provider: ImageProvider,
) -> None:
    ui_lang = resolve_response_language(
        choice=st.session_state["response_language_choice"],
        user_input="",
        last_language=st.session_state["response_language"],
    )
    text = UI_TEXT[ui_lang]

    st.subheader(text["chat_mode"])
    st.write(text["consent_first"])
    st.session_state["response_language_choice"] = st.selectbox(
        text["assistant_language"],
        options=["Auto", "English", "中文", "Deutsch"],
        index=["Auto", "English", "中文", "Deutsch"].index(st.session_state["response_language_choice"]),
    )

    st.session_state["consent_profile"] = st.checkbox(
        text["consent_profile"], value=st.session_state["consent_profile"]
    )
    st.session_state["consent_image"] = st.checkbox(
        text["consent_image"], value=st.session_state["consent_image"]
    )

    if not st.session_state["consent_profile"]:
        st.info(text["enable_consent"])
        return

    if st.button(text["reset_chat"], key="chat_reset"):
        st.session_state["profile_patch"] = {}
        st.session_state["skipped_domains"] = []
        st.session_state["final_profile"] = None
        st.session_state["chat_history"] = []
        st.session_state["last_question_context"] = None
        st.session_state["response_language"] = "en"
        st.session_state["hazards_json"] = None
        st.session_state["image_hazard_cache"] = {}
        st.rerun()

    if not st.session_state["chat_history"]:
        st.session_state["response_language"] = ui_lang
        opener = text["opener"]
        st.session_state["chat_history"].append({"role": "assistant", "text": opener})
        st.session_state["last_question_context"] = "vision"

    for message in st.session_state["chat_history"]:
        with st.chat_message(message["role"]):
            st.write(message["text"])

    user_input = st.chat_input(text["type_answer"])
    if user_input:
        st.session_state["chat_history"].append({"role": "user", "text": user_input})

        st.session_state["response_language"] = ui_lang

        parsed_short_answer = classify_short_answer(user_input)
        if parsed_short_answer == "skip" and st.session_state["last_question_context"]:
            domain = context_to_domain(st.session_state["last_question_context"])
            if domain not in st.session_state["skipped_domains"]:
                st.session_state["skipped_domains"].append(domain)

        used_mock_fallback = False
        try:
            result = profiler.process_turn(
                user_message=user_input,
                current_patch=st.session_state["profile_patch"],
                skipped_domains=st.session_state["skipped_domains"],
                question_context=st.session_state["last_question_context"],
                response_language=ui_lang,
            )
        except Exception as exc:
            st.error(f"{text['profiler_failed']}: {exc.__class__.__name__}")
            with st.expander(text["details"]):
                st.write(str(exc))
            st.info(text["fallback_mock"])
            used_mock_fallback = True
            fallback_profiler = ProfilerAgent(llm_provider=MockLLMProvider())
            result = fallback_profiler.process_turn(
                user_message=user_input,
                current_patch=st.session_state["profile_patch"],
                skipped_domains=st.session_state["skipped_domains"],
                question_context=st.session_state["last_question_context"],
                response_language=ui_lang,
            )

        st.session_state["profile_patch"] = result.profile_patch.model_dump()
        st.session_state["final_profile"] = profiler.build_profile(
            st.session_state["profile_patch"],
            consent_to_profile=True,
            skipped_domains=st.session_state["skipped_domains"],
        ).model_dump()

        st.session_state["last_question_context"] = result.next_question_context

        response = result.confirmation_text
        if used_mock_fallback:
            response += f"\n\n{text['mock_note']}"
        if result.next_question:
            response += f"\n\n{text['next_prefix']}{result.next_question}"
        else:
            response += f"\n\n{text['done']}"

        st.session_state["chat_history"].append({"role": "assistant", "text": response})
        st.rerun()

    st.divider()
    route_ids = [route.route_id for route in route_provider.list_routes()]
    selected_route = st.selectbox(text["select_route"], options=route_ids, key="chat_route")
    hazards = maybe_image_hazards(image_provider, text, key_prefix="chat_image")

    if st.button(text["generate_plan"], key="chat_generate_plan"):
        if not st.session_state["final_profile"]:
            st.error(text["need_profile_first"])
            return

        try:
            plan = planner.create_plan(
                profile=st.session_state["final_profile"],
                route_id=selected_route,
                image_hazards=hazards,
                response_language=ui_lang,
            )
        except Exception as exc:
            st.error(f"{text['planner_failed']}: {exc.__class__.__name__}")
            with st.expander(text["details"]):
                st.write(str(exc))
            st.info(text["fallback_plan"])
            fallback_llm = MockLLMProvider()
            fallback_planner = PlannerAgent(llm_provider=fallback_llm, route_provider=route_provider)
            plan = fallback_planner.create_plan(
                profile=st.session_state["final_profile"],
                route_id=selected_route,
                image_hazards=hazards,
                response_language=ui_lang,
            )
        st.session_state["plan_json"] = plan.model_dump()
        st.session_state["plan_text"] = planner.format_plan(
            plan,
            language=ui_lang,
        )

    if st.session_state["final_profile"]:
        st.write(text["profile_json"])
        st.json(st.session_state["final_profile"])

    if st.session_state["plan_json"]:
        st.write(text["plan_formatted"])
        st.text(st.session_state["plan_text"])
        st.write(text["plan_json"])
        st.json(st.session_state["plan_json"])


def yes_no_skip(label: str, key: str) -> str:
    return st.selectbox(label, options=["skip", "yes", "no", "是", "否", "有", "没有"], key=key)


def _from_yes_no_skip(value: str) -> bool | None:
    if value in {"yes", "是", "有"}:
        return True
    if value in {"no", "否", "没有"}:
        return False
    return None


def render_stepper_mode(
    profiler: ProfilerAgent,
    planner: PlannerAgent,
    route_provider: MockRouteProvider,
    image_provider: ImageProvider,
) -> None:
    ui_lang = resolve_response_language(
        choice=st.session_state["response_language_choice"],
        user_input="",
        last_language=st.session_state["response_language"],
    )
    text = UI_TEXT[ui_lang]

    st.subheader(text["stepper_mode"])
    st.session_state["response_language_choice"] = st.selectbox(
        text["assistant_language"],
        options=["Auto", "English", "中文", "Deutsch"],
        index=["Auto", "English", "中文", "Deutsch"].index(st.session_state["response_language_choice"]),
        key="stepper_language_choice",
    )
    st.session_state["response_language"] = ui_lang

    steps = text["step_names"]
    step = st.session_state["step_index"]
    st.write(f"{text['step_current']}: {steps[step]}")

    if step == 0:
        st.session_state["consent_profile"] = st.checkbox(
            text["consent_profile"], value=st.session_state["consent_profile"], key="step_consent_profile"
        )
        st.session_state["consent_image"] = st.checkbox(
            text["consent_image"], value=st.session_state["consent_image"], key="step_consent_image"
        )

    elif step == 1:
        if not st.session_state["consent_profile"]:
            st.warning(text["enable_consent"])
        else:
            vision = yes_no_skip(text["step_questions"]["vision"], "step_vision")
            hearing = yes_no_skip(text["step_questions"]["hearing"], "step_hearing")
            sign = yes_no_skip(text["step_questions"]["sign"], "step_sign")
            wheelchair = yes_no_skip(text["step_questions"]["wheelchair"], "step_wheelchair")
            step_free = yes_no_skip(text["step_questions"]["step_free"], "step_step_free")
            simple = yes_no_skip(text["step_questions"]["simple"], "step_simple")
            memory = yes_no_skip(text["step_questions"]["memory"], "step_memory")
            child_or_reading = yes_no_skip(
                text["step_questions"]["child_or_reading"], "step_child_or_reading"
            )

            if st.button(text["save_profile"], key="step_save_profile"):
                patch = {
                    "needs": {
                        "vision": {"blind_or_low_vision": _from_yes_no_skip(vision)},
                        "hearing": {
                            "deaf_or_hard_of_hearing": _from_yes_no_skip(hearing),
                            "sign_language_user": _from_yes_no_skip(sign),
                        },
                        "mobility": {
                            "wheelchair_user": _from_yes_no_skip(wheelchair),
                            "needs_step_free_route": _from_yes_no_skip(step_free),
                            "avoid_long_walks": _from_yes_no_skip(step_free),
                        },
                        "cognitive": {
                            "needs_simple_language": _from_yes_no_skip(simple),
                            "needs_memory_support": _from_yes_no_skip(memory),
                            "reading_or_memory_difficulty_or_child": _from_yes_no_skip(child_or_reading),
                        },
                    },
                }

                sign_value = _from_yes_no_skip(sign)
                simple_value = _from_yes_no_skip(simple)
                child_value = _from_yes_no_skip(child_or_reading)

                if sign_value is True:
                    patch["communication"] = {"output_mode": OutputMode.SIGN_GLOSS_TEXT.value}
                elif simple_value is True or child_value is True:
                    patch["communication"] = {"output_mode": OutputMode.SIMPLE_TEXT.value}
                else:
                    patch["communication"] = {"output_mode": OutputMode.STANDARD_TEXT.value}

                st.session_state["profile_patch"] = patch
                st.session_state["final_profile"] = profiler.build_profile(
                    patch,
                    consent_to_profile=True,
                    skipped_domains=st.session_state["skipped_domains"],
                ).model_dump()
                st.success(text["profile_saved"])

    elif step == 2:
        route_ids = [route.route_id for route in route_provider.list_routes()]
        selected_route = st.selectbox(text["select_route"], options=route_ids, key="step_route")
        hazards = maybe_image_hazards(image_provider, text, key_prefix="step_image")

        if st.button(text["create_plan"], key="step_create_plan"):
            if not st.session_state["final_profile"]:
                st.error(text["create_profile_first"])
            else:
                try:
                    plan = planner.create_plan(
                        profile=st.session_state["final_profile"],
                        route_id=selected_route,
                        image_hazards=hazards,
                        response_language=ui_lang,
                    )
                except Exception as exc:
                    st.error(f"{text['planner_failed']}: {exc.__class__.__name__}")
                    with st.expander(text["details"]):
                        st.write(str(exc))
                    st.info(text["fallback_plan"])
                    fallback_llm = MockLLMProvider()
                    fallback_planner = PlannerAgent(llm_provider=fallback_llm, route_provider=route_provider)
                    plan = fallback_planner.create_plan(
                        profile=st.session_state["final_profile"],
                        route_id=selected_route,
                        image_hazards=hazards,
                        response_language=ui_lang,
                    )
                st.session_state["plan_json"] = plan.model_dump()
                st.session_state["plan_text"] = planner.format_plan(
                    plan,
                    language=ui_lang,
                )
                st.success(text["plan_created"])

    elif step == 3:
        st.write(text["profile_json"])
        st.json(st.session_state.get("final_profile") or {})
        st.write(text["plan_json"])
        st.json(st.session_state.get("plan_json") or {})
        st.write(text["plan_formatted"])
        st.text(st.session_state.get("plan_text") or "")

        if st.session_state.get("final_profile"):
            st.download_button(
                text["download_profile"],
                json.dumps(st.session_state["final_profile"], indent=2),
                file_name="profile.json",
                mime="application/json",
            )

        if st.session_state.get("plan_json"):
            st.download_button(
                text["download_plan"],
                json.dumps(st.session_state["plan_json"], indent=2),
                file_name="personalized_plan.json",
                mime="application/json",
            )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(text["back"], disabled=step == 0, key="step_back"):
            st.session_state["step_index"] = max(0, step - 1)
            st.rerun()
    with col2:
        if st.button(text["next"], disabled=step == len(steps) - 1, key="step_next"):
            st.session_state["step_index"] = min(len(steps) - 1, step + 1)
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="Accessibility Profiling Agent", layout="wide")
    init_state()

    ui_lang = resolve_response_language(
        choice=st.session_state["response_language_choice"],
        user_input="",
        last_language=st.session_state["response_language"],
    )
    text = UI_TEXT[ui_lang]

    st.title(text["title"])
    st.caption(text["caption"])

    st.sidebar.subheader(text["runtime"])
    st.session_state["provider_mode"] = st.sidebar.selectbox(
        text["llm_backend"],
        options=["Mock (offline)", "Ollama (local)"],
        index=["Mock (offline)", "Ollama (local)"].index(st.session_state["provider_mode"]),
    )
    if st.session_state["provider_mode"] == "Ollama (local)":
        st.session_state["ollama_base_url"] = st.sidebar.text_input(
            text["ollama_base_url"],
            value=st.session_state["ollama_base_url"],
        )
        st.session_state["ollama_text_model"] = st.sidebar.text_input(
            text["text_model"],
            value=st.session_state["ollama_text_model"],
        )
        st.session_state["ollama_vision_model"] = st.sidebar.text_input(
            text["vision_model"],
            value=st.session_state["ollama_vision_model"],
        )
        st.session_state["ollama_timeout_sec"] = st.sidebar.number_input(
            text["timeout_sec"],
            min_value=30,
            max_value=900,
            value=int(st.session_state["ollama_timeout_sec"]),
            step=30,
        )
        if st.sidebar.button(text["retry_ollama"], key="retry_ollama_btn"):
            st.session_state["ollama_retry_nonce"] += 1
            st.rerun()
        if st.session_state.get("ollama_status"):
            st.sidebar.caption(st.session_state["ollama_status"])
        models = st.session_state.get("ollama_available_models") or []
        if models:
            preview = ", ".join(models[:8])
            if len(models) > 8:
                preview += ", ..."
            st.sidebar.caption(f"{text['available_models']}: {preview}")
    else:
        st.sidebar.caption(text["mock_caption"])

    profiler, planner, route_provider, image_provider = get_services()

    mode = st.radio(text["ui_mode"], options=[text["chat_only"], text["stepper"]], horizontal=True)

    if mode == text["chat_only"]:
        render_chat_mode(profiler, planner, route_provider, image_provider)
    else:
        render_stepper_mode(profiler, planner, route_provider, image_provider)


if __name__ == "__main__":
    main()
