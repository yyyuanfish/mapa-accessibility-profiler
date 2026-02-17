# Multimodal Accessibility Profiling Agent

Offline-first prototype for consent-first accessibility profiling and personalized journey planning.

## Runtime Modes
- `Mock (offline)`: fully local deterministic behavior, no model server, no API key.
- `Ollama (local)`: local text + vision models (`/api/chat`) for richer responses, still no cloud API key.

Notes:
- This repo does not include a cloud LLM provider.
- Ollama can require internet once for `ollama pull`, then inference is local.

## What The System Does
- Runs a short consent-first dialogue to infer functional needs only.
- Builds validated profile JSON (`accessibility_profile.v1`) with Pydantic + JSON Schema.
- Personalizes route plans from fixture routes.
- Supports two Streamlit flows:
  - Chat-only
  - Stepper (`Consent -> Profile -> Trip -> Review/Export`)
- Supports optional consent-gated image hazard analysis (`stairs`, `slope`, `crowd`).

## Implemented Accessibility Behaviors
- Vision: stepwise text, avoid map-only phrasing, landmark-friendly guidance.
- Hearing: avoid audio-only instructions and prefer visible text cues.
- Sign users: supports `sign_gloss_text` output mode.
- Mobility: step-free preference and strong stair alerts.
- Cognitive or child-focused needs: switches to simple language mode with reminders/checklists.

## Language Support
- UI and plan output support `English`, `中文`, `Deutsch`.
- `Auto` currently defaults to English.
- Short answers supported: `yes/no`, `有/没有`, `是/否`, `ja/nein`, `skip`.

## Image Hazard Flow
- Explicit consent required before any image analysis.
- Source can be:
  - Upload (`.png`, `.jpg`, `.jpeg`)
  - Built-in sample images
- Analysis is manually triggered via button (`Analyze image hazards`), not auto-run on upload.
- Sample fixtures use fixed demo mappings:
  - `default_stairs.png` -> stairs high
  - `default_slope.png` -> slope high
  - `default_crowd.png` -> crowd high
  - `default_none.png` -> all none

## Project Structure
- `backend/app/models.py`
- `backend/app/schemas/accessibility_profile.v1.schema.json`
- `backend/app/providers/llm_provider.py`
- `backend/app/providers/route_provider.py`
- `backend/app/providers/image_provider.py`
- `backend/app/services/profiler_agent.py`
- `backend/app/services/planner_agent.py`
- `backend/app/evaluation/harness.py`
- `frontend/app.py`
- `backend/tests/`

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
pytest -q
streamlit run frontend/app.py
```

## Use Ollama (Optional)
1. Start Ollama:
```bash
ollama serve
```
2. Pull models:
```bash
ollama pull llama3.1:8b
ollama pull llava:7b
```
3. In the Streamlit sidebar set:
- `LLM backend` to `Ollama (local)`
- `Ollama base URL` to `http://127.0.0.1:11434` or `http://localhost:11434`
- `Text model` and `Vision model` names exactly as `ollama list`

Fallback behavior:
- If Ollama is unreachable or a request fails, the app falls back to mock providers for that turn/plan.

## Troubleshooting
- Check server:
```bash
curl http://127.0.0.1:11434/api/tags
```
- If `ollama serve` says `address already in use`, Ollama is already running.
- If image analysis is slow, this is often model load latency on first vision call.
- If image analysis errors, check model name and ensure it supports image input.

## Evaluation Harness
```bash
python -m backend.app.evaluation.run_eval
```

## Safety Notes
- No medical diagnosis inference.
- Functional needs only, with skip allowed.
- Confirm-understanding recap in profiler turns.
- Planner claims only what route fixture metadata supports.
