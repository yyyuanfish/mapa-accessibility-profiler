# PHASE 09 - Speech I/O

## Scope
- Add a dedicated `SpeechProvider` for speech-to-text (STT) and speech-ready output text.
- Support voice-first interaction while preserving full text visibility.
- Allow users to choose voice input or text input on every turn.
- Auto-transcribe microphone recordings before they enter the Orchestrator.
- Auto-read assistant replies when speech playback is enabled.
- Keep speech optional, consent-aware, and degradable without blocking text interaction.

## Architecture
- Speech is **not** a new reasoning subagent.
- Speech sits around orchestration as an I/O layer:
  - `audio input -> SpeechProvider.transcribe() -> Orchestrator`
  - `Orchestrator text reply -> SpeechProvider.prepare_output_text() -> browser/local TTS`
- `NeedsExtractor`, `ProfilerAgent`, `PlannerAgent`, and `ImageProvider` continue to operate on text / structured data only.

## Rules
- Never require speech to use the system.
- Always render text even when speech playback is enabled.
- Never start microphone capture without explicit user permission.
- If STT fails, keep typed input available and show a recoverable error.
- If speech playback fails, the text UI remains the source of truth.
- Do not merge speech preference into `communication.output_mode`; delivery modality and text style stay separate.

## Backend Requirements
- Add `SpeechProvider` interface under `backend/app/providers/`.
- Provide:
  - `MockSpeechProvider` for deterministic tests
  - `FasterWhisperSpeechProvider` for local/offline STT
- Expose `POST /api/audio/transcribe`.
- `Orchestrator` can:
  - transcribe uploaded audio
  - normalize assistant text into speech-ready output text

## Frontend Requirements
- Keep text chat visible at all times.
- Support:
  - typed send
  - microphone recording
  - backend STT transcription
  - auto-play assistant speech with mute control
- Voice mode may auto-send transcribed utterances.
- Text mode may keep transcribed text editable before send.

## Acceptance Criteria
- Users can complete profiling with only voice input.
- Users can switch between text and voice input without resetting the session.
- Assistant messages can be both displayed and spoken.
- Backend mode supports local STT through `SpeechProvider`.
- `pytest -q` covers speech provider and audio API behavior.
