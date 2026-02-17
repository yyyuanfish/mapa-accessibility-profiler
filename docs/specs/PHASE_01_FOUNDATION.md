# PHASE 01 - Foundation

## Scope
- Establish repo skeleton and Python packages.
- Add provider interfaces and deterministic mock implementations.
- Add shared utilities (`json_extract`) and test scaffolding.
- Add import stability support for tests (`conftest.py` path bootstrap).

## Acceptance Criteria
- Offline execution in mock mode.
- `pytest -q` runs with no external services.
- Import paths are stable (`backend.app...`).
- Optional local Ollama mode can be enabled without code changes.
