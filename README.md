# MAPA Profiler Agent

Offline-first prototype for **consent-first accessibility profiling** and **personalized journey planning**, built with a LangGraph multi-agent pipeline.

## Architecture

| Layer | Technology |
|-------|-----------|
| Frontend | React + TypeScript + Vite + Shadcn/Radix UI |
| API | FastAPI (REST + SSE streaming) |
| Pipeline | LangGraph StateGraph (parallel node execution) |
| LLM | Ollama (`qwen3.5:4b` text, `llava:7b` vision) or deterministic Mock |
| Validation | Pydantic v2 strict models + JSON Schema v1 |

## Runtime Modes

| Mode | Description |
|------|-------------|
| **Mock** (default) | Fully offline, deterministic — no model server needed |
| **Ollama** | Local LLM via Ollama — no cloud API key |
| **Backend** | React frontend connects to FastAPI over REST/SSE |

## Pipeline

### Profile Pipeline (multi-turn dialogue)
```
consent_guard → profiler → profile_manager → conversation_orchestrator → END
```

### Planning Pipeline (parallel fan-out)
```
input_validator → [ route_reasoner || image_hazard ] → hazard_fusion → planner → synthesis → END
```

`route_reasoner` and `image_hazard` run in parallel via LangGraph.
See interactive diagram: `docs/pipeline_workflow.html`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/routes` | List route fixtures |
| POST | `/api/profile/turn` | Profile dialogue turn (sync) |
| POST | `/api/profile/stream` | Profile dialogue turn (SSE) |
| POST | `/api/plan` | Create journey plan (sync) |
| POST | `/api/plan/stream` | Create journey plan (SSE, shows parallel progress) |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
# Backend (port 8000)
uvicorn backend.app.api:app --reload --port 8000

# Frontend (port 8080)
cd frontend && npm install && npm run dev
```

## Use Ollama (Optional)

```bash
ollama serve
ollama pull qwen3.5:4b    # text model (3.4 GB)
ollama pull llava:7b       # vision model (4.7 GB)
```

Then set `mode: "ollama"` in API requests, or select "Ollama" / "Backend" mode in the frontend.

## Tests

```bash
pytest -q
```

## Evaluation Harness

```bash
python -m backend.app.evaluation.run_eval
```

Runs 5 scripted personas (Blind, Deaf/sign, Wheelchair, Cognitive, Mixed) through the profiler and reports precision/recall metrics.

## Project Structure

```
backend/
  app/
    api.py                          # FastAPI endpoints (REST + SSE)
    models.py                       # Pydantic v2 models
    agents/
      state.py                      # LangGraph TypedDict state
      profile_graph.py              # Profile pipeline (4 nodes)
      planning_graph.py             # Planning pipeline (6 nodes, parallel)
    services/
      profiler_agent.py             # Dialogue agent
      planner_agent.py              # Plan generation agent
      multi_agent_orchestrator.py   # JourneyOrchestrator (delegates to graphs)
    providers/
      llm_provider.py               # Mock + Ollama LLM providers
      route_provider.py             # Mock route fixtures
      image_provider.py             # Mock + Ollama image analysis
    utils/
      json_extract.py               # Robust JSON extraction
    evaluation/
      harness.py                    # Evaluation framework
  tests/
frontend/
  src/
    components/                     # React UI components
    lib/
      runtime-context.tsx           # Mode/language state
      backend-api.ts                # Backend API client + schema translation
docs/
  pipeline_workflow.html            # Interactive pipeline diagram
  specs/                            # Phase specification documents
skills/                             # Agent responsibility definitions
```

## Supported Accessibility Behaviors

- **Vision**: stepwise text, avoid map-only references, landmark-friendly guidance
- **Hearing**: avoid audio-only cues, provide visible/text alternatives
- **Sign users**: `sign_gloss_text` output mode
- **Mobility**: step-free preference, strong stair alerts, route switching
- **Cognitive**: simple language mode, reminders, micro-step checklists

## Language Support

English, 中文, Deutsch
