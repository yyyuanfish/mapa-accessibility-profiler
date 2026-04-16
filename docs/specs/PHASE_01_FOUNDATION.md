# PHASE 01 - Foundation

## Scope
- Establish repo skeleton and Python packages.
- Add provider interfaces and deterministic mock implementations.
- Add shared utilities (`json_extract`) and test scaffolding.
- Add import stability support for tests (`conftest.py` path bootstrap).
- Set up FastAPI server with CORS middleware.
- Add LangGraph as pipeline orchestration layer.

## Acceptance Criteria
- Offline execution in mock mode.
- `pytest -q` runs with no external services.
- Import paths are stable (`backend.app...`).
- `uvicorn backend.app.api:app` starts without errors.
- Optional local Ollama mode (`qwen3.5:4b` text, `llava:7b` vision) can be enabled without code changes.
