"""Tests for the standard-library PCM WAV audio provider."""

from __future__ import annotations

import math
import wave
from pathlib import Path

import pytest

from providers.audio import PcmWavAudioProvider, PcmWavProcessingError

SAMPLE_RATE = 8_000


def _write_tone(path: Path, amplitude: int, duration_ms: int = 1_000) -> None:
    sample_count = SAMPLE_RATE * duration_ms // 1_000
    frames = bytearray()
    for index in range(sample_count):
        sample = round(
            amplitude * math.sin(2 * math.pi * 220 * index / SAMPLE_RATE)
        )
        frames.extend(sample.to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(frames)


def test_provider_creates_normalized_derived_wav_and_preserves_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    output = tmp_path / "derived.wav"
    _write_tone(source, 2_000)
    original = source.read_bytes()
    provider = PcmWavAudioProvider()

    result = provider.apply_dialogue_level_preset(source, output)

    assert source.read_bytes() == original
    assert output.is_file()
    assert result["before"]["rms_dbfs"] < -20.5
    assert result["after"]["rms_dbfs"] == pytest.approx(-20.0, abs=0.05)
    assert result["after"]["peak_dbfs"] <= -1.0
    assert result["applied_gain_db"] > 0


def test_provider_rejects_silent_audio(tmp_path: Path) -> None:
    source = tmp_path / "silent.wav"
    _write_tone(source, 0)

    with pytest.raises(PcmWavProcessingError, match="Silent audio"):
        PcmWavAudioProvider().apply_dialogue_level_preset(
            source,
            tmp_path / "derived.wav",
        )


def test_provider_streams_wav_frames_in_bounded_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "long-source.wav"
    output = tmp_path / "long-derived.wav"
    _write_tone(source, 2_000, duration_ms=20_000)
    original_readframes = wave.Wave_read.readframes
    requested_frame_counts: list[int] = []

    def tracked_readframes(reader: wave.Wave_read, count: int) -> bytes:
        requested_frame_counts.append(count)
        return original_readframes(reader, count)

    monkeypatch.setattr(wave.Wave_read, "readframes", tracked_readframes)

    PcmWavAudioProvider().apply_dialogue_level_preset(source, output)

    assert output.is_file()
    assert requested_frame_counts
    assert max(requested_frame_counts) <= 65_536


def test_provider_limiter_reaches_rms_target_with_isolated_full_scale_peak(
    tmp_path: Path,
) -> None:
    source = tmp_path / "peaked-source.wav"
    output = tmp_path / "limited-derived.wav"
    _write_tone(source, 2_000)
    with wave.open(str(source), "rb") as input_audio:
        parameters = input_audio.getparams()
        frames = bytearray(input_audio.readframes(input_audio.getnframes()))
    frames[:2] = (32767).to_bytes(2, "little", signed=True)
    with wave.open(str(source), "wb") as output_audio:
        output_audio.setparams(parameters)
        output_audio.writeframes(frames)

    result = PcmWavAudioProvider().apply_dialogue_level_preset(
        source,
        output,
        limit_peaks=True,
    )

    assert result["limiter_applied"] is True
    assert result["limited_sample_count"] >= 1
    assert result["after"]["rms_dbfs"] == pytest.approx(-20.0, abs=0.5)
    assert result["after"]["peak_dbfs"] <= -1.0
