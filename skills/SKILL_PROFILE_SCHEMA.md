# SKILL_PROFILE_SCHEMA

## Goal
Define and validate profile data with both JSON Schema v1 and Pydantic.

## Required Fields
- `schema_version` fixed to `accessibility_profile.v1`
- `consent_to_profile`
- `needs.vision.blind_or_low_vision`
- `needs.vision.prefers_landmarks`
- `needs.hearing.deaf_or_hard_of_hearing`
- `needs.hearing.sign_language_user`
- `communication.output_mode` includes `sign_gloss_text`
- `needs.mobility.wheelchair_user`
- `needs.mobility.needs_step_free_route`
- `needs.mobility.avoid_long_walks`
- `needs.cognitive.needs_simple_language`
- `needs.cognitive.needs_memory_support`
- `needs.cognitive.reading_or_memory_difficulty_or_child`
- `preferences.avoid_crowds`
- `preferences.extra_time_buffer_min`
- `confidence.overall` and per-domain confidence scores

## Steps
1. Implement strict Pydantic models in `backend/app/models.py`.
2. Mirror constraints in `backend/app/schemas/accessibility_profile.v1.schema.json`.
3. Add tests that validate model dumps against JSON Schema.

## Quality Checks
- Boolean/null fields remain functional, not diagnostic.
- Schema and Pydantic field names are identical.
- Output mode values are `standard_text`, `simple_text`, `sign_gloss_text`.
