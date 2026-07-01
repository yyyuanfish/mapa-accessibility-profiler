from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.api import app
from backend.app.providers.speech_provider import MockSpeechProvider


client = TestClient(app)


def test_audio_transcribe_endpoint_returns_transcript() -> None:
    with patch(
        "backend.app.api._make_speech_provider",
        return_value=MockSpeechProvider(transcripts={"en": "I am blind."}),
    ):
        response = client.post(
            "/api/audio/transcribe?language=en",
            content=b"fake-audio",
            headers={"content-type": "audio/webm"},
        )

    assert response.status_code == 200
    assert response.json()["transcript"] == "I am blind."


def test_profile_turn_includes_speech_text() -> None:
    with patch(
        "backend.app.api._make_speech_provider",
        return_value=MockSpeechProvider(),
    ):
        response = client.post(
            "/api/profile/turn",
            json={
                "user_message": "I use a wheelchair.",
                "current_patch": {},
                "skipped_domains": [],
                "question_context": None,
                "turn_count": 1,
                "language": "en",
                "consent_to_profile": True,
                "mode": "mock",
                "ollama_url": "http://localhost:11434",
                "ollama_model": "shmily_006/Qw3:4b_4bit",
                "ollama_timeout": 300,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["speech_text"]
    assert "wheelchair" in payload["speech_text"].lower() or "route" in payload["speech_text"].lower()
