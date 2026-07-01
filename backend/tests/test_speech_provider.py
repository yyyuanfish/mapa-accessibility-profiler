from __future__ import annotations

from backend.app.providers.speech_provider import MockSpeechProvider


def test_mock_speech_provider_transcribes_by_language() -> None:
    provider = MockSpeechProvider()

    result = provider.transcribe(b"fake-audio", language="zh")

    assert result.transcript == "我需要无台阶路线。"
    assert result.language == "zh"
    assert result.provider == "mock"


def test_mock_speech_provider_normalizes_output_text() -> None:
    provider = MockSpeechProvider()

    speech_text = provider.prepare_output_text("Hello\n\nworld.   Please   continue.")

    assert speech_text == "Hello world. Please continue."
