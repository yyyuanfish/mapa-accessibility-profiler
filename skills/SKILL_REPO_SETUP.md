# SKILL_REPO_SETUP

## Goal
Create an offline-first Python repo with LangGraph multi-agent pipeline, FastAPI backend, and React frontend.

## Steps
1. Create `backend/app`, `backend/app/agents`, `backend/app/services`, `backend/app/providers`, `backend/tests`, `frontend`, `docs/specs`, and `skills`.
2. Add `__init__.py` files so imports like `backend.app...` work in pytest.
3. Add root `conftest.py` path setup so `backend` imports resolve in tests.
4. Add provider interfaces first (`LLMProvider`, `RouteProvider`, `ImageProvider`, `SpeechProvider`).
5. Keep mocks deterministic and local-file driven.
6. Add LangGraph `StateGraph` pipelines in `backend/app/agents/` with `TypedDict` state.
7. Add FastAPI server in `backend/app/api.py` with REST + SSE streaming endpoints.
8. Requirements: `pydantic`, `pytest`, `jsonschema`, `requests`, `fastapi`, `uvicorn`, `langgraph`.

## Runtime Expectations
- Default: `Mock (offline)` mode works with no model server.
- Optional: `Ollama (local)` mode for text (`qwen3.5:4b`) and vision (`llava:7b`).
- No cloud API key dependency in this repo.

## Quality Checks
- `pytest -q` runs from repo root.
- `uvicorn backend.app.api:app` starts without errors.
- Core flow works with no API keys or external services.
