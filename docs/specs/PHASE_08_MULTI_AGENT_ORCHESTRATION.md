# PHASE 08 - Multi-Agent Orchestration (LangGraph)

## Scope
- Coordinate specialized agents through LangGraph `StateGraph` pipelines.
- Support **parallel node execution** in the planning pipeline.
- Expose SSE streaming for real-time per-node progress events.
- Keep the workflow explicit, traceable, and compatible with existing strict schemas.
- `Orchestrator` delegates to compiled LangGraph graphs.
- Keep speech I/O outside the reasoning graph as an orchestration-side capability.

## Profile Pipeline (sequential)

Nodes:
1. `consent_guard_node` — policy gate
2. `profiler_node` — `ProfilerAgent.process_turn()`
3. `profile_manager_node` — `ProfilerAgent.build_profile()` (schema validation)
4. `conversation_orchestrator_node` — next-action decision + agent reply

State: `ProfilerState` (`TypedDict` in `backend/app/agents/state.py`)

Output: `MultiAgentProfileResult` (profiler_output, draft_profile, trace, agent_reply)

## Planning Pipeline (parallel fan-out)

Nodes:
1. `input_validator_node` — validates `AccessibilityProfile` schema
2. `route_reasoner_node` — selects route (step-free switching) **[parallel]**
3. `image_hazard_node` — validates/passes image hazards **[parallel]**
4. `hazard_fusion_node` — merges route metadata + image hazards
5. `planner_node` — `PlannerAgent.create_plan()`
6. `synthesis_node` — builds user-facing explanation

State: `PlannerState` (`TypedDict`, uses `Annotated[list, operator.add]` for parallel trace merging)

Parallel execution: `route_reasoner_node` and `image_hazard_node` run concurrently after `input_validator_node`.

Output: `MultiAgentPlanResult` (route_decision, hazard_summary, plan, trace, agent_reply)

## SSE Streaming

Both pipelines support SSE via `stream_profile_turn()` and `stream_planning()`:
- `{"type": "progress", "agent": "<node>", "status": "starting"}`
- `{"type": "progress", "agent": "<node>", "status": "done", "duration_ms": N}`
- `{"type": "result", ...}`

Uses `contextvars.ContextVar` + `_wrap()` node wrapper for callback-driven progress.

## Design Rules
- Each agent node owns a narrowly defined responsibility.
- State is `TypedDict` with plain dicts — no Pydantic models in graph state.
- Parallel nodes return only their own keys (LangGraph merges automatically).
- Orchestration must not weaken the safety or schema guarantees of core agents.
- Final outputs include trace data suitable for demos, debugging, and evaluation.
- Speech input/output is provider-driven (`SpeechProvider`) and wraps the graph; it is not a LangGraph node unless future real-time voice turn-taking requires it.

## Acceptance Criteria
- FastAPI endpoints use `Orchestrator` (which delegates to LangGraph graphs).
- SSE streaming shows per-node progress with timing for both pipelines.
- Parallel nodes (`route_reasoner_node`, `image_hazard_node`) start simultaneously in SSE output.
- Evaluation harness can run through orchestration-layer entry points.
- Trace data clearly shows workflow step names, roles, and key findings.
- Existing profile and plan schemas remain unchanged in meaning.
