# SKILL_EVALUATION_HARNESS

## Goal
Measure detection quality across representative personas using scripted dialogue.

## Personas
- Blind persona
- Deaf/sign persona
- Wheelchair persona
- Reading/memory difficulty or child persona
- Mixed-needs persona

## Steps
1. Script short dialogue snippets per persona.
2. Run `ProfilerAgent` with `MockLLMProvider` on scripts to produce inferred profile patches.
3. Compare inferred labels with expected labels.
4. Compute per-persona and aggregate precision/recall.
5. Return a machine-readable summary for regression checks.

## Quality Checks
- Deterministic results in mock mode.
- Clear output structure for quick regression checks.
- Metrics are based on functional-need positive labels only.
