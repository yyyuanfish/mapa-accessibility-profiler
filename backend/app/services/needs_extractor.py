"""NeedsExtractor subagent: pure NLU, free text -> ProfilePatch dict.

Responsibilities:
- Own the profiler LLM system prompt (schema + few-shot examples + rules).
- Call the LLM (Ollama or Mock) with ``user_message`` + ``current_patch`` +
  optional ``question_context`` as a JSON payload.
- Parse + validate the response as ``ProfilerLLMResponse``; retry once if the
  first completion isn't valid JSON.
- Merge the LLM patch with a domain-agnostic lexicon scan from
  ``needs_taxonomy`` so unambiguous synonym hits reinforce weak LLM signal.

Non-goals (on purpose):
- No dialogue state, no next-question logic, no confidence math. Those live in
  ``ProfilerAgent`` / ``Orchestrator``.
- No language localization. The LLM can reply in any language for the JSON
  payload; localization is for confirmation text, which belongs to
  ``ProfilerAgent``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from backend.app.models import ProfilePatch, ProfilerLLMResponse
from backend.app.providers.llm_provider import LLMProvider
from backend.app.services import needs_taxonomy
from backend.app.utils.dict_merge import deep_merge_dicts
from backend.app.utils.json_extract import JSONExtractionError, extract_first_json

# Confidence levels by signal source.
_CONFIDENCE_BOTH = 0.9  # lexicon + LLM agree
_CONFIDENCE_LEXICON = 0.8  # deterministic lexicon match only
_CONFIDENCE_LLM = 0.5  # LLM inference only, no lexicon confirmation


@dataclass
class ExtractionResult:
    """Bundle returned by ``extract_with_confidence``.

    ``patch`` is the merged profile_patch dict (same as ``extract`` returns).
    ``domain_confidence_hints`` maps domain names (``"vision"``, ``"hearing"``,
    ``"mobility"``, ``"cognitive"``) to a float in [0, 1] indicating how
    confident the extraction is for that domain, based on the signal source:

    - 0.9 — both LLM and lexicon agree on at least one field.
    - 0.8 — deterministic lexicon match (high reliability).
    - 0.5 — LLM inference only (no lexicon confirmation).

    Domains not mentioned at all are omitted from the dict.
    """

    patch: dict[str, Any] = field(default_factory=dict)
    domain_confidence_hints: dict[str, float] = field(default_factory=dict)


class NeedsExtractor:
    # Same prompt as ``ProfilerAgent.SYSTEM_PROMPT``. We deliberately duplicate
    # the string here (instead of importing it) so the extractor is a fully
    # standalone subagent — deletions in profiler_agent.py should not silently
    # break extraction. If prompt drift becomes a concern, centralize in a
    # prompts module later.
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
        "\"mobility\":{\"wheelchair_user\":true,\"needs_step_free_route\":true,\"avoid_long_walks\":true},"
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
        "- \"eye problem\" / \"vision issue\" imply blind_or_low_vision=true."
    )

    def __init__(self, llm_provider: LLMProvider) -> None:
        self.llm_provider = llm_provider

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(
        self,
        user_message: str,
        current_patch: ProfilePatch | None = None,
        question_context: str | None = None,
    ) -> dict[str, Any]:
        """Return a ``profile_patch`` dict derived from ``user_message``.

        Convenience wrapper around ``extract_with_confidence`` that discards
        the domain-confidence hints.  Keeps backward compatibility with all
        callers that only need the patch dict.
        """
        return self.extract_with_confidence(user_message, current_patch, question_context).patch

    def extract_with_confidence(
        self,
        user_message: str,
        current_patch: ProfilePatch | None = None,
        question_context: str | None = None,
    ) -> ExtractionResult:
        """Return an ``ExtractionResult`` with patch **and** domain confidence hints.

        Two layers are merged:

        1. LLM inference (Ollama or Mock). Produces a high-recall but possibly
           noisy patch based on the few-shot-primed system prompt.
        2. Lexicon scan (``needs_taxonomy.extract_all_domains``). Deterministic
           synonym match; runs after the LLM so unambiguous positive/negative
           phrases can reinforce or override weak LLM signal.

        ``domain_confidence_hints`` is computed by comparing which domains each
        layer populated:

        - Both agree → 0.9 (high confidence).
        - Lexicon only → 0.8 (deterministic, reliable).
        - LLM only → 0.5 (model inference, less reliable).
        """
        current = current_patch if current_patch is not None else ProfilePatch()
        llm_patch = self._request_llm_patch(user_message, current, question_context)
        lexicon_patch = needs_taxonomy.extract_all_domains(user_message)
        merged = deep_merge_dicts(llm_patch, lexicon_patch)

        hints = self._compute_domain_confidence(llm_patch, lexicon_patch)
        return ExtractionResult(patch=merged, domain_confidence_hints=hints)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _request_llm_patch(
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
            # One retry with an even more explicit "JSON only" hint.
            retry_system_prompt = self.SYSTEM_PROMPT + "\nReturn ONLY JSON. No prose."
            raw_retry = self.llm_provider.complete(retry_system_prompt, user_prompt)
            parsed_retry = extract_first_json(raw_retry)
            validated_retry = ProfilerLLMResponse.model_validate(parsed_retry)
            return validated_retry.profile_patch.model_dump(
                exclude_defaults=True, exclude_none=True
            )

    @staticmethod
    def _compute_domain_confidence(
        llm_patch: dict[str, Any],
        lexicon_patch: dict[str, Any],
    ) -> dict[str, float]:
        """Compare LLM vs lexicon patches to assign per-domain confidence.

        Returns a dict mapping domain names (``"vision"``, ``"hearing"``,
        ``"mobility"``, ``"cognitive"``) to confidence floats. Only domains
        that have signal from at least one layer are included.
        """
        domains = ("vision", "hearing", "mobility", "cognitive")
        llm_needs = llm_patch.get("needs", {})
        lex_needs = lexicon_patch.get("needs", {})

        hints: dict[str, float] = {}
        for domain in domains:
            in_llm = bool(llm_needs.get(domain))
            in_lex = bool(lex_needs.get(domain))
            if in_llm and in_lex:
                hints[domain] = _CONFIDENCE_BOTH
            elif in_lex:
                hints[domain] = _CONFIDENCE_LEXICON
            elif in_llm:
                hints[domain] = _CONFIDENCE_LLM
            # else: no signal — omit from hints
        return hints
