# PHASE 07 - Evaluation Harness

## Scope
- Evaluate profiler detection quality with scripted personas.

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

## Acceptance Criteria
- Deterministic run in offline mock mode.
- Output is machine-readable JSON for regression checks.
- Persona set covers blind, deaf/sign, wheelchair, cognitive/child, and mixed needs.
