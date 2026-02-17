# SKILL_STREAMLIT_UI

## Goal
Provide two UX modes for the offline prototype.

## Modes
1. Chat-only profiling + planning flow
2. Button-based stepper:
   - Consent
   - Profile
   - Trip
   - Review/Export

## Steps
1. Store profile, consent flags, and route selections in `st.session_state`.
2. Gate multimodal upload behind explicit image consent.
3. Display both JSON and formatted human-readable plan.
4. Keep UI copy concise and accessible.
5. Support language selection (`English`, `中文`, `Deutsch`, `Auto` where auto defaults to English).
6. Support image source selection:
   - Upload image
   - Built-in sample fixtures
7. Trigger image analysis manually by button (do not auto-run on upload).
8. Cache hazard analysis by image key to avoid repeated long runs.
9. In Ollama mode, show helpful status and fallback to mock providers on request failures.

## Quality Checks
- Works without API keys.
- Both modes reach review/export successfully.
- Sample fixtures provide stable demo hazard outcomes.
