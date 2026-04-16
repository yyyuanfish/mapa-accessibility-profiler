# PHASE 03 - Profiler Agent

## Scope
- Build a short consent-first dialogue service.
- Infer profile patch from minimal user text.
- Support multilingual profiling turns under orchestration control.

## Output Contract
Profiler output JSON:
- `profile_patch`
- `confidence`
- `missing_critical_fields`
- `next_question`
- `next_question_context`
- `confirmation_text`

## Safety Rules
- Skip allowed at all times.
- No diagnosis language.
- Confirmation recap every turn.
- Keep response language aligned to UI selection.
- Only infer functional needs.
- Remain compatible with `JourneyOrchestrator` profile workflow.

## Acceptance Criteria
- Parsing fallback retries once with strict JSON instruction.
- Unit tests cover parsing and patch updates.
- Supports short direct answers across supported UI languages.
- Output can be wrapped by orchestration trace steps without changing core schema.
