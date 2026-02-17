# SKILL_PLANNER_AGENT

## Goal
Generate a personalized journey plan from profile + raw route metadata.

## Input
- Validated profile JSON
- Route fixture data
- Optional hazards summary from image stub

## Output JSON
- `summary`
- `directions[]`
- `alerts`
- `checklist`
- `if_you_get_lost`
- `preferences_applied`

## Behavioral Rules
- Blind/low-vision: avoid map-only references, provide clear stepwise text.
- Deaf/HoH: avoid audio-only cues, provide visible/text alternatives.
- Sign-language users: support `sign_gloss_text` output mode.
- Wheelchair/mobility: prefer step-free routing, strongly alert on stairs.
- Cognitive/child: use Simple English + reminders + micro-steps.
- Apply optional image hazards conservatively (`stairs`, `slope`, `crowd`).
- Localize formatted plan output to selected UI language (`en`, `zh`, `de`).

## Quality Checks
- Output is strict JSON validated by Pydantic.
- No unsupported accessibility claims.
- Preferences listed in `preferences_applied` match actual transformations.
