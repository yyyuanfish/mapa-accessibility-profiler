# PHASE 02 - Accessibility Profile Schema

## Scope
- Define Pydantic models for accessibility profile v1.
- Add JSON Schema mirror at `backend/app/schemas/accessibility_profile.v1.schema.json`.
- Include communication mode and confidence fields for all key domains.

## Required Semantics
- Functional needs only.
- Confidence with overall + per-domain values.
- Output mode includes `sign_gloss_text`.
- Cognitive support includes simple language and memory support.
- Support nullable booleans for partially answered profiling turns.

## Acceptance Criteria
- Model serialization validates against JSON Schema in tests.
- Field names remain aligned across schema, models, and service outputs.
