"""Deterministic standard-library processing for 16-bit PCM WAV files."""

from __future__ import annotations

import hashlib
import math
import os
import sys
import wave
from array import array
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SILENCE_THRESHOLD_DBFS = -50.0
ANALYSIS_WINDOW_MS = 20


class PcmWavProcessingError(ValueError):
    """Raised when a PCM WAV cannot be analyzed or processed safely."""


@dataclass(frozen=True)
class PcmWavAnalysis:
    """Provider-neutral measurements for one PCM WAV asset."""

    duration_ms: int
    sample_rate_hz: int
    channels: int
    sample_width_bits: int
    rms_dbfs: float | None
    peak_dbfs: float | None
    clipping_sample_count: int
    silent_window_ratio: float
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return asdict(self)


@dataclass(frozen=True)
class _PcmWav:
    channels: int
    sample_rate_hz: int
    frame_count: int
    samples: array[int]


class PcmWavAudioProvider:
    """Analyze and level 16-bit PCM WAV assets without Resolve or shell tools."""

    def analyze(self, path: Path) -> PcmWavAnalysis:
        """Measure dialogue-oriented level, peak, clipping, and silence."""
        resolved = path.resolve()
        source = _read_pcm_wav(resolved)
        return _analyze(resolved, source)

    def apply_dialogue_level_preset(
        self,
        source_path: Path,
        output_path: Path,
        *,
        target_rms_dbfs: float = -20.0,
        max_peak_dbfs: float = -1.0,
    ) -> dict[str, Any]:
        """Create a gain-normalized derived WAV while preserving the source."""
        if not -60.0 <= target_rms_dbfs <= -6.0:
            raise PcmWavProcessingError(
                "target_rms_dbfs must be between -60 and -6."
            )
        if not -12.0 <= max_peak_dbfs <= 0.0:
            raise PcmWavProcessingError(
                "max_peak_dbfs must be between -12 and 0."
            )

        source_resolved = source_path.resolve()
        output_resolved = output_path.resolve()
        if source_resolved == output_resolved:
            raise PcmWavProcessingError(
                "Derived output path must differ from the source path."
            )

        source = _read_pcm_wav(source_resolved)
        before = _analyze(source_resolved, source)
        if before.rms_dbfs is None or before.peak_dbfs is None:
            raise PcmWavProcessingError(
                "Silent audio cannot be normalized with the dialogue preset."
            )

        requested_gain_db = target_rms_dbfs - before.rms_dbfs
        peak_limited_gain_db = max_peak_dbfs - before.peak_dbfs
        applied_gain_db = min(requested_gain_db, peak_limited_gain_db)
        gain = 10.0 ** (applied_gain_db / 20.0)
        processed = array(
            "h",
            (
                max(-32768, min(32767, round(sample * gain)))
                for sample in source.samples
            ),
        )

        output_resolved.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_resolved.with_name(f"{output_resolved.name}.tmp")
        try:
            with wave.open(str(temporary), "wb") as output:
                output.setnchannels(source.channels)
                output.setsampwidth(2)
                output.setframerate(source.sample_rate_hz)
                output.writeframes(_little_endian_bytes(processed))
            os.replace(temporary, output_resolved)
        except (OSError, wave.Error) as error:
            raise PcmWavProcessingError(
                f"Failed to create derived PCM WAV: {error}"
            ) from error
        finally:
            if temporary.exists():
                temporary.unlink()

        after = self.analyze(output_resolved)
        return {
            "before": before.to_dict(),
            "after": after.to_dict(),
            "requested_gain_db": round(requested_gain_db, 3),
            "applied_gain_db": round(applied_gain_db, 3),
            "peak_guard_limited": applied_gain_db < requested_gain_db,
        }


def _read_pcm_wav(path: Path) -> _PcmWav:
    if not path.is_file():
        raise PcmWavProcessingError(f"Audio file does not exist: {path}")
    try:
        with wave.open(str(path), "rb") as source:
            if source.getcomptype() != "NONE":
                raise PcmWavProcessingError(
                    "Only uncompressed PCM WAV audio is supported."
                )
            if source.getsampwidth() != 2:
                raise PcmWavProcessingError(
                    "Only 16-bit PCM WAV audio is supported."
                )
            channels = source.getnchannels()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            if channels < 1 or sample_rate < 1 or frame_count < 1:
                raise PcmWavProcessingError("PCM WAV metadata is invalid.")
            samples = array("h")
            samples.frombytes(source.readframes(frame_count))
            if sys.byteorder != "little":
                samples.byteswap()
    except (EOFError, OSError, wave.Error) as error:
        raise PcmWavProcessingError(f"PCM WAV is unreadable: {error}") from error
    if len(samples) != frame_count * channels:
        raise PcmWavProcessingError("PCM WAV sample data is incomplete.")
    return _PcmWav(channels, sample_rate, frame_count, samples)


def _analyze(path: Path, source: _PcmWav) -> PcmWavAnalysis:
    square_sum = sum(float(sample) ** 2 for sample in source.samples)
    rms = math.sqrt(square_sum / len(source.samples))
    peak = max(abs(sample) for sample in source.samples)
    clipping_count = sum(abs(sample) >= 32767 for sample in source.samples)
    frames_per_window = max(
        1,
        source.sample_rate_hz * ANALYSIS_WINDOW_MS // 1000,
    )
    samples_per_window = frames_per_window * source.channels
    silent_windows = 0
    window_count = 0
    silence_amplitude = 32768.0 * 10.0 ** (SILENCE_THRESHOLD_DBFS / 20.0)
    for start in range(0, len(source.samples), samples_per_window):
        window = source.samples[start : start + samples_per_window]
        window_rms = math.sqrt(
            sum(float(sample) ** 2 for sample in window) / len(window)
        )
        silent_windows += window_rms <= silence_amplitude
        window_count += 1
    return PcmWavAnalysis(
        duration_ms=round(source.frame_count * 1000 / source.sample_rate_hz),
        sample_rate_hz=source.sample_rate_hz,
        channels=source.channels,
        sample_width_bits=16,
        rms_dbfs=_dbfs(rms),
        peak_dbfs=_dbfs(float(peak)),
        clipping_sample_count=clipping_count,
        silent_window_ratio=round(silent_windows / window_count, 6),
        sha256=_sha256(path),
    )


def _dbfs(amplitude: float) -> float | None:
    if amplitude <= 0:
        return None
    return round(20.0 * math.log10(amplitude / 32768.0), 3)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _little_endian_bytes(samples: array[int]) -> bytes:
    if sys.byteorder == "little":
        return samples.tobytes()
    copy = array("h", samples)
    copy.byteswap()
    return copy.tobytes()
