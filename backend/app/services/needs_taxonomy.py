"""Shared accessibility-needs lexicon and free-text extractor.

This module is the single source of truth for the natural-language -> profile
mapping. It is used by:

- ``MockLLMProvider._complete_profiler`` for offline deterministic behavior.
- ``NeedsExtractor`` (Phase 2) as the keyword-fallback layer that runs alongside
  the LLM.
- ``ProfilerAgent._contextual_patch`` for in-turn multi-domain scans.

Design choices:
- Pure Python, no network, no extra dependencies — aligns with the offline-first
  philosophy documented in ``README.md``.
- Tri-lingual (EN + ZH + DE) from day one to match the existing multilingual UI.
- Offline fuzziness = text normalization (hyphen/apostrophe/whitespace variants).
  No embeddings, no Levenshtein library. If recall gaps show up in the eval
  harness, add ``difflib.SequenceMatcher`` (stdlib) as a second pass.
"""

from __future__ import annotations

import re
from typing import Any

from backend.app.models import OutputMode
from backend.app.utils.dict_merge import deep_merge_dicts


# ---------------------------------------------------------------------------
# Lexicon
# ---------------------------------------------------------------------------
#
# Each key is a *lexicon label* (not a schema field) that ``extract_all_domains``
# knows how to map onto the real ``profile_patch`` structure. Keep labels
# stable because they appear in tests.
#
# Keep negatives listed before positives mentally: ``detect_bool`` checks
# negatives first so "no vision needs" wins over "vision" appearing as a
# substring of "television" or similar.

# Blanket "no needs" phrases — if the user says something like "no special
# needs" or "standard is fine", all domains should be set to False.
_BLANKET_NO_NEEDS: list[str] = [
    # EN
    "no special needs", "no accessibility needs", "nothing special",
    "all good", "standard is fine", "no needs",
    # ZH
    "都不需要", "没有特殊需求", "不需要任何帮助",
    # DE
    "keine besonderen bedarfe", "alles gut", "standard ist okay",
]

