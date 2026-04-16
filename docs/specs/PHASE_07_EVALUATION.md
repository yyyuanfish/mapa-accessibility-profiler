# PHASE 07 - Evaluation Harness

## Scope
- Evaluate profiler detection quality with scripted personas.
- Evaluate the profile workflow through the orchestrated multi-agent path, not only the raw profiler class.

## Personas
- Blind
- Deaf/sign
- Wheelchair
- Reading/memory difficulty or child
- Mixed needs

## Metrics
- Precision and recall on functional-need labels.
- Per-persona and aggregate reporting.
- Deterministic run with `MockLLMProvider`.
- Machine-readable output suitable for regression checks and trace-aware inspection.

## Acceptance Criteria
- Deterministic run in offline mock mode.
- Output is machine-readable JSON for regression checks.
- Persona set covers blind, deaf/sign, wheelchair, cognitive/child, and mixed needs.
- Evaluation remains compatible with orchestration-layer contracts.
