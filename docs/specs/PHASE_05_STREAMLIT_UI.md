# PHASE 05 - Streamlit UI

## Scope
Implement two UI modes:
- Chat-only mode
- Stepper mode: Consent -> Profile -> Trip -> Review/Export

## Requirements
- Consent-first flow.
- JSON output preview for profile and plan.
- Human-readable plan panel.
- Optional multimodal input gated by explicit consent.
- Sidebar runtime controls for Mock vs Ollama mode.
- Language selection for UI and formatted plan output.
- Image source options (upload + built-in sample fixtures).
- Manual image analysis trigger with progress feedback and cached results.

## Acceptance Criteria
- Both modes complete end-to-end with mock providers.
- Ollama failures degrade gracefully to mock behavior where implemented.
