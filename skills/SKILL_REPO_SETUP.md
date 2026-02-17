# SKILL_REPO_SETUP

## Goal
Create an offline-first Python repo structure for profiling, planning, UI, and tests.

## Steps
1. Create `backend/app`, `backend/tests`, `frontend`, `docs/specs`, and `skills`.
2. Add `__init__.py` files so imports like `backend.app...` work in pytest.
3. Add root `conftest.py` path setup so `backend` imports resolve in tests.
4. Add provider interfaces first (`LLMProvider`, `RouteProvider`, `ImageProvider`).
5. Keep mocks deterministic and local-file driven.
6. Add requirements for `pydantic`, `streamlit`, `pytest`, `jsonschema`, and `requests`.

## Runtime Expectations
- Default: `Mock (offline)` mode works with no model server.
- Optional: `Ollama (local)` mode for text and vision.
- No cloud API key dependency in this repo.

## Quality Checks
- `pytest -q` runs from repo root.
- Core flow works with no API keys or external services.
