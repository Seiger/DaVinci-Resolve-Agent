"""Deterministic standard-library processing for 16-bit PCM WAV files."""

from __future__ import annotations

import hashlib
import importlib
import math
import os
import sys
import warnings
import wave
from array import array
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, cast

SILENCE_THRESHOLD_DBFS = -50.0
ANALYSIS_WINDOW_MS = 20


class _AudioOpModule(Protocol):
    def max(self, fragment: bytes, width: int) -> int: ...

    def mul(self, fragment: bytes, width: int, factor: float) -> bytes: ...

    def rms(self, fragment: bytes, width: int) -> int: ...


def _load_audioop() -> _AudioOpModule:
    """Load the Python 3.10-3.12 PCM accelerator without warning callers."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        module = importlib.import_module("audioop")
    return cast(_AudioOpModule, module)


AUDIOOP = _load_audioop()


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


class PcmWavAudioProvider:
    """Analyze and level 16-bit PCM WAV assets without Resolve or shell tools."""

    def analyze(self, path: Path) -> PcmWavAnalysis:
        """Measure dialogue-oriented level, peak, clipping, and silence."""
        resolved = path.resolve()
        source = _read_pcm_wav_metadata(resolved)
        return _analyze(resolved, source)

    def apply_dialogue_level_preset(
        self,
        source_path: Path,
        output_path: Path,
        *,
        target_rms_dbfs: float = -20.0,
        max_peak_dbfs: float = -1.0,
        limit_peaks: bool = False,
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

        source = _read_pcm_wav_metadata(source_resolved)
        before = _analyze(source_resolved, source)
        if before.rms_dbfs is None or before.peak_dbfs is None:
            raise PcmWavProcessingError(
                "Silent audio cannot be normalized with the dialogue preset."
            )

        requested_gain_db = target_rms_dbfs - before.rms_dbfs
        peak_limited_gain_db = max_peak_dbfs - before.peak_dbfs
        applied_gain_db = (
            requested_gain_db
            if limit_peaks
            else min(requested_gain_db, peak_limited_gain_db)
        )
        gain = 10.0 ** (applied_gain_db / 20.0)
        limiter_pre_gain = 10.0 ** (
            ((applied_gain_db - max_peak_dbfs) if limit_peaks else 0.0)
            / 20.0
        )
        limiter_post_gain = (
            10.0 ** (max_peak_dbfs / 20.0) if limit_peaks else 1.0
        )
        limited_sample_count = 0
        output_resolved.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_resolved.with_name(f"{output_resolved.name}.tmp")
        try:
            with wave.open(str(source_resolved), "rb") as input_audio, wave.open(
                str(temporary), "wb"
            ) as output:
                output.setnchannels(source.channels)
                output.setsampwidth(2)
                output.setframerate(source.sample_rate_hz)
                written_frames = 0
                while raw := input_audio.readframes(65_536):
                    if limit_peaks:
                        limited = AUDIOOP.mul(raw, 2, limiter_pre_gain)
                        limited_samples = array("h")
                        limited_samples.frombytes(limited)
                        if sys.byteorder != "little":
                            limited_samples.byteswap()
                        limited_sample_count += limited_samples.count(32767)
                        limited_sample_count += limited_samples.count(-32768)
                        processed = AUDIOOP.mul(
                            limited,
                            2,
                            limiter_post_gain,
                        )
                    else:
                        processed = AUDIOOP.mul(raw, 2, gain)
                    output.writeframesraw(processed)
                    written_frames += len(raw) // (2 * source.channels)
                output.writeframes(b"")
                if written_frames != source.frame_count:
                    raise PcmWavProcessingError(
                        "PCM WAV sample data is incomplete."
                    )
            os.replace(temporary, output_resolved)
        except (EOFError, OSError, wave.Error) as error:
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
            "limiter_applied": limit_peaks,
            "limited_sample_count": limited_sample_count,
        }


def _read_pcm_wav_metadata(path: Path) -> _PcmWav:
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
    except (EOFError, OSError, wave.Error) as error:
        raise PcmWavProcessingError(f"PCM WAV is unreadable: {error}") from error
    return _PcmWav(channels, sample_rate, frame_count)


def _analyze(path: Path, source: _PcmWav) -> PcmWavAnalysis:
    frames_per_window = max(
        1,
        source.sample_rate_hz * ANALYSIS_WINDOW_MS // 1000,
    )
    sample_count = 0
    square_sum = 0.0
    peak = 0
    clipping_count = 0
    silent_windows = 0
    window_count = 0
    silence_amplitude = 32768.0 * 10.0 ** (SILENCE_THRESHOLD_DBFS / 20.0)
    read_frames = 0
    try:
        with wave.open(str(path), "rb") as input_audio:
            while raw := input_audio.readframes(frames_per_window):
                samples_in_window = len(raw) // 2
                window_rms = AUDIOOP.rms(raw, 2)
                square_sum += float(window_rms) ** 2 * samples_in_window
                sample_count += samples_in_window
                peak = max(peak, AUDIOOP.max(raw, 2))
                samples = array("h")
                samples.frombytes(raw)
                if sys.byteorder != "little":
                    samples.byteswap()
                clipping_count += samples.count(32767)
                clipping_count += samples.count(-32768)
                silent_windows += window_rms <= silence_amplitude
                window_count += 1
                read_frames += samples_in_window // source.channels
    except (EOFError, OSError, wave.Error) as error:
        raise PcmWavProcessingError(f"PCM WAV is unreadable: {error}") from error
    if read_frames != source.frame_count or sample_count < 1 or window_count < 1:
        raise PcmWavProcessingError("PCM WAV sample data is incomplete.")
    rms = math.sqrt(square_sum / sample_count)
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
