"""M5 review-only rough-cut planning tests."""

from __future__ import annotations

import math
import wave
from pathlib import Path

from agent.contracts import validate_contract
from agent.rough_cut import RoughCutPlanner

SAMPLE_RATE = 8_000


def _write_wav(path: Path, amplitudes: list[int], window_ms: int = 20) -> None:
    samples_per_window = SAMPLE_RATE * window_ms // 1000
    frames = bytearray()
    for amplitude in amplitudes:
        for index in range(samples_per_window):
            sample = round(
                amplitude
                * math.sin(2 * math.pi * 220 * index / SAMPLE_RATE)
            )
            frames.extend(sample.to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(frames)


def test_planner_persists_deterministic_pending_review_plan(
    tmp_path: Path,
) -> None:
    screen = tmp_path / "screen.wav"
    webcam = tmp_path / "webcam.wav"
    speech = tmp_path / "speech.wav"
    pattern = [
        1_000 + ((index * 7) % 13) * 1_000
        for index in range(100)
    ]
    _write_wav(screen, pattern)
    _write_wav(webcam, ([0] * 10) + pattern)
    _write_wav(speech, ([5_000] * 10) + ([0] * 40) + ([5_000] * 50))
    planner = RoughCutPlanner(tmp_path / "plans")

    first = planner.create_plan(
        screen_file=str(screen),
        webcam_file=str(webcam),
        screen_audio_file=str(screen),
        webcam_audio_file=str(webcam),
        speech_audio_file=str(speech),
        timeline_name="M5 Draft",
        max_sync_offset_ms=500,
    )
    second = planner.create_plan(
        screen_file=str(screen),
        webcam_file=str(webcam),
        screen_audio_file=str(screen),
        webcam_audio_file=str(webcam),
        speech_audio_file=str(speech),
        timeline_name="M5 Draft",
        max_sync_offset_ms=500,
    )

    validate_contract("rough-cut-plan", first)
    assert first == second
    assert first["status"] == "pending_review"
    assert first["review"] == {
        "required": True,
        "approved": False,
        "apply_supported": False,
    }
    assert first["synchronization"]["webcam_offset_ms"] == 200
    assert first["pause_analysis"]["proposed_cuts"] == [
        {"start_ms": 320, "end_ms": 880, "duration_ms": 560}
    ]
    assert (tmp_path / "plans" / f"{first['plan_id']}.json").is_file()