NEEDS_LEXICON: dict[str, dict[str, list[str]]] = {
    "vision": {
        "positive": [
            # EN
            "blind", "low vision", "low-vision", "screen reader",
            "cannot see", "can't see", "can not see",
            "eye problem", "eye problems", "eye issue", "eye issues",
            "eye trouble", "vision issue", "vision problem",
            "trouble seeing", "hard to see", "poor eyesight", "bad eyesight",
            "bad eyes", "visual impairment", "visually impaired", "sight loss",
            # ZH
            "眼睛有问题", "眼睛不好", "看不清", "看不见", "视力差", "视力不好",
            "视障", "失明", "盲人", "低视力",
            # DE
            "sehbehinderung", "sehbehindert", "blind", "augenproblem",
            "augenprobleme", "sehe schlecht", "schlechte augen", "sehschwäche",
        ],
        "negative": [
            "no vision support", "no vision needs", "not blind",
            "sight is fine", "eyes are fine", "vision is fine",
            "视力没问题", "眼睛没问题", "不是盲人",
            "keine sehprobleme", "sehe gut",
        ],
    },
    "hearing": {
        "positive": [
            # EN
            "deaf", "hard of hearing", "hoh", "hearing loss",
            "cannot hear", "can't hear", "can not hear",
            "hearing issue", "hearing issues", "hearing problem",
            "ear problem", "ear problems", "bad hearing",
            # ZH
            "听力不好", "听力问题", "听不清", "听不见", "听障", "聋",
            "耳朵有问题",
            # DE
            "gehörlos", "schwerhörig", "taub", "höre schlecht",
            "hörproblem", "hörprobleme", "hörbehinderung",
        ],
        "negative": [
            "not deaf", "no hearing needs", "hearing is fine",
            "听力没问题", "耳朵没问题",
            "höre gut", "keine hörprobleme",
        ],
    },
    "sign_language": {
        "positive": [
            # EN
            "sign language", "asl", "bsl", "signed", "sign user",
            "use sign", "uses sign",
            # ZH
            "手语", "使用手语", "用手语",
            # DE
            "gebärdensprache", "gebärde", "nutze gebärdensprache",
        ],
        "negative": [
            "no sign language", "do not sign", "don't sign",
            "不用手语", "不需要手语",
            "keine gebärdensprache",
        ],
    },
    "wheelchair": {
        "positive": [
            # EN
            "wheelchair", "wheel chair", "powerchair", "power chair",
            "i am in a wheelchair", "use a wheelchair", "wheelchair user",
            # ZH
            "轮椅", "使用轮椅", "坐轮椅",
            # DE
            "rollstuhl", "im rollstuhl", "rollstuhlfahrer",
        ],
        "negative": [
            "no mobility support", "not a wheelchair user",
            "no wheelchair", "no wheelchair needs",
            "without wheelchair support",
            "不用轮椅", "不需要轮椅",
            "kein rollstuhl",
        ],
    },
    "step_free": {
        "positive": [
            # EN — explicit step-free phrasing
            "step free", "step-free", "stepfree",
            "avoid stairs", "no stairs", "without stairs",
            "cannot climb stairs", "can't climb stairs", "can not climb stairs",
            "trouble with stairs", "stairs are hard",
            # EN — "walking is hard" style, implies step-free help
            "walk badly", "walks badly", "walk slowly", "walks slowly",
            "walking difficulty", "walking difficulties", "hard to walk",
            "trouble walking", "difficulty walking", "limp", "limping",
            "bad leg", "bad legs", "bad knee", "bad knees",
            "mobility issue", "mobility issues", "mobility problem",
            "walker",  # mobility aid, not the tool
            # ZH
            "走路不好", "走路慢", "走路困难", "腿脚不便", "腿不好",
            "爬楼梯困难", "上不了楼梯", "避免台阶", "无台阶",
            # DE
            "stufenfrei", "ohne stufen", "treppen vermeiden",
            "gehe schlecht", "laufe schlecht", "gehbehinderung",
            "schlechtes bein", "schlechte beine",
        ],
        "negative": [
            "stairs are fine", "i can walk fine", "walking is fine",
            "steps are okay",
            "走路没问题", "台阶没问题",
            "treppen sind kein problem", "laufe gut",
        ],
    },
    "cognitive_simple": {
        "positive": [
            # EN
            "simple english", "easy words", "short sentences",
            "simple language", "plain language", "plain english",
            "complex text", "complicated text", "difficult words",
            "long words", "hard to read", "reading difficulty",
            "reading difficulties", "confusing", "confuses me",
            "can't read complex", "cannot read complex",
            "can't understand complex", "cannot understand complex",
            "child", "kid", "for a child",
            # ZH
            "简明语言", "简单语言", "简单英文", "读不懂", "读不懂复杂文字",
            "复杂文字", "复杂文本", "看不懂", "文字太难", "字太难",
            # DE
            "einfache sprache", "leichte sprache",
            "komplexe texte", "schwierige wörter", "schwieriger text",
            "kann nicht lesen", "nicht verstehen komplexe",
        ],
        "negative": [
            "standard language is fine", "no simple language",
            "complex language is fine",
            "不需要简明语言", "标准语言可以",
            "standardsprache ist okay",
        ],
    },
    "cognitive_memory": {
        "positive": [
            # EN
            "memory", "reminders", "remind me", "i forget", "i forgot",
            "memory difficulty", "memory support", "memory reminders",
            "forgetful",
            # ZH
            "记忆", "提醒", "记忆提醒", "容易忘", "我会忘", "记不住",
            # DE
            "gedächtnis", "erinnerung", "erinnerungen", "vergesse",
            "gedächtnisstütze", "gedächtnisprobleme",
        ],
        "negative": [
            "no memory issues", "memory is fine", "no reminders needed",
            "记忆没问题", "不需要提醒",
            "keine gedächtnisprobleme",
        ],
    },
}


# ---------------------------------------------------------------------------
# Normalization & matching
# ---------------------------------------------------------------------------

