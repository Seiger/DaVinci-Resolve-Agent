"""Tests for M51 B-roll planning and bounded application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.broll import BrollError, BrollWorkflow

BASELINE_ID = "a" * 64
SOURCE_ID = "timeline-source"
TARGET_ID = "timeline-target"
ASSET_ID = "broll-asset"


class StubBaseline:
    def __init__(self, *, complete: bool = True) -> None:
        self.complete = complete

    def status(self, receipt_id: str, **kwargs: Any) -> dict[str, Any]:
        assert receipt_id == BASELINE_ID
        return {
            "status": "complete" if self.complete else "in_progress",
            "target": {
                "timeline_id": SOURCE_ID,
                "timeline_name": "M50 Source",
            },
        }


class StubGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.inserted: list[dict[str, Any]] = []

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append("editing_metadata")
        assert timeline_id == SOURCE_ID
        assert asset_ids == [ASSET_ID]
        return {
            "timeline": {
                "timeline_id": SOURCE_ID,
                "name": "M50 Source",
                "video_track_count": 2,
                "audio_track_count": 2,
                "frame_rate": 24.0,
            },
            "assets": [
                {
                    "asset_id": ASSET_ID,
                    "name": "detail.mp4",
                    "duration_frames": 240,
                    "frame_rate": 24.0,
                }
            ],
        }

    def timeline_items(self, timeline_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("timeline_items")
        base = [
            _item("screen", "screen", 1, 86400, 86640, 0, 239),
            _item("webcam", "webcam", 2, 86400, 86640, 0, 239),
        ]
        inserted_readback = [
            {
                key: value
                for key, value in item.items()
                if key not in {"asset_id", "placement_index"}
            }
            for item in self.inserted
        ]
        return {
            "timeline_id": timeline_id,
            "name": "M50 Source" if timeline_id == SOURCE_ID else "M51 B-roll",
            "items": base + (inserted_readback if timeline_id == TARGET_ID else []),
        }

    def duplicate_timeline(
        self, timeline_id: str, name: str, **kwargs: Any
    ) -> dict[str, Any]:
        self.calls.append("duplicate_timeline")
        return {
            "source_timeline": {"timeline_id": timeline_id, "name": "M50 Source"},
            "timeline": {"timeline_id": TARGET_ID, "name": name},
        }

    def ensure_timeline_tracks(
        self, timeline_id: str, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        self.calls.append("ensure_timeline_tracks")
        assert timeline_id == TARGET_ID
        return {
            "timeline_id": TARGET_ID,
            "video_track_count": 3,
            "audio_track_count": 2,
        }

    def insert_clips(
        self,
        timeline_id: str,
        placements: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append("insert_clips")
        assert timeline_id == TARGET_ID
        self.inserted = [
            _item(
                f"broll-{index}",
                placement["asset_id"],
                placement["track_index"],
                86400 + placement["position_frames"],
                86400 + placement["position_frames"] + 48,
                placement["source_start_frame"],
                placement["source_end_frame"],
                placement_index=index,
            )
            for index, placement in enumerate(placements)
        ]
        return {"timeline_id": TARGET_ID, "items": self.inserted}


def test_preview_builds_deterministic_review_plan(tmp_path: Path) -> None:
    workflow, gateway = _workflow(tmp_path)

    first = workflow.preview(**_arguments())
    second = workflow.preview(**_arguments())

    assert first == second
    assert first["status"] == "preview"
    assert first["apply_supported"] is True
    assert first["placements"][0]["timeline_duration_frames"] == 48
    assert first["placements"][0]["timeline_end_position_frames"] == 72
    assert gateway.calls == [
        "timeline_items",
        "editing_metadata",
        "timeline_items",
        "editing_metadata",
    ]


def test_preview_rejects_same_track_overlap(tmp_path: Path) -> None:
    workflow, _ = _workflow(tmp_path)
    placements = _placements() + [
        {
            **_placements()[0],
            "source_start_frame": 60,
            "source_end_frame": 107,
            "position_frames": 48,
        }
    ]

    with pytest.raises(BrollError, match="overlap"):
        workflow.preview(**{**_arguments(), "placements": placements})


def test_preview_requires_completed_baseline(tmp_path: Path) -> None:
    workflow, _ = _workflow(tmp_path, baseline=StubBaseline(complete=False))

    with pytest.raises(BrollError, match="completed M50"):
        workflow.preview(**_arguments())


def test_apply_requires_confirmation_and_exact_plan_id(tmp_path: Path) -> None:
    workflow, _ = _workflow(tmp_path)
    plan = workflow.preview(**_arguments())

    with pytest.raises(BrollError, match="confirm_apply"):
        workflow.apply(
            **_arguments(),
            expected_plan_id=plan["plan_id"],
            confirm_apply=False,
        )
    with pytest.raises(BrollError, match="expected_plan_id"):
        workflow.apply(
            **_arguments(),
            expected_plan_id="f" * 64,
            confirm_apply=True,
        )


def test_apply_duplicates_inserts_and_replays_exact_receipt(tmp_path: Path) -> None:
    workflow, gateway = _workflow(tmp_path)
    plan = workflow.preview(**_arguments())
    arguments = {
        **_arguments(),
        "expected_plan_id": plan["plan_id"],
        "confirm_apply": True,
    }

    first = workflow.apply(**arguments)
    calls_after_first = list(gateway.calls)
    second = workflow.apply(**arguments)

    assert first == second
    assert first["status"] == "applied"
    assert first["target"] == {
        "timeline_id": TARGET_ID,
        "timeline_name": "M51 B-roll",
    }
    assert len(first["inserted_items"]) == 1
    assert gateway.calls == calls_after_first + [
        "timeline_items",
        "editing_metadata",
    ]
    assert calls_after_first[-4:] == [
        "duplicate_timeline",
        "ensure_timeline_tracks",
        "insert_clips",
        "timeline_items",
    ]


def test_apply_blocks_unverified_write_capability(tmp_path: Path) -> None:
    capabilities = _capabilities()
    capabilities["timeline.duplicate"] = False
    workflow, gateway = _workflow(tmp_path, capabilities=capabilities)
    plan = workflow.preview(**_arguments())

    assert plan["apply_supported"] is False
    with pytest.raises(BrollError, match="timeline.duplicate"):
        workflow.apply(
            **_arguments(),
            expected_plan_id=plan["plan_id"],
            confirm_apply=True,
        )
    assert "duplicate_timeline" not in gateway.calls


def _workflow(
    tmp_path: Path,
    *,
    baseline: StubBaseline | None = None,
    capabilities: dict[str, bool] | None = None,
) -> tuple[BrollWorkflow, StubGateway]:
    gateway = StubGateway()
    capability_values = _capabilities() if capabilities is None else capabilities
    return (
        BrollWorkflow(
            gateway=gateway,
            baseline=baseline or StubBaseline(),
            capabilities=lambda: capability_values,
            receipts_root=tmp_path / "broll",
        ),
        gateway,
    )


def _arguments() -> dict[str, Any]:
    return {
        "baseline_edit_receipt_id": BASELINE_ID,
        "target_timeline_name": "M51 B-roll",
        "placements": _placements(),
        "timeout_seconds": 20,
    }


def _placements() -> list[dict[str, Any]]:
    return [
        {
            "asset_id": ASSET_ID,
            "source_start_frame": 0,
            "source_end_frame": 47,
            "position_frames": 24,
            "track_index": 3,
            "purpose": "Показати деталь інтерфейсу",
        }
    ]


def _capabilities() -> dict[str, bool]:
    return {
        "clip.range_insert": True,
        "clip.read": True,
        "media.metadata.read": True,
        "timeline.duplicate": True,
        "timeline.track.create": True,
    }


def _item(
    item_id: str,
    asset_id: str,
    track_index: int,
    start: int,
    end: int,
    source_start: int,
    source_end: int,
    *,
    placement_index: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "timeline_item_id": item_id,
        "asset_id": asset_id,
        "name": item_id,
        "track_type": "video",
        "track_index": track_index,
        "timeline_start_frame": start,
        "timeline_end_frame": end,
        "source_start_frame": source_start,
        "source_end_frame": source_end,
    }
    if placement_index is not None:
        result["placement_index"] = placement_index
    return result
