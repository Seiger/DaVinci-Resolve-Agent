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
