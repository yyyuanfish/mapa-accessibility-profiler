from __future__ import annotations

import re
from typing import Any

from backend.app.models import (
    AccessibilityProfile,
    ConfidenceScores,
    DomainConfidence,
    OutputMode,
    ProfilePatch,
    ProfilerAgentOutput,
)
from backend.app.providers.llm_provider import LLMProvider
from backend.app.utils.dict_merge import deep_merge_dicts


class ProfilerAgent:
    # Expanded profiler prompt: schema excerpt + few-shot examples + rules.
    # Size is still tiny for llama3.1:8b's 8k context (~700 chars) but gives
    # the model enough structure to map natural-language variants onto the
    # real profile shape. Small enough that Mock and retry paths stay fast.
    SYSTEM_PROMPT = (
        "TASK=PROFILER\n"
        "Extract functional accessibility needs from the user message.\n"
        "Never diagnose medical conditions. Return ONLY JSON with a \"profile_patch\".\n"
        "\n"
        "Schema (only include fields the user mentions):\n"
        "{\"profile_patch\":{\"needs\":{"
        "\"vision\":{\"blind_or_low_vision\":bool,\"prefers_landmarks\":bool},"
        "\"hearing\":{\"deaf_or_hard_of_hearing\":bool,\"sign_language_user\":bool},"
        "\"mobility\":{\"wheelchair_user\":bool,\"needs_step_free_route\":bool,\"avoid_long_walks\":bool},"
        "\"cognitive\":{\"needs_simple_language\":bool,\"needs_memory_support\":bool,"
        "\"reading_or_memory_difficulty_or_child\":bool}},"
        "\"communication\":{\"output_mode\":\"standard_text|simple_text|sign_gloss_text\"}}}\n"
        "\n"
        "Examples:\n"
        "USER \"I am blind\" -> {\"profile_patch\":{\"needs\":{\"vision\":"
        "{\"blind_or_low_vision\":true,\"prefers_landmarks\":true}}}}\n"
        "USER \"eye problem, walk badly, can't read complex text\" -> "
        "{\"profile_patch\":{\"needs\":{"
        "\"vision\":{\"blind_or_low_vision\":true,\"prefers_landmarks\":true},"
        "\"mobility\":{\"wheelchair_user\":true,\"needs_step_free_route\":true},"
        "\"cognitive\":{\"needs_simple_language\":true,\"reading_or_memory_difficulty_or_child\":true}},"
        "\"communication\":{\"output_mode\":\"simple_text\"}}}\n"
        "USER \"I use sign language\" -> {\"profile_patch\":{\"needs\":{\"hearing\":"
        "{\"deaf_or_hard_of_hearing\":true,\"sign_language_user\":true}},"
        "\"communication\":{\"output_mode\":\"sign_gloss_text\"}}}\n"
        "USER \"skip\" -> {\"profile_patch\":{}}\n"
        "\n"
        "Rules:\n"
        "- Output JSON only, no prose.\n"
        "- Omit keys the user did not mention.\n"
        "- \"walk badly\" / \"bad leg\" / \"trouble walking\" imply needs_step_free_route=true.\n"
        "- \"complex text\" / \"difficult words\" imply needs_simple_language=true.\n"
        "- \"eye problem\" / \"vision issue\" / \"eyesight is bad\" imply blind_or_low_vision=true.\n"
        "- \"read lips\" / \"miss announcements\" imply deaf_or_hard_of_hearing=true.\n"
        "- \"prefer signing\" implies sign_language_user=true.\n"
        "- \"ramps or lifts\" / \"cannot cope with steps\" imply needs_step_free_route=true.\n"
        "- \"small chunks\" / \"long paragraphs\" imply needs_simple_language=true; \"lose track\" implies needs_memory_support=true."
    )
    _SUPPORTED_LANGS = {"en", "zh", "de"}
    _QUESTION_TEXTS = {
        "en": {
            "vision": "Do you have any vision-related access needs, such as blind or low-vision support? Please answer yes or no (or skip).",
            "hearing": "Do you have hearing-related needs? Please answer yes or no (or skip).",
            "hearing_sign": "Would you prefer sign-language style text output? Please answer yes or no (or skip).",
            "mobility": "Do you use a wheelchair or need step-free routes? Please answer yes or no (or skip).",
            "mobility_wheelchair": "Do you use a wheelchair? Please answer yes or no (or skip).",
            "mobility_step_free": "Do you need a step-free route (no stairs)? Please answer yes or no (or skip).",
            "cognitive": "Would Simple English, shorter steps, or memory reminders help you? Please answer yes or no (or skip).",
            "cognitive_simple": "Would simple language and shorter sentences help you? Please answer yes or no (or skip).",
            "cognitive_memory": "Would memory reminders along the route help you? Please answer yes or no (or skip).",
        },
        "zh": {
            "vision": "你是否有视觉相关的出行需求（如盲人/低视力支持）？请回答「是」或「否」（也可以跳过）。",
            "hearing": "你是否有听力相关需求？请回答「是」或「否」（也可以跳过）。",
            "hearing_sign": "你是否希望使用手语风格文本输出？请回答「是」或「否」（也可以跳过）。",
            "mobility": "你是否使用轮椅或需要无台阶路线？请回答「是」或「否」（也可以跳过）。",
            "mobility_wheelchair": "你使用轮椅吗？请回答「是」或「否」（也可以跳过）。",
            "mobility_step_free": "你需要无台阶路线（不走楼梯）吗？请回答「是」或「否」（也可以跳过）。",
            "cognitive": "你是否需要简明语言、更短步骤或记忆提醒？请回答「是」或「否」（也可以跳过）。",
            "cognitive_simple": "简明语言与较短句子对你有帮助吗？请回答「是」或「否」（也可以跳过）。",
            "cognitive_memory": "路线中的记忆提醒对你有帮助吗？请回答「是」或「否」（也可以跳过）。",
        },
        "de": {
            "vision": "Haben Sie visuelle Zugangsbedarfe? Bitte antworten Sie mit ja oder nein (oder überspringen).",
            "hearing": "Haben Sie hörbezogene Bedarfe? Bitte antworten Sie mit ja oder nein (oder überspringen).",
            "hearing_sign": "Möchten Sie eine gebärdensprachnahe Textausgabe? Bitte antworten Sie mit ja oder nein (oder überspringen).",
            "mobility": "Nutzen Sie einen Rollstuhl oder benötigen Sie stufenfreie Routen? Bitte antworten Sie mit ja oder nein (oder überspringen).",
            "mobility_wheelchair": "Nutzen Sie einen Rollstuhl? Bitte antworten Sie mit ja oder nein (oder überspringen).",
            "mobility_step_free": "Benötigen Sie eine stufenfreie Route (ohne Treppen)? Bitte antworten Sie mit ja oder nein (oder überspringen).",
            "cognitive": "Würden einfache Sprache, kurze Schritte oder Erinnerungshilfen helfen? Bitte antworten Sie mit ja oder nein (oder überspringen).",
            "cognitive_simple": "Würden einfache Sprache und kürzere Sätze Ihnen helfen? Bitte antworten Sie mit ja oder nein (oder überspringen).",
            "cognitive_memory": "Würden Erinnerungshilfen entlang der Route Ihnen helfen? Bitte antworten Sie mit ja oder nein (oder überspringen).",
        },
    }

    def __init__(
        self,
        llm_provider: LLMProvider,
        needs_extractor: "NeedsExtractor | None" = None,
    ) -> None:
        """Construct a profiler agent.

        ``needs_extractor`` is the Phase 2 NLU subagent. It is optional for
        backward compatibility: existing callers that only passed
        ``llm_provider`` keep working because we lazily build a default
        extractor from the same provider.
        """
        # Local import to avoid a circular dependency at module load: the
        # extractor imports nothing from this module, but future type-checking
        # tools may surface the cycle if imported at top level.
        from backend.app.services.needs_extractor import NeedsExtractor

        self.llm_provider = llm_provider
        self.needs_extractor = needs_extractor or NeedsExtractor(llm_provider)

    def process_turn(
        self,
        user_message: str,
        current_patch: dict[str, Any] | None = None,
        skipped_domains: list[str] | None = None,
        question_context: str | None = None,
        response_language: str = "en",
        turn_count: int = 1,
    ) -> ProfilerAgentOutput:
        language = self._normalize_language(response_language)
        skipped = set(skipped_domains or [])
        current = ProfilePatch.model_validate(current_patch or {})

        # Handle the "confirm" question context: the user was asked to confirm
        # the profile. If they say yes, finalize. If no/skip, re-triage.
        short_answer = self._classify_short_answer(user_message)
        if question_context == "confirm":
            confidence = self._compute_confidence(current, skipped)
            confirmation_text = self._confirmation_text(current, language)
            if short_answer == "yes":
                return ProfilerAgentOutput(
                    profile_patch=current,
                    confidence=confidence,
                    missing_critical_fields=[],
                    next_question=None,
                    next_question_context=None,
                    confirmation_text=confirmation_text,
                )
            if short_answer in {"no", "skip"}:
                return ProfilerAgentOutput(
                    profile_patch=current,
                    confidence=confidence,
                    missing_critical_fields=self._missing_critical_fields(current, skipped),
                    next_question=self._triage_prompt(language),
                    next_question_context="triage",
                    confirmation_text=confirmation_text,
                )
            # If not a clear yes/no, fall through to re-extract.
            question_context = None

        # NLU: LLM + lexicon scan, delegated to the subagent. Use
        # ``extract_with_confidence`` to get domain-level confidence hints
        # (lexicon vs LLM source) that feed into ``_compute_confidence``.
        extraction = self.needs_extractor.extract_with_confidence(
            user_message=user_message,
            current_patch=current,
            question_context=question_context,
        )
        # Dialogue: context-specific yes/no overlay (e.g. plain "yes" to the
        # current question fills in that domain). Runs AFTER extraction so an
        # explicit focused answer wins over free-text signal.
        context_patch_dict = self._context_yes_no_overlay(user_message, question_context)

        merged_dict = deep_merge_dicts(current.model_dump(), extraction.patch)
        merged_dict = deep_merge_dicts(merged_dict, context_patch_dict)
        merged_dict = self._enforce_output_mode_rules(merged_dict)
        merged_patch = ProfilePatch.model_validate(merged_dict)

        confidence = self._compute_confidence(
            merged_patch, skipped, domain_hints=extraction.domain_confidence_hints,
        )
        missing = self._missing_critical_fields(merged_patch, skipped)
        next_question, next_question_context = self._next_question(merged_patch, skipped, language)
        confirmation_text = self._confirmation_text(merged_patch, language)

        if question_context in {None, "triage"} and turn_count <= 1 and self._is_empty_patch(merged_patch):
            generic_context = self._generic_first_turn_context(user_message)
            if generic_context is not None:
                return ProfilerAgentOutput(
                    profile_patch=merged_patch,
                    confidence=confidence,
                    missing_critical_fields=missing,
                    next_question=self._question(generic_context, language),
                    next_question_context=generic_context,
                    confirmation_text=confirmation_text,
                )
            return ProfilerAgentOutput(
                profile_patch=merged_patch,
                confidence=confidence,
                missing_critical_fields=missing,
                next_question=self._triage_prompt(language),
                next_question_context="triage",
                confirmation_text=confirmation_text,
            )

        if next_question is None:
            next_question_context = "confirm"

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

    # NOTE: ``_request_patch`` (LLM call + JSON validation) used to live here
    # but has moved to ``NeedsExtractor._request_llm_patch`` in Phase 2. The
    # profiler no longer owns any LLM prompt — it delegates to the extractor
    # subagent.

    def _missing_critical_fields(self, patch: ProfilePatch, skipped_domains: set[str]) -> list[str]:
        """Return only ROUTE-CRITICAL fields that still need an answer.

        Per the expert review, "critical" here is narrowed to fields that
        directly affect route selection or output form: step-free routing,
        sign-language preference (→ output mode), and simple-language preference
        (→ output mode). Vision/hearing/memory domains are NOT required for a
        usable plan — we can generate a standard route without them and still
        have a respectful, correct experience.
        """
        missing: list[str] = []

        # Step-free routing — directly affects the returned route.
        if (
            "mobility" not in skipped_domains
            and patch.needs.mobility.needs_step_free_route is None
        ):
            missing.append("needs.mobility.needs_step_free_route")

        # Sign-language user → gates sign_gloss_text output mode, but only ask
        # when we already know hearing support is needed.
        if (
            "hearing" not in skipped_domains
            and patch.needs.hearing.deaf_or_hard_of_hearing is True
            and patch.needs.hearing.sign_language_user is None
        ):
            missing.append("needs.hearing.sign_language_user")

        # Simple-language preference → gates simple_text output mode, but only
        # ask when the user already hinted at cognitive needs.
        if (
            "cognitive" not in skipped_domains
            and patch.needs.cognitive.reading_or_memory_difficulty_or_child is True
            and patch.needs.cognitive.needs_simple_language is None
        ):
            missing.append("needs.cognitive.needs_simple_language")

        return missing

    @staticmethod
    def _domain_known(values: list[bool | None]) -> int:
        return sum(1 for value in values if value is not None)

    def _compute_confidence(
        self,
        patch: ProfilePatch,
        skipped_domains: set[str],
        domain_hints: dict[str, float] | None = None,
    ) -> ConfidenceScores:
        """Compute per-domain and overall confidence.

        ``domain_hints`` (optional, Phase 3) is a dict mapping domain names to
        source-confidence floats produced by ``NeedsExtractor``:

        - 0.9 → lexicon **and** LLM both populated the domain.
        - 0.8 → deterministic lexicon match only.
        - 0.5 → LLM inference only.

        When hints are available, a domain's score is the product of the
        field-coverage ratio and the source-confidence hint. This means a
        lexicon-confirmed domain with all fields known scores 0.9, while an
        LLM-only domain with partial fields might score 0.25.

        When ``domain_hints`` is ``None`` (backward compat with callers that
        still call ``extract`` instead of ``extract_with_confidence``), the
        score falls back to the original field-count ratio.
        """
        hints = domain_hints or {}
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
            coverage = known / total
            # When we have a source-confidence hint, multiply coverage by
            # the hint so a lexicon-backed domain scores higher than an
            # LLM-only domain with the same field coverage.
            source_confidence = hints.get(domain)
            if source_confidence is not None and known > 0:
                return round(coverage * source_confidence, 2)
            return round(coverage, 2)

        per_domain = DomainConfidence(
            vision=score(vision_known, vision_total, "vision"),
            hearing=score(hearing_known, hearing_total, "hearing"),
            mobility=score(mobility_known, mobility_total, "mobility"),
            cognitive=score(cognitive_known, cognitive_total, "cognitive"),
        )
        known_domain_scores = [
            value
            for value, known in [
                (per_domain.vision, vision_known),
                (per_domain.hearing, hearing_known),
                (per_domain.mobility, mobility_known),
                (per_domain.cognitive, cognitive_known),
            ]
            if known > 0
        ]
        overall = (
            round(sum(known_domain_scores) / len(known_domain_scores), 2)
            if known_domain_scores
            else 0.0
        )
        return ConfidenceScores(overall=overall, per_domain=per_domain)

    def _next_question(
        self,
        patch: ProfilePatch,
        skipped_domains: set[str],
        language: str,
    ) -> tuple[str | None, str | None]:
        """Adaptive next-question policy (expert-reviewed).

        Only follow up on branches the user has HIT (i.e. signalled a positive
        need for). We do NOT walk every domain top-to-bottom — that wastes the
        user's time and creates false positives when the triage turn already
        cleared a domain.

        Priority order is route-critical first:
          1. step-free routing  (directly gates the chosen route)
          2. sign-language      (gates sign_gloss_text output mode)
          3. simple-language    (gates simple_text output mode)
          4. memory reminders   (affects plan content only, not the route)
        """
        m = patch.needs.mobility
        h = patch.needs.hearing
        c = patch.needs.cognitive

        # 1. If mobility has been flagged but step-free is still unknown → ask.
        mobility_hit = m.wheelchair_user is True or m.avoid_long_walks is True
        if (
            "mobility" not in skipped_domains
            and mobility_hit
            and m.needs_step_free_route is None
        ):
            return self._question("mobility_step_free", language), "mobility_step_free"

        if (
            "mobility" not in skipped_domains
            and (m.needs_step_free_route is True or m.avoid_long_walks is True)
            and m.wheelchair_user is None
        ):
            return self._question("mobility_wheelchair", language), "mobility_wheelchair"

        # 2. Hearing → sign-language follow-up only if hearing was flagged.
        if (
            "hearing" not in skipped_domains
            and h.deaf_or_hard_of_hearing is True
            and h.sign_language_user is None
        ):
            return self._question("hearing_sign", language), "hearing_sign"

        # 3. Cognitive → simple-language only if cognitive was flagged.
        cognitive_hit = (
            c.needs_memory_support is True or c.reading_or_memory_difficulty_or_child is True
        )
        if (
            "cognitive" not in skipped_domains
            and c.reading_or_memory_difficulty_or_child is True
            and c.needs_simple_language is None
            and c.needs_memory_support is not True
        ):
            return self._question("cognitive_simple", language), "cognitive_simple"

        # 4. Memory reminders follow-up (lower priority — doesn't change route).
        if (
            "cognitive" not in skipped_domains
            and c.needs_simple_language is True
            and c.needs_memory_support is None
        ):
            return self._question("cognitive_memory", language), "cognitive_memory"

        # Nothing hit and nothing outstanding → stop. Route-critical view:
        # we do NOT keep probing cold domains the user never mentioned.
        return None, None

    # Concise diff-style recap — list only what the user positively indicated.
    # Walking every domain ("no blind support, no hearing support, …") is
    # disrespectful and slow; users skip over long recaps anyway.
    _RECAP_TEMPLATES: dict[str, dict[str, str]] = {
        "en": {
            "prefix": "Here is what I understood:",
            "suffix": "Please confirm this before I plan your route.",
            "empty": "No specific accessibility preferences noted. I'll use a standard route.",
            "wheelchair": "wheelchair user",
            "step_free": "step-free routing",
            "vision": "vision support",
            "hearing": "hearing support",
            "sign": "sign-language style output",
            "simple": "simple language",
            "memory": "memory reminders",
        },
        "zh": {
            "prefix": "好的——我了解到的是：",
            "suffix": "请先确认这些信息，我再为你规划路线。",
            "empty": "未记录特定无障碍偏好。我将使用标准路线。",
            "wheelchair": "使用轮椅",
            "step_free": "无台阶路线",
            "vision": "视觉支持",
            "hearing": "听力支持",
            "sign": "手语风格输出",
            "simple": "简明语言",
            "memory": "记忆提醒",
        },
        "de": {
            "prefix": "Verstanden — das habe ich notiert:",
            "suffix": "Bitte bestätigen Sie dies, bevor ich Ihre Route plane.",
            "empty": "Keine speziellen Barrierefreiheits-Präferenzen notiert. Ich verwende eine Standardroute.",
            "wheelchair": "Rollstuhl",
            "step_free": "stufenfreie Route",
            "vision": "Seh-Unterstützung",
            "hearing": "Hör-Unterstützung",
            "sign": "gebärdensprachnahe Ausgabe",
            "simple": "einfache Sprache",
            "memory": "Erinnerungshilfen",
        },
    }

    def _confirmation_text(self, patch: ProfilePatch, language: str) -> str:
        lang = language if language in self._RECAP_TEMPLATES else "en"
        tmpl = self._RECAP_TEMPLATES[lang]

        parts: list[str] = []
        if patch.needs.mobility.wheelchair_user is True:
            parts.append(tmpl["wheelchair"])
        if patch.needs.mobility.needs_step_free_route is True:
            parts.append(tmpl["step_free"])
        if patch.needs.vision.blind_or_low_vision is True:
            parts.append(tmpl["vision"])
        if patch.needs.hearing.deaf_or_hard_of_hearing is True:
            parts.append(tmpl["hearing"])
        if patch.needs.hearing.sign_language_user is True:
            parts.append(tmpl["sign"])
        if patch.needs.cognitive.needs_simple_language is True:
            parts.append(tmpl["simple"])
        if patch.needs.cognitive.needs_memory_support is True:
            parts.append(tmpl["memory"])

        if not parts:
            return tmpl["empty"]

        joiner = "、" if lang == "zh" else ", "
        return f"{tmpl['prefix']} {joiner.join(parts)}. {tmpl['suffix']}"

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

    def _triage_prompt(self, language: str) -> str:
        lang = self._normalize_language(language)
        prompts = {
            "en": (
                "To personalize routes quickly, tell me which apply -- you can list several at once, "
                "or say 'none' or 'skip': vision / screen reader; hearing / captions / sign language; "
                "step-free route / wheelchair; simple language / reminders."
            ),
            "zh": (
                "为了更快个性化路线，请告诉我哪些适用——可以一次说多个，"
                "或回答'都不需要'/'跳过'："
                "视觉 / 屏幕阅读；听力 / 字幕 / 手语；无台阶路线 / 轮椅；简明语言 / 提醒。"
            ),
            "de": (
                "Um Routen schnell zu personalisieren, sagen Sie mir, was zutrifft -- Sie koennen mehreres "
                "auf einmal nennen oder 'nichts' / 'ueberspringen' sagen: Sehen / Bildschirmleser; "
                "Hoeren / Untertitel / Gebaerdensprache; stufenfreie Route / Rollstuhl; einfache Sprache / Erinnerungen."
            ),
        }
        return prompts.get(lang, prompts["en"])

    @staticmethod
    def _generic_first_turn_context(user_message: str) -> str | None:
        lowered = user_message.lower()
        if re.search(
            r"\bmobility\b|leg.?problem|legs|walking.?difficult|difficulty.?walking|行动|出行|腿|走路|mobilit|bein|gehproblem|laufen",
            lowered,
        ):
            return "mobility_step_free"
        if re.search(r"\bhearing\b|听力|hör|hoer", lowered):
            return "hearing_sign"
        if re.search(r"\bvision\b|视觉|seh", lowered):
            return "vision"
        if re.search(r"\bcognitive\b|memory support|simple language|认知|记忆|einfache sprache", lowered):
            return "cognitive_simple"
        return None

    def _context_yes_no_overlay(
        self, user_message: str, question_context: str | None
    ) -> dict[str, Any]:
        """Return the patch implied by a plain yes/no/skip to the focused question.

        This is the *overlay* that runs on top of ``NeedsExtractor.extract``:
        when the user types a recognizable yes/no to the current question, we
        set every field that question is supposed to populate. Returns ``{}``
        when no focused question is active or the message isn't a clean yes/no.
        """
        if not question_context:
            return {}
        answer = self._classify_short_answer(user_message)
        if answer not in {"yes", "no"}:
            return {}
        return self._context_yes_no_patch(question_context, answer == "yes")

    @staticmethod
    def _context_yes_no_patch(question_context: str, yes: bool) -> dict[str, Any]:
        """Build the patch that corresponds to a plain yes/no on the focused question."""
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

        # "mobility" (legacy / triage-level) still sets both flags because the
        # question is intentionally broad. For finer grain, callers should send
        # either "mobility_wheelchair" or "mobility_step_free".
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

        if question_context == "mobility_wheelchair":
            # Wheelchair implies step-free; the inverse is NOT true.
            if yes:
                return {
                    "needs": {
                        "mobility": {
                            "wheelchair_user": True,
                            "needs_step_free_route": True,
                        }
                    }
                }
            return {"needs": {"mobility": {"wheelchair_user": False}}}

        if question_context == "mobility_step_free":
            return {
                "needs": {
                    "mobility": {
                        "needs_step_free_route": yes,
                    }
                }
            }

        # "cognitive" (legacy / triage-level) remains coupled. Prefer the
        # split contexts below for individual follow-ups.
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

        if question_context == "cognitive_simple":
            if yes:
                return {
                    "needs": {
                        "cognitive": {
                            "needs_simple_language": True,
                            "reading_or_memory_difficulty_or_child": True,
                        }
                    },
                    "communication": {"output_mode": OutputMode.SIMPLE_TEXT.value},
                }
            return {"needs": {"cognitive": {"needs_simple_language": False}}}

        if question_context == "cognitive_memory":
            if yes:
                return {
                    "needs": {
                        "cognitive": {
                            "needs_memory_support": True,
                            "reading_or_memory_difficulty_or_child": True,
                        }
                    }
                }
            return {"needs": {"cognitive": {"needs_memory_support": False}}}

        return {}

    @staticmethod
    def _classify_short_answer(user_message: str) -> str | None:
        """Classify the user's message as ``yes``/``no``/``skip``/``None``.

        Two-layer logic:

        1. **Lead-token match.** Find the first alphanumeric / CJK token and
           check it against the yes/no/skip sets. This catches replies that
           start with a short affirmation followed by free text, e.g.
           ``"yes I have eye problem, ..."`` which the previous exact-match
           rule missed.
        2. **Compact exact-match fallback.** Kept verbatim so short multi-word
           phrases like ``"n a"`` (becomes ``"na"``) still classify as skip.
        """
        raw = user_message.strip().lower()
        if not raw:
            return None

        skip_tokens = {
            "skip", "pass", "none", "na", "n/a",
            "跳过", "略过", "先跳过",
            "überspringen", "skippen", "keineangabe",
        }
        yes_tokens = {
            "yes", "y", "yeah", "yep", "sure", "ok", "okay", "ja",
            "有", "是", "对", "好", "可以", "需要", "需要的",
        }
        no_tokens = {
            "no", "n", "nope", "nein",
            "否", "没有", "不用", "不需要", "不是", "不",
            "kein", "nicht",
        }

        # (1) Lead-token: grab the first run of letters/digits/CJK characters.
        lead_match = re.match(
            r"[\s\.,!?;:，。！？；：\-_]*([\w\u4e00-\u9fff]+)",
            raw,
        )
        if lead_match:
            lead = lead_match.group(1)
            if lead in skip_tokens:
                return "skip"
            if lead in yes_tokens:
                return "yes"
            if lead in no_tokens:
                return "no"

        # (2) Compact exact-match fallback (original behavior).
        compact = re.sub(r"[\s\.,!?;:，。！？；：\-_]+", "", raw)
        if not compact:
            return None
        if compact in skip_tokens:
            return "skip"
        if compact in yes_tokens:
            return "yes"
        if compact in no_tokens:
            return "no"
        return None

    @staticmethod
    def _is_empty_patch(patch: ProfilePatch) -> bool:
        return not patch.model_dump(exclude_none=True, exclude_defaults=True)

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
        # Thin wrapper kept for backward compatibility with existing call sites.
        # The real implementation lives in ``backend.app.utils.dict_merge`` so
        # taxonomy, needs extractor, and orchestrator can share it without
        # importing from this module.
        return deep_merge_dicts(base, incoming)
