from __future__ import annotations

import io
import re
from abc import ABC, abstractmethod

from backend.app.models import SpeechTranscription


class SpeechProvider(ABC):
    @abstractmethod
    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str | None = None,
        language: str = "en",
    ) -> SpeechTranscription:
        raise NotImplementedError

    def prepare_output_text(self, text: str, *, language: str = "en") -> str:
        del language
        return _normalize_speech_text(text)

    @staticmethod
    def normalize_language(language: str) -> str:
        lowered = (language or "en").strip().lower()
        if lowered.startswith("zh"):
            return "zh"
        if lowered.startswith("de"):
            return "de"
        return "en"


class FasterWhisperSpeechProvider(SpeechProvider):
    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "int8",
        vad_filter: bool = True,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.vad_filter = vad_filter
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper is not installed. Run `pip install -r requirements.txt`."
                ) from exc

            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str | None = None,
        language: str = "en",
    ) -> SpeechTranscription:
        del mime_type
        normalized_language = self.normalize_language(language)

        try:
            model = self._get_model()
            segments, info = model.transcribe(
                io.BytesIO(audio_bytes),
                language=normalized_language,
                vad_filter=self.vad_filter,
                beam_size=1,
                condition_on_previous_text=False,
            )
            transcript = " ".join(
                segment.text.strip()
                for segment in segments
                if getattr(segment, "text", "").strip()
            ).strip()
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Speech transcription failed: {exc}") from exc

        if not transcript:
            raise RuntimeError("No speech was detected in the uploaded audio.")

        detected_language = getattr(info, "language", None) or normalized_language
        duration = getattr(info, "duration", None)
        return SpeechTranscription(
            transcript=transcript,
            language=str(detected_language),
            provider=f"faster_whisper:{self.model_size}",
            duration_sec=float(duration) if duration is not None else None,
        )


class MockSpeechProvider(SpeechProvider):
    def __init__(self, transcripts: dict[str, str] | None = None) -> None:
        self.transcripts = transcripts or {
            "en": "I need a step-free route.",
            "zh": "我需要无台阶路线。",
            "de": "Ich brauche eine stufenfreie Route.",
        }

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str | None = None,
        language: str = "en",
    ) -> SpeechTranscription:
        del audio_bytes
        del mime_type
        normalized_language = self.normalize_language(language)
        transcript = self.transcripts.get(
            normalized_language,
            self.transcripts["en"],
        )
        return SpeechTranscription(
            transcript=transcript,
            language=normalized_language,
            provider="mock",
        )


def _normalize_speech_text(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    return collapsed
