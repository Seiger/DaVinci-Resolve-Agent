"""Deterministic PCM WAV analysis for M5 draft planning."""

from __future__ import annotations

import math
import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

DEFAULT_WINDOW_MS = 20
MIN_SYNC_OVERLAP_WINDOWS = 20


class AudioAnalysisError(ValueError):
    """Raised when an audio source cannot be analyzed safely."""


@dataclass(frozen=True)
class AudioEnvelope:
    """Windowed PCM amplitude data independent from an editor provider."""

    path: Path
    window_ms: int
    duration_ms: int
    rms_values: tuple[float, ...]


def read_pcm_wav_envelope(
    path: Path,
    *,
    window_ms: int = DEFAULT_WINDOW_MS,
) -> AudioEnvelope:
    """Read an uncompressed 16-bit PCM WAV into an RMS envelope."""
    if window_ms < 1:
        raise AudioAnalysisError("window_ms must be greater than zero.")
    resolved = path.resolve()
    if not resolved.is_file():
        raise AudioAnalysisError(f"Audio file does not exist: {resolved}")

    try:
        with wave.open(str(resolved), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            compression = source.getcomptype()
            if compression != "NONE":
                raise AudioAnalysisError(
                    "Only uncompressed PCM WAV analysis is supported."
                )
            if sample_width != 2:
                raise AudioAnalysisError(
                    "Only 16-bit PCM WAV analysis is supported."
                )
            if channels < 1 or sample_rate < 1:
                raise AudioAnalysisError("WAV channel or sample-rate data is invalid.")

            frames_per_window = max(1, sample_rate * window_ms // 1000)
            rms_values: list[float] = []
            while True:
                raw = source.readframes(frames_per_window)
                if not raw:
                    break
                samples = array("h")
                samples.frombytes(raw)
                if sys.byteorder != "little":
                    samples.byteswap()
                if not samples:
                    break
                square_sum = sum(float(sample) ** 2 for sample in samples)
                rms_values.append(math.sqrt(square_sum / len(samples)))
    except (OSError, EOFError, wave.Error) as error:
        raise AudioAnalysisError(f"WAV file is unreadable: {error}") from error

    if not rms_values:
        raise AudioAnalysisError("WAV file contains no PCM samples.")
    duration_ms = round(frame_count * 1000 / sample_rate)
    return AudioEnvelope(
        path=resolved,
        window_ms=window_ms,
        duration_ms=duration_ms,
        rms_values=tuple(rms_values),
    )


def estimate_sync_offset(
    screen: AudioEnvelope,
    webcam: AudioEnvelope,
    *,
    max_offset_ms: int = 30_000,
) -> dict[str, int | float | str]:
    """Estimate webcam placement relative to screen audio by correlation."""
    if screen.window_ms != webcam.window_ms:
        raise AudioAnalysisError("Audio envelopes must use the same window size.")
    if max_offset_ms < 0:
        raise AudioAnalysisError("max_offset_ms must be non-negative.")

    screen_values = _standardize(screen.rms_values, "screen")
    webcam_values = _standardize(webcam.rms_values, "webcam")
    max_lag = max_offset_ms // screen.window_ms
    best_lag: int | None = None
    best_score = -2.0

    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            overlap = min(len(screen_values), len(webcam_values) - lag)
            screen_start = 0
            webcam_start = lag
        else:
            overlap = min(len(screen_values) + lag, len(webcam_values))
            screen_start = -lag
            webcam_start = 0
        if overlap < MIN_SYNC_OVERLAP_WINDOWS:
            continue
        score = sum(
            screen_values[screen_start + index]
            * webcam_values[webcam_start + index]
            for index in range(overlap)
        ) / overlap
        if score > best_score:
            best_score = score
            best_lag = lag

    if best_lag is None:
        raise AudioAnalysisError(
            "Audio sources do not have enough overlap for synchronization."
        )
    return {
        "strategy": "audio_correlation",
        "reference": "screen",
        "aligned": "webcam",
        "webcam_offset_ms": best_lag * screen.window_ms,
        "correlation_score": round(best_score, 6),
        "window_ms": screen.window_ms,
    }


def detect_pauses(
    envelope: AudioEnvelope,
    *,
    threshold_dbfs: float = -40.0,
    min_duration_ms: int = 700,
) -> list[dict[str, int | float]]:
    """Return silence intervals meeting the configured minimum duration."""
    if threshold_dbfs > 0:
        raise AudioAnalysisError("threshold_dbfs must not be positive.")
    if min_duration_ms < envelope.window_ms:
        raise AudioAnalysisError(
            "min_duration_ms must be at least one analysis window."
        )

    pauses: list[dict[str, int | float]] = []
    start_index: int | None = None
    for index, rms in enumerate((*envelope.rms_values, math.inf)):
        dbfs = (
            -math.inf
            if rms <= 0
            else 20.0 * math.log10(rms / 32768.0)
        )
        silent = dbfs <= threshold_dbfs
        if silent and start_index is None:
            start_index = index
        elif not silent and start_index is not None:
            start_ms = start_index * envelope.window_ms
            end_ms = min(index * envelope.window_ms, envelope.duration_ms)
            duration_ms = end_ms - start_ms
            if duration_ms >= min_duration_ms:
                pauses.append(
                    {
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "duration_ms": duration_ms,
                        "threshold_dbfs": threshold_dbfs,
                    }
                )
            start_index = None
    return pauses


def _standardize(values: tuple[float, ...], label: str) -> tuple[float, ...]:
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    deviation = math.sqrt(variance)
    if deviation <= 1e-9:
        raise AudioAnalysisError(
            f"{label} audio has no usable amplitude variation for sync."
        )
    return tuple((value - mean) / deviation for value in values)
