"""Tests for M50 baseline edit QA and render orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

import pytest

from agent.baseline_edit import BaselineEditError, BaselineEditWorkflow

FINALIZATION_ID = "a" * 64
AUDIO_ID = "b" * 64
SUBTITLE_ID = "c" * 64
VISUAL_ID = "d" * 64
TIMELINE_ID = "timeline-final"


class ReceiptIds(TypedDict):
    finalization_receipt_id: str
    audio_integration_receipt_id: str
    subtitle_receipt_id: str
    visual_treatment_receipt_id: str


class FakeGateway:
    def __init__(self) -> None:
        self.calls = 0

    def timeline_items(self, timeline_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        assert timeline_id == TIMELINE_ID
        return {
            "timeline_id": TIMELINE_ID,
            "name": "Final",
            "items": [
                _item("video", "video", 1, 0, 100),
                _item("audio-source", "audio", 1, 0, 100),
                _item("audio-clean", "audio", 2, 0, 100),
                _item("title", "video", 1, 100, 120),
            ],
        }

    def subtitle_environment(self, timeline_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "timeline_id": timeline_id,
            "tracks": [
                {
                    "index": 1,
                    "items": [{"timeline_item_id": "subtitle"}],
                }
            ],
        }


class FakePreparer:
    def __init__(self) -> None:
        self.calls = 0
        self.custom_name = ""

    def prepare(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        self.custom_name = kwargs["custom_name"]
        return {"receipt_id": "e" * 64, "status": "applied"}


class FakeExecutor:
    def __init__(self) -> None:
        self.start_calls = 0

    def start(self, **kwargs: Any) -> dict[str, Any]:
        self.start_calls += 1
        return {"receipt_id": "f" * 64, "status": "started"}

    def status(
        self,
        execution_receipt_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        assert execution_receipt_id == "f" * 64
        return {
            "live": {"status": {"JobStatus": "Complete"}},
            "output": {
                "output": {"path": "managed.mp4", "size_bytes": 1024},
                "validation": {
                    "completed": True,
                    "managed_path": True,
                    "non_empty": True,
                    "passed": True,
                },
            },
        }


def test_preview_accepts_one_canonical_live_timeline(tmp_path: Path) -> None:
    workflow, gateway, _, _ = _workflow(tmp_path)

    result = workflow.preview(**_ids())

    assert result["status"] == "ready"
    assert result["summary"] == {"passed": 10, "failed": 0}
    assert gateway.calls == 2


def test_preview_accepts_core_edit_without_optional_enhancements(
    tmp_path: Path,
) -> None:
    workflow, gateway, _, _ = _workflow(tmp_path)

    result = workflow.preview(
        finalization_receipt_id=FINALIZATION_ID,
        audio_integration_receipt_id=AUDIO_ID,
    )

    assert result["status"] == "ready"
    assert result["inputs"]["subtitle_receipt_id"] is None
    assert result["inputs"]["visual_treatment_receipt_id"] is None
    assert result["summary"] == {"passed": 6, "failed": 0}
    assert gateway.calls == 1


def test_preview_blocks_receipts_from_different_timelines(tmp_path: Path) -> None:
    workflow, gateway, _, roots = _workflow(tmp_path)
    subtitle = _subtitle()
    subtitle["timeline_id"] = "other-timeline"
    _write(roots["subtitles"], SUBTITLE_ID, subtitle)

    result = workflow.preview(**_ids())

    assert result["status"] == "blocked"
    assert result["summary"]["failed"] == 6
    assert gateway.calls == 0


def test_start_requires_confirmation(tmp_path: Path) -> None:
    workflow, _, _, _ = _workflow(tmp_path)

    with pytest.raises(BaselineEditError, match="confirm_render"):
        workflow.start(
            **_ids(),
            custom_name="Baseline",
            profile="youtube-1080p-h264-v1",
            confirm_render=False,
        )


def test_start_is_deterministic_and_replay_safe(tmp_path: Path) -> None:
    workflow, _, services, _ = _workflow(tmp_path)
    arguments: dict[str, Any] = {
        **_ids(),
        "custom_name": "Baseline",
        "profile": "youtube-1080p-h264-v1",
        "confirm_render": True,
    }

    first = workflow.start(**arguments)
    second = workflow.start(**arguments)

    assert first == second
    assert first["status"] == "started"
    assert first["render"]["custom_name"].startswith("Baseline-")
    assert len(first["render"]["custom_name"].rsplit("-", 1)[1]) == 12
    assert services["preparer"].calls == 1
    assert services["executor"].start_calls == 1


def test_status_requires_complete_render_and_fresh_qa(tmp_path: Path) -> None:
    workflow, gateway, _, _ = _workflow(tmp_path)
    receipt = workflow.start(
        **_ids(),
        custom_name="Baseline",
        profile="youtube-2160p-h264-v1",
        confirm_render=True,
    )

    result = workflow.status(receipt["receipt_id"])

    assert result["status"] == "complete"
    assert result["qa"]["status"] == "ready"
    assert gateway.calls == 4


def test_preview_rejects_missing_receipt(tmp_path: Path) -> None:
    workflow, _, _, roots = _workflow(tmp_path)
    (roots["visual"] / f"{VISUAL_ID}.json").unlink()

    with pytest.raises(BaselineEditError, match="visual receipt was not found"):
        workflow.preview(**_ids())


def _workflow(
    tmp_path: Path,
) -> tuple[
    BaselineEditWorkflow,
    FakeGateway,
    dict[str, Any],
    dict[str, Path],
]:
    roots = {
        "finalizations": tmp_path / "finalizations",
        "audio": tmp_path / "audio",
        "subtitles": tmp_path / "subtitles",
        "visual": tmp_path / "visual",
        "runs": tmp_path / "runs",
    }
    _write(roots["finalizations"], FINALIZATION_ID, _finalization())
    _write(roots["audio"], AUDIO_ID, _audio())
    _write(roots["subtitles"], SUBTITLE_ID, _subtitle())
    _write(roots["visual"], VISUAL_ID, _visual())
    gateway = FakeGateway()
    preparer = FakePreparer()
    executor = FakeExecutor()
    workflow = BaselineEditWorkflow(
        gateway=gateway,
        render_preparer=preparer,
        render_executor=executor,
        finalizations_root=roots["finalizations"],
        audio_integrations_root=roots["audio"],
        subtitle_receipts_root=roots["subtitles"],
        visual_treatments_root=roots["visual"],
        runs_root=roots["runs"],
    )
    return workflow, gateway, {"preparer": preparer, "executor": executor}, roots


def _ids() -> ReceiptIds:
    return {
        "finalization_receipt_id": FINALIZATION_ID,
        "audio_integration_receipt_id": AUDIO_ID,
        "subtitle_receipt_id": SUBTITLE_ID,
        "visual_treatment_receipt_id": VISUAL_ID,
    }


def _item(
    item_id: str,
    track_type: str,
    track_index: int,
    start: int,
    end: int,
) -> dict[str, Any]:
    return {
        "timeline_item_id": item_id,
        "name": item_id,
        "track_type": track_type,
        "track_index": track_index,
        "timeline_start_frame": start,
        "timeline_end_frame": end,
        "duration_frames": end - start,
    }


def _finalization() -> dict[str, Any]:
    item = _item("video", "video", 1, 0, 100)
    return {
        "finalization_version": "1.0",
        "receipt_id": FINALIZATION_ID,
        "status": "applied",
        "inputs": {
            "pause_compaction_receipt_id": "1" * 64,
            "picture_in_picture_receipt_id": "2" * 64,
            "synchronized_link_receipt_id": "3" * 64,
        },
        "target": {
            "synchronized_pair_receipt_id": "4" * 64,
            "timeline_id": TIMELINE_ID,
            "timeline_name": "Final",
        },
        "link_groups": [["video", "audio-source"]],
        "webcam_item_ids": ["video"],
        "transform": {"position_x": 0, "position_y": 0, "zoom": 0.25},
        "operations": [
            {"operation": "set_clip_link_groups", "status": "applied", "result": {}},
            {"operation": "set_clip_transforms", "status": "applied", "result": {}},
        ],
        "readback": {"timeline_id": TIMELINE_ID, "items": [item]},
    }


def _audio() -> dict[str, Any]:
    items = [
        _item("video", "video", 1, 0, 100),
        _item("audio-source", "audio", 1, 0, 100),
        _item("audio-clean", "audio", 2, 0, 100),
    ]
    return {
        "audio_integration_version": "1.0",
        "receipt_id": AUDIO_ID,
        "status": "applied",
        "inputs": {"extraction_receipt_id": "5" * 64, "audio_report_id": "6" * 64},
        "target": {
            "timeline_id": TIMELINE_ID,
            "timeline_name": "Final",
            "timeline_start_frame": 0,
            "duration_frames": 100,
            "frame_rate": 24,
            "video_track_count": 1,
        },
        "source_audio_item_ids": ["audio-source"],
        "source_video_item_ids": ["video"],
        "operations": [
            {"operation": "import_processed_audio", "status": "applied", "result": {}},
            {"operation": "ensure_audio_track_2", "status": "applied", "result": {}},
            {"operation": "insert_processed_audio", "status": "applied", "result": {}},
            {"operation": "disable_source_audio", "status": "applied", "result": {}},
        ],
        "readback": {"timeline_id": TIMELINE_ID, "items": items},
    }


def _subtitle() -> dict[str, Any]:
    return {
        "receipt_id": SUBTITLE_ID,
        "status": "applied",
        "timeline_id": TIMELINE_ID,
        "source_file": "source.wav",
        "subtitle_file": "captions.srt",
        "backend": "fake",
        "model": "small",
        "language": "uk",
        "segment_count": 1,
        "previous_subtitle_item_count": 0,
        "subtitle_item_count": 1,
        "timeline_item_ids": ["subtitle"],
        "import_result": {},
        "append_result": {},
    }


def _visual() -> dict[str, Any]:
    return {
        "visual_treatment_version": "1.0",
        "receipt_id": VISUAL_ID,
        "status": "applied",
        "inputs": {
            "timeline_id": TIMELINE_ID,
            "transforms": [{"timeline_item_id": "video", "zoom": 1.1}],
            "titles": [{"title_name": "Text", "timecode": "01:00:05:00"}],
        },
        "operations": [
            {"kind": "set_clip_transforms", "status": "applied", "result": {}},
            {
                "kind": "insert_title",
                "title_index": 0,
                "status": "applied",
                "result": {"item": _item("title", "video", 1, 100, 120)},
            },
        ],
    }


def _write(root: Path, receipt_id: str, payload: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{receipt_id}.json").write_text(json.dumps(payload), encoding="utf-8")
