# SKILL_SPEECH_IO

## Goal
Implement voice-first but text-safe interaction around the Orchestrator.

## Responsibilities
- Convert microphone audio into text via `SpeechProvider`.
- Normalize assistant replies into speech-ready text.
- Keep speech optional and consent-gated.
- Preserve text UI as the primary source of truth.

## Input
- Recorded audio bytes + mime type
- Selected language
- Assistant reply text

## Output
- `SpeechTranscription`
- speech-ready text for frontend/browser TTS

## Rules
1. Speech is an I/O capability, not a reasoning subagent.
2. `NeedsExtractor`, `ProfilerAgent`, and `PlannerAgent` must stay text-first.
3. Text must remain visible even when speech playback is on.
4. STT failure must not block typed input.
5. Default tests use deterministic mock speech providers.

## Quality Checks
- Backend exposes an audio transcription endpoint.
- Voice and text input share the same downstream turn-dispatch logic.
- Assistant messages can be spoken without changing schema meaning.
