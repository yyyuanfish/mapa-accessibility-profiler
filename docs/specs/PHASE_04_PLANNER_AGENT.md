# PHASE 04 - Planner Agent

## Scope
- Personalize route steps using profile + route fixtures.
- Emit strict plan JSON and human-readable formatted text.
- Remain composable inside a multi-agent planning workflow.

## Input Data
- Routes: `route_with_stairs`, `step_free_route`, `long_walk_route`
- Optional image hazards summary
- Response language (`en`, `zh`, `de`) for formatted output
- Route-selection and hazard-fusion decisions may be provided by upstream orchestration logic.

## Output Contract
Plan JSON:
- `summary`
- `directions[]`
- `alerts`
- `checklist`
- `if_you_get_lost`
- `preferences_applied`

## Acceptance Criteria
- Wheelchair users get step-free preference and stair alerts.
- Deaf/HoH users are not given audio-only instructions.
- Cognitive/simple-language users receive simplified output.
- Formatted plan text is localized to selected language.
- Planner output remains strict JSON and can be paired with route-decision and trace metadata.