# Unifies "can't" / "cant" / "can not" / "cannot" so the lexicon only has to
# list one form. Same for hyphen/space in "low-vision" / "low vision".
_APOSTROPHE_VARIANTS = {"’": "'", "‘": "'"}
_CANNOT_PATTERNS = [
    (re.compile(r"\bcan\s*not\b", re.IGNORECASE), "cannot"),
    (re.compile(r"\bcan\s*['’]?\s*t\b", re.IGNORECASE), "cannot"),
    (re.compile(r"\bdo\s*not\b", re.IGNORECASE), "do not"),
    (re.compile(r"\bdon\s*['’]?\s*t\b", re.IGNORECASE), "do not"),
]
_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, unify apostrophe/contraction variants, collapse whitespace.

    Keeps hyphens (``low-vision`` stays distinct but we also normalize to the
    spaced form for matching). CJK characters pass through untouched.
    """
    if not text:
        return ""
    lowered = text.lower()
    for src, dst in _APOSTROPHE_VARIANTS.items():
        lowered = lowered.replace(src, dst)
    for pattern, replacement in _CANNOT_PATTERNS:
        lowered = pattern.sub(replacement, lowered)
    # Also build a spaced-hyphen view so both "low-vision" and "low vision" match.
    lowered = _WHITESPACE_RE.sub(" ", lowered).strip()
    return lowered


def _match_variants(text: str, phrase: str) -> bool:
    """Return True if ``phrase`` appears in ``text`` under hyphen/space variants."""
    if phrase in text:
        return True
    # Try hyphen <-> space swap both ways.
    swap_hyphen = phrase.replace("-", " ")
    if swap_hyphen != phrase and swap_hyphen in text:
        return True
    swap_space = phrase.replace(" ", "-")
    if swap_space != phrase and swap_space in text:
        return True
    return False


def any_phrase_in(text: str, phrases: list[str]) -> bool:
    """Normalized, variant-tolerant substring match."""
    if not text or not phrases:
        return False
    normalized_text = normalize(text)
    for phrase in phrases:
        normalized_phrase = normalize(phrase)
        if _match_variants(normalized_text, normalized_phrase):
            return True
    return False


def detect_bool(text: str, key: str) -> bool | None:
    """Return True/False/None for a single lexicon key.

    Negatives are checked first so explicit denials win over incidental
    positive substrings.
    """
    entry = NEEDS_LEXICON.get(key)
    if not entry:
        return None
    if any_phrase_in(text, entry.get("negative", [])):
        return False
    if any_phrase_in(text, entry.get("positive", [])):
        return True
    return None


# ---------------------------------------------------------------------------
# Full-patch extraction
# ---------------------------------------------------------------------------


def extract_all_domains(text: str) -> dict[str, Any]:
    """Scan ``text`` for every domain and return a full ``profile_patch`` dict.

    Returns ``{}`` when no signal is found. The shape matches
    ``ProfilePatch.model_dump(exclude_none=True)`` so the result can be
    deep-merged with other patches.

    Secondary inferences mirror the existing ``ProfilerAgent._contextual_patch``
    rules (e.g., wheelchair implies step-free + avoid long walks, simple
    language implies ``output_mode=simple_text``).
    """
    # Check for blanket "no needs" phrases first. If present, set all
    # primary fields to False so the caller can skip all follow-up questions.
    if any_phrase_in(text, _BLANKET_NO_NEEDS):
        return {
            "needs": {
                "vision": {"blind_or_low_vision": False, "prefers_landmarks": False},
                "hearing": {"deaf_or_hard_of_hearing": False, "sign_language_user": False},
                "mobility": {
                    "wheelchair_user": False,
                    "needs_step_free_route": False,
                    "avoid_long_walks": False,
                },
                "cognitive": {
                    "needs_simple_language": False,
                    "needs_memory_support": False,
                    "reading_or_memory_difficulty_or_child": False,
                },
            },
            "communication": {"output_mode": OutputMode.STANDARD_TEXT.value},
        }

    needs: dict[str, Any] = {}
    communication: dict[str, Any] = {}

    vision = detect_bool(text, "vision")
    if vision is not None:
        needs.setdefault("vision", {})["blind_or_low_vision"] = vision
        if vision:
            needs["vision"]["prefers_landmarks"] = True

    hearing = detect_bool(text, "hearing")
    if hearing is not None:
        needs.setdefault("hearing", {})["deaf_or_hard_of_hearing"] = hearing

    sign = detect_bool(text, "sign_language")
    if sign is not None:
        needs.setdefault("hearing", {})["sign_language_user"] = sign
        if sign:
            # A sign-language user is implicitly Deaf/HoH unless explicitly denied.
            needs["hearing"].setdefault("deaf_or_hard_of_hearing", True)
            communication["output_mode"] = OutputMode.SIGN_GLOSS_TEXT.value

    wheelchair = detect_bool(text, "wheelchair")
    if wheelchair is not None:
        needs.setdefault("mobility", {})["wheelchair_user"] = wheelchair
        if wheelchair:
            needs["mobility"]["needs_step_free_route"] = True
            needs["mobility"]["avoid_long_walks"] = True

    step_free = detect_bool(text, "step_free")
    if step_free is not None:
        mobility = needs.setdefault("mobility", {})
        # Positive step-free never downgrades an existing True. Negative only
        # downgrades when the user hasn't already been set as a wheelchair user.
        if step_free:
            mobility["needs_step_free_route"] = True
        elif not mobility.get("wheelchair_user"):
            mobility["needs_step_free_route"] = False

    simple = detect_bool(text, "cognitive_simple")
    if simple is not None:
        needs.setdefault("cognitive", {})["needs_simple_language"] = simple
        if simple:
            needs["cognitive"]["reading_or_memory_difficulty_or_child"] = True
            communication.setdefault("output_mode", OutputMode.SIMPLE_TEXT.value)

    memory = detect_bool(text, "cognitive_memory")
    if memory is not None:
        needs.setdefault("cognitive", {})["needs_memory_support"] = memory
        if memory:
            needs["cognitive"]["reading_or_memory_difficulty_or_child"] = True
            communication.setdefault("output_mode", OutputMode.SIMPLE_TEXT.value)

    patch: dict[str, Any] = {}
    if needs:
        patch["needs"] = needs
    if communication:
        patch["communication"] = communication
    return patch


def merge_patches(*patches: dict[str, Any]) -> dict[str, Any]:
    """Convenience: deep-merge multiple patches left to right."""
    result: dict[str, Any] = {}
    for patch in patches:
        if patch:
            result = deep_merge_dicts(result, patch)
    return result
