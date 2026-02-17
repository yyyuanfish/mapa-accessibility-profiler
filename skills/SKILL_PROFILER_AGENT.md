# SKILL_PROFILER_AGENT

## Goal
Implement a short consent-first dialogue agent that infers functional accessibility needs.

## Input
- Latest user message
- Current profile patch
- Skipped domains (optional)

## Output JSON
- `profile_patch`
- `confidence`
- `missing_critical_fields`
- `next_question`
- `next_question_context`
- `confirmation_text`

## Steps
1. Ask minimal questions to distinguish vision/hearing/mobility/cognitive needs.
2. Use provider call for LLM behavior; keep logic deterministic in mock mode.
3. Parse response via robust JSON extractor.
4. Retry once with strict "return ONLY JSON" instruction if parsing fails.
5. Always include recap confirmation text.
6. Accept short direct answers (`yes/no/skip`, `有/没有/是/否`, `ja/nein`) in UI flow.
7. Keep language output aligned with selected response language (`en`, `zh`, `de`).

## Quality Checks
- Dialogue can complete in <= 5-8 turns.
- User can skip and continue.
- No medical diagnosis wording.
- If cognitive support is requested or detected, output mode can move to simple text.
