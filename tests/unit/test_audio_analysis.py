"""Deterministic PCM WAV analysis tests."""

from __future__ import annotations

import wave
from array import array
from pathlib import Path

from agent.audio_analysis import (
    detect_pauses,
    estimate_sync_offset,
    read_pcm_wav_envelope,
)

SAMPLE_RATE = 1_000
WINDOW_MS = 20
SAMPLES_PER_WINDOW = SAMPLE_RATE * WINDOW_MS // 1_000


def _write_wav(path: Path, amplitudes: list[int]) -> None:
    samples = array(
        "h",
        [
            amplitude
            for amplitude in amplitudes
            for _ in range(SAMPLES_PER_WINDOW)
        ],
    )
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(samples.tobytes())


def test_audio_correlation_estimates_webcam_delay(tmp_path: Path) -> None:
    pattern = [
        1_000 + ((index * 7) % 13) * 1_000
        for index in range(100)
    ]
    screen_path = tmp_path / "screen.wav"
    webcam_path = tmp_path / "webcam.wav"
    _write_wav(screen_path, pattern)
    _write_wav(webcam_path, [0] * 10 + pattern)

    sync = estimate_sync_offset(
        read_pcm_wav_envelope(screen_path),
        read_pcm_wav_envelope(webcam_path),
        max_offset_ms=1_000,
    )

    assert sync["webcam_offset_ms"] == 200
    assert float(sync["correlation_score"]) > 0.9


def test_pause_detection_returns_long_silence_only(tmp_path: Path) -> None:
    audio_path = tmp_path / "speech.wav"
    _write_wav(
        audio_path,
        [8_000] * 10 + [0] * 40 + [8_000] * 10 + [0] * 10,
    )

    pauses = detect_pauses(
        read_pcm_wav_envelope(audio_path),
        threshold_dbfs=-40,
        min_duration_ms=700,
    )

    assert pauses == [
        {
            "start_ms": 200,
            "end_ms": 1_000,
            "duration_ms": 800,
            "threshold_dbfs": -40,
        }
    ]
