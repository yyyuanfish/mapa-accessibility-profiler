# AGENTS.md

## Mission
Build and maintain an offline-first **Multimodal Accessibility Profiling Agent for Personalized Journey Planning**.

Core outcomes:
- Run a short consent-first profiling dialogue (functional needs only).
- Produce validated JSON user profiles (JSON Schema v1 + Pydantic).
- Personalize route guidance using route fixture metadata.
- Support Streamlit chat and stepper flows.
- Keep multimodal image analysis optional and explicitly consent-gated.
- Support both runtime modes in one codebase:
  - Deterministic offline `Mock` mode
  - Local `Ollama` mode for text and vision models (no cloud API key)

## Product Rules
- Never infer medical diagnoses.
- Ask minimal, non-intrusive questions and always allow skip.
- Always include a recap confirmation: "Here is what I understood... Is this correct?"
- Never claim real-world accessibility unless route data explicitly contains it.
- Keep all model calls behind provider interfaces (`LLMProvider`, `RouteProvider`, `ImageProvider`).
- Default runtime is offline with mock providers.
- If local model calls fail, degrade gracefully to mock behavior where implemented.
- Agent outputs must be strict JSON validated by Pydantic.
- If JSON parsing fails, retry once with a strict instruction to return JSON only.
- If cognitive/readability needs are detected (or requested), switch output to Simple English.

## Target User Types
The system must explicitly support:
- Blind / low-vision users
- Deaf / hard-of-hearing users
- Sign-language users
- Wheelchair / mobility disability users
- Users with reading or memory difficulty, cognitive load concerns, or children

## Definition of Done (DoD)
A change is complete only if:
- All profile and plan schemas validate.
- `pytest -q` passes.
- Streamlit app starts and supports both modes:
  - Chat-only
  - Stepper: Consent -> Profile -> Trip -> Review/Export
- Streamlit image flow is consent-gated and manually triggered (not auto-run on upload).
- Route fixtures include:
  - `route_with_stairs`
  - `step_free_route`
  - `long_walk_route`
- Built-in sample images include:
  - `default_stairs.png`
  - `default_slope.png`
  - `default_crowd.png`
  - `default_none.png`
- Evaluation harness runs all personas and returns precision/recall metrics.
- README includes setup and run instructions.

## Standard Commands
- `python -m venv .venv`
- `source .venv/bin/activate`
- `pip install -r requirements.txt`
- `pytest -q`
- `streamlit run frontend/app.py`

## Engineering Notes
- Keep schema versioning explicit (`accessibility_profile.v1`).
- Preserve deterministic behavior for mock providers to keep tests stable.
- Keep documentation aligned with actual code paths and fallback behavior.
- Keep generated text concise and functional.
