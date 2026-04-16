# AGENTS.md

## Mission
Build and maintain an offline-first **Multimodal Accessibility Profiling Agent for Personalized Journey Planning**.

Core outcomes:
- Run a short consent-first profiling dialogue (functional needs only).
- Produce validated JSON user profiles (JSON Schema v1 + Pydantic).
- Personalize route guidance using route fixture metadata.
- Orchestrate multi-agent pipelines via **LangGraph** with parallel execution.
- Expose REST + SSE streaming APIs via **FastAPI**.
- Serve a **React / TypeScript** frontend (Vite + Shadcn/Radix UI).
- Keep multimodal image analysis optional and explicitly consent-gated.
- Support three runtime modes:
  - **Mock** — deterministic offline, no model server
  - **Ollama** — local LLM (`qwen3.5:4b`) + vision (`llava:7b`), no cloud API key
  - **Backend** — React frontend calls FastAPI endpoints

## Pipeline Architecture

### Profile Pipeline (multi-turn dialogue)
```
consent_guard_node
      |
profiler_node           <- ProfilerAgent.process_turn()
      |
profile_manager_node    <- ProfilerAgent.build_profile()
      |
conversation_orchestrator_node
      |
     END
```

### Planning Pipeline (single-shot, parallel fan-out)
```
input_validator_node
      |
 +---------+---------+
 |                   |
route_reasoner    image_hazard     <- parallel
 |                   |
 +---------+---------+
           |
  hazard_fusion_node
           |
     planner_node       <- PlannerAgent.create_plan()
           |
    synthesis_node
           |
          END
```

See `docs/pipeline_workflow.html` for the interactive diagram.

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
- FastAPI server starts and all endpoints respond (`/api/health`, `/api/routes`, `/api/profile/turn`, `/api/profile/stream`, `/api/plan`, `/api/plan/stream`).
- React frontend builds and connects to the backend in "Backend" mode.
- SSE streaming shows per-node progress for both pipelines.
- Route fixtures include: `route_with_stairs`, `step_free_route`, `long_walk_route`.
- Evaluation harness runs all personas and returns precision/recall metrics.

## Standard Commands
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q

# Backend
uvicorn backend.app.api:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

## Engineering Notes
- Keep schema versioning explicit (`accessibility_profile.v1`).
- Preserve deterministic behavior for mock providers to keep tests stable.
- LangGraph `TypedDict` state uses `Annotated[list, operator.add]` for parallel-safe trace merging.
- Default Ollama model: `qwen3.5:4b` (text), `llava:7b` (vision).
- Keep documentation aligned with actual code paths and fallback behavior.
