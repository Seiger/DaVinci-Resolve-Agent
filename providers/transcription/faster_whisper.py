"""Bounded local faster-whisper adapter without shell execution."""

from __future__ import annotations

import math
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import av
import numpy as np
from numpy.typing import NDArray

from agent.storage import ensure_storage_capacity

MODEL_NAME = "small"
LANGUAGE = "uk"
MAX_SEGMENTS = 10_000
MAX_TEXT_LENGTH = 4_000
MAX_SOURCE_RANGE_SECONDS = 300.0
MODEL_SAMPLE_RATE = 16_000


class TranscriptionProviderError(RuntimeError):
    """Raised when the local transcription backend cannot produce a result."""


class FasterWhisperTranscriber:
    """Transcribe locally with a fixed CPU/int8 multilingual model policy."""

    def __init__(self, model_root: Path) -> None:
        self._model_root = model_root
        self._model: Any | None = None

    def transcribe(
        self,
        source_path: Path,
        *,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Return normalized millisecond segments for one local media file."""
        resolved = source_path.resolve()
        if not resolved.is_file():
            raise ValueError(f"Transcription source does not exist: {resolved}")
        source_range = _source_range(start_seconds, end_seconds)
        audio: str | NDArray[np.float32]
        if source_range is None:
            audio = str(resolved)
        else:
            audio = _decode_audio_range(resolved, *source_range)
        model = self._model_instance()
        raw_segments, info = model.transcribe(
            audio,
            language=LANGUAGE,
            task="transcribe",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=True,
        )
        return _normalized_transcript(raw_segments, info)

    def _model_instance(self) -> Any:
        if self._model is not None:
            return self._model
        ensure_storage_capacity(self._model_root, 2 * 1024 * 1024 * 1024)
        try:
            module = import_module("faster_whisper")
            model_class = module.WhisperModel
        except (ImportError, AttributeError) as error:
            raise TranscriptionProviderError(
                "faster-whisper is not installed; rerun installer/install.ps1."
            ) from error
        self._model = model_class(
            MODEL_NAME,
            device="cpu",
            compute_type="int8",
            download_root=str(self._model_root),
        )
        return self._model


def _source_range(
    start_seconds: float | None,
    end_seconds: float | None,
) -> tuple[float, float] | None:
    if start_seconds is None and end_seconds is None:
        return None
    if (
        isinstance(start_seconds, bool)
        or not isinstance(start_seconds, (int, float))
        or isinstance(end_seconds, bool)
        or not isinstance(end_seconds, (int, float))
    ):
        raise ValueError("start_seconds and end_seconds must be finite numbers.")
    start = float(start_seconds)
    end = float(end_seconds)
    if (
        not math.isfinite(start)
        or not math.isfinite(end)
        or start < 0
        or end <= start
    ):
        raise ValueError("Source range must satisfy 0 <= start_seconds < end_seconds.")
    if end - start > MAX_SOURCE_RANGE_SECONDS:
        raise ValueError("Source range must not exceed 300 seconds.")
    return start, end


def _decode_audio_range(
    source_path: Path,
    start_seconds: float,
    end_seconds: float,
) -> NDArray[np.float32]:
    chunks: list[NDArray[np.float32]] = []
    with av.open(str(source_path)) as container:
        stream = next(iter(container.streams.audio), None)
        if stream is None:
            raise TranscriptionProviderError("No audio stream is available.")
        source_rate = int(stream.rate or 0)
        if source_rate <= 0:
            raise TranscriptionProviderError("Audio sample rate is unavailable.")
        timestamp = int(start_seconds / float(stream.time_base))
        container.seek(timestamp, stream=stream, any_frame=False, backward=True)
        fallback_time = start_seconds
        for frame in container.decode(stream):
            values = _mono_float32(frame.to_ndarray())
            frame_start = _frame_start_seconds(frame, fallback_time)
            frame_end = frame_start + values.size / source_rate
            fallback_time = frame_end
            if frame_start >= end_seconds:
                break
            if frame_end <= start_seconds:
                continue
            slice_start = max(
                0,
                round((start_seconds - frame_start) * source_rate),
            )
            slice_end = min(
                values.size,
                round((end_seconds - frame_start) * source_rate),
            )
            if slice_end > slice_start:
                chunks.append(values[slice_start:slice_end])
    if not chunks:
        raise TranscriptionProviderError("No audio samples exist in source range.")
    source_audio = np.concatenate(chunks).astype(np.float32, copy=False)
    if source_rate == MODEL_SAMPLE_RATE:
        return source_audio
    target_count = round(source_audio.size * MODEL_SAMPLE_RATE / source_rate)
    if target_count <= 0:
        raise TranscriptionProviderError("Source range is too short to transcribe.")
    source_positions = np.arange(source_audio.size, dtype=np.float64)
    target_positions = np.arange(target_count, dtype=np.float64) * (
        source_rate / MODEL_SAMPLE_RATE
    )
    return cast(
        NDArray[np.float32],
        np.interp(target_positions, source_positions, source_audio).astype(np.float32),
    )


def _mono_float32(values: np.ndarray[Any, Any]) -> NDArray[np.float32]:
    normalized = values.astype(np.float32)
    if normalized.ndim > 1:
        normalized = np.mean(normalized, axis=0, dtype=np.float32)
    normalized = normalized.reshape(-1)
    if np.issubdtype(values.dtype, np.integer):
        info = np.iinfo(values.dtype)
        normalized /= max(abs(info.min), abs(info.max))
    return cast(
        NDArray[np.float32],
        np.clip(normalized, -1.0, 1.0).astype(np.float32, copy=False),
    )


def _frame_start_seconds(frame: Any, fallback: float) -> float:
    frame_time = getattr(frame, "time", None)
    if frame_time is not None:
        value = float(frame_time)
        if math.isfinite(value):
            return value
    pts = getattr(frame, "pts", None)
    time_base = getattr(frame, "time_base", None)
    if pts is not None and time_base is not None:
        value = float(pts * time_base)
        if math.isfinite(value):
            return value
    return fallback


def _normalized_transcript(raw_segments: Any, info: Any) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    for raw_segment in raw_segments:
        if len(segments) >= MAX_SEGMENTS:
            raise TranscriptionProviderError("Transcription exceeded 10000 segments.")
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
        segments.append({"start_ms": start_ms, "end_ms": end_ms, "text": text})
    if not segments:
        raise TranscriptionProviderError("No speech segments were detected.")
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
