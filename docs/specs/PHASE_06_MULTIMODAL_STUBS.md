# PHASE 06 - Multimodal Stub (Optional)

## Scope
- Add consent-gated image upload path.
- Generate hazards summary stub (`stairs`, `slope`, `crowd`).
- Support local vision analysis via Ollama when enabled.
- Provide built-in default sample fixtures for deterministic demos.

## Rules
- No image processing without explicit user consent.
- Stub output influences planner alerts/checklist conservatively.
- Analysis is manually triggered (button), not automatic on file upload.

## Acceptance Criteria
- Image provider is interface-driven and mockable.
- Sample fixture mappings are stable:
  - `default_stairs.png` -> stairs hazard
  - `default_slope.png` -> slope hazard
  - `default_crowd.png` -> crowd hazard
  - `default_none.png` -> no major hazard
