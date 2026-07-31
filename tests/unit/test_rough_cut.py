"""M5 review-only rough-cut planning tests."""

from __future__ import annotations

import json
import math
import wave
from pathlib import Path

import pytest

from agent.contracts import validate_contract
from agent.rough_cut import (
    RoughCutInspector,
    RoughCutPlanner,
    RoughCutPlanningError,
    RoughCutReviewer,
)

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
    plan_path = tmp_path / "plans" / f"{first['plan_id']}.json"
    assert plan_path.is_file()

    plan_before_review = plan_path.read_bytes()
    reviewer = RoughCutReviewer(tmp_path / "plans")
    approval = reviewer.approve(
        first["plan_id"],
        confirm_review=True,
    )
    replay = reviewer.approve(
        first["plan_id"],
        confirm_review=True,
    )

    validate_contract("rough-cut-approval", approval)
    assert approval == replay
    assert approval["status"] == "approved"
    assert approval["apply_supported"] is False
    assert plan_path.read_bytes() == plan_before_review
    assert (
        tmp_path / "plans" / f"{first['plan_id']}.approval.json"
    ).is_file()

    inspector = RoughCutInspector(tmp_path / "plans")
    detail = inspector.get_plan(first["plan_id"])
    listing = inspector.list_plans(limit=1)

    assert detail["plan"] == first
    assert detail["approval"] == approval
    assert detail["effective_status"] == "approved"
    assert listing == {
        "plans": [
            {
                "plan_id": first["plan_id"],
                "created_at": first["created_at"],
                "timeline_name": "M5 Draft",
                "proposed_operation_count": 5,
                "effective_status": "approved",
                "approved_at": approval["approved_at"],
                "apply_supported": False,
            }
        ],
        "count": 1,
        "truncated": False,
    }

    changed_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    changed_plan["warnings"].append("Changed after approval.")
    plan_path.write_text(json.dumps(changed_plan), encoding="utf-8")
    with pytest.raises(RoughCutPlanningError, match="does not match"):
        reviewer.approve(first["plan_id"], confirm_review=True)


def test_reviewer_requires_canonical_id_and_explicit_confirmation(
    tmp_path: Path,
) -> None:
    reviewer = RoughCutReviewer(tmp_path / "plans")

    with pytest.raises(RoughCutPlanningError, match="plan_id"):
        reviewer.approve("../plan", confirm_review=True)
    with pytest.raises(RoughCutPlanningError, match="confirm_review"):
        reviewer.approve("a" * 64, confirm_review=False)

    inspector = RoughCutInspector(tmp_path / "plans")
    assert inspector.list_plans() == {
        "plans": [],
        "count": 0,
        "truncated": False,
    }
    with pytest.raises(RoughCutPlanningError, match="limit"):
        inspector.list_plans(limit=0)
