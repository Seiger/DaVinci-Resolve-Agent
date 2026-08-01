"""Bounded local faster-whisper adapter without shell execution."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

MODEL_NAME = "small"
LANGUAGE = "uk"
MAX_SEGMENTS = 10_000
MAX_TEXT_LENGTH = 4_000


class TranscriptionProviderError(RuntimeError):
    """Raised when the local transcription backend cannot produce a result."""


class FasterWhisperTranscriber:
    """Transcribe locally with a fixed CPU/int8 multilingual model policy."""

    def __init__(self, model_root: Path) -> None:
        self._model_root = model_root

    def transcribe(self, source_path: Path) -> dict[str, Any]:
        """Return normalized millisecond segments for one local media file."""
        resolved = source_path.resolve()
        if not resolved.is_file():
            raise ValueError(f"Transcription source does not exist: {resolved}")
        self._model_root.mkdir(parents=True, exist_ok=True)
        try:
            module = import_module("faster_whisper")
            model_class = module.WhisperModel
        except (ImportError, AttributeError) as error:
            raise TranscriptionProviderError(
                "faster-whisper is not installed; rerun installer/install.ps1."
            ) from error
        model = model_class(
            MODEL_NAME,
            device="cpu",
            compute_type="int8",
            download_root=str(self._model_root),
        )
        raw_segments, info = model.transcribe(
            str(resolved),
            language=LANGUAGE,
            task="transcribe",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=True,
        )
        segments: list[dict[str, Any]] = []
        for raw_segment in raw_segments:
            if len(segments) >= MAX_SEGMENTS:
                raise TranscriptionProviderError(
                    "Transcription exceeded 10000 segments."
                )
            text = " ".join(str(raw_segment.text).split())
            start_ms = round(float(raw_segment.start) * 1000)
            end_ms = round(float(raw_segment.end) * 1000)
            if (
                not text
                or len(text) > MAX_TEXT_LENGTH
                or start_ms < 0
                or end_ms <= start_ms
            ):
                raise TranscriptionProviderError(
                    "faster-whisper returned an invalid transcription segment."
                )
            segments.append(
                {"start_ms": start_ms, "end_ms": end_ms, "text": text}
            )
        if not segments:
            raise TranscriptionProviderError(
                "No speech segments were detected in the source file."
            )
        detected_language = str(getattr(info, "language", ""))
        probability = float(getattr(info, "language_probability", 0.0))
        duration = float(getattr(info, "duration", segments[-1]["end_ms"] / 1000))
        return {
            "backend": "faster-whisper",
            "model": MODEL_NAME,
            "language": detected_language or LANGUAGE,
            "language_probability": probability,
            "duration_ms": round(duration * 1000),
            "segments": segments,
        }
