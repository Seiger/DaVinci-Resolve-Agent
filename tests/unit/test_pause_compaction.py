"""M41 pause-compaction preview tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.pause_compaction import (
    PauseCompactionError,
    PauseCompactionPreviewer,
    _canonical_sha256,
)


class StubInspector:
    def __init__(self, plan: dict[str, Any], *, approved: bool = True) -> None:
        self.plan = plan
        self.approved = approved

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        assert plan_id == self.plan["plan_id"]
        return {
            "plan": self.plan,
            "approval": (
                {
                    "status": "approved",
                    "plan_sha256": _canonical_sha256(self.plan),
                }
                if self.approved
                else None
            ),
        }


class StubGateway:
    def __init__(self, *, webcam_name: str = "webcam.mkv") -> None:
        self.webcam_name = webcam_name
        self.calls: list[dict[str, Any]] = []

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "timeline_id": timeline_id,
                "asset_ids": asset_ids,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {
            "timeline": {"timeline_id": timeline_id, "frame_rate": 24.0},
            "assets": [
                {
                    "asset_id": asset_ids[0],
                    "name": "screen.mkv",
                    "duration_frames": 600,
                    "frame_rate": 60.0,
                },
                {
                    "asset_id": asset_ids[1],
                    "name": self.webcam_name,
                    "duration_frames": 540,
                    "frame_rate": 60.0,
                },
            ],
        }


def _plan(*, offset_ms: int = 0) -> dict[str, Any]:
    plan = {
        "plan_id": "a" * 64,
        "inputs": {
            "screen_file": r"G:\source\screen.mkv",
            "webcam_file": r"G:\source\webcam.mkv",
        },
        "synchronization": {"webcam_offset_ms": offset_ms},
        "pause_analysis": {
            "proposed_cuts": [
                {"start_ms": 2000, "end_ms": 3000, "duration_ms": 1000}
            ]
        },
    }
    return plan


def _write_pair(root: Path, *, offset_ms: int = 0) -> None:
    receipt = {
        "sync_version": "1.0",
        "receipt_id": "b" * 64,
        "status": "applied",
        "inputs": {
            "timeline_name": "M38",
            "screen_asset_id": "screen-id",
            "webcam_asset_id": "webcam-id",
            "webcam_offset_ms": offset_ms,
        },
        "timeline": {"timeline_id": "timeline-38", "name": "M38"},
        "timeline_frame_rate": 24.0,
        "placements": [
            {
                "role": role,
                "asset_id": (
                    "webcam-id" if role == "webcam_video" else "screen-id"
                ),
                "track_type": "audio" if role == "screen_audio" else "video",
                "track_index": 2 if role == "webcam_video" else 1,
                "source_start_frame": 0,
                "source_end_frame": 100,
                "position_frames": 0,
            }
            for role in ("screen_video", "screen_audio", "webcam_video")
        ],
        "operations": [
            {
                "operation": operation,
                "status": "applied",
                "result": {},
            }
            for operation in (
                "create_timeline",
                "ensure_timeline_tracks",
                "insert_screen_video",
                "insert_screen_audio",
                "insert_webcam_video",
            )
        ],
        "readback": {},
    }
    (root / f"{'b' * 64}.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )


def _capabilities() -> dict[str, bool]:
    return {
        "media.metadata.read": True,
        "clip.range_insert": True,
        "clip.read": True,
        "timeline.create": True,
        "timeline.track.create": True,
    }


def test_preview_converts_cuts_to_kept_frame_placements(tmp_path: Path) -> None:
    pairs = tmp_path / "pairs"
    pairs.mkdir()
    _write_pair(pairs)
    plan = _plan()
    gateway = StubGateway()
    previewer = PauseCompactionPreviewer(
        gateway=gateway,
        capabilities=_capabilities(),
        inspector=StubInspector(plan),
        synchronized_pairs_root=pairs,
    )

    result = previewer.preview(
        plan_id="a" * 64,
        synchronized_pair_receipt_id="b" * 64,
        target_timeline_name="M41 Compacted Preview",
        timeout_seconds=45,
    )

    assert result["status"] == "preview"
    assert result["apply_supported"] is True
    assert result["timeline"] == {
        "frame_rate": 24.0,
        "source_duration_ms": 10000,
        "removed_duration_ms": 1000,
        "output_duration_ms": 9000,
        "output_duration_frames": 216,
    }
    assert result["kept_intervals"] == [
        {
            "start_ms": 0,
            "end_ms": 2000,
            "duration_ms": 2000,
            "output_start_ms": 0,
        },
        {
            "start_ms": 3000,
            "end_ms": 10000,
            "duration_ms": 7000,
            "output_start_ms": 2000,
        },
    ]
    assert len(result["placements"]) == 6
    assert result["placements"][0] == {
        "segment_index": 0,
        "role": "screen_video",
        "asset_id": "screen-id",
        "track_type": "video",
        "track_index": 1,
        "source_start_frame": 0,
        "source_end_frame": 119,
        "position_frames": 0,
        "source_frame_rate": 60.0,
    }
    assert result["placements"][3]["source_start_frame"] == 180
    assert result["placements"][3]["source_end_frame"] == 599
    assert result["placements"][3]["position_frames"] == 48
    assert result["unsupported_capabilities"] == []
    assert gateway.calls[0]["asset_ids"] == ["screen-id", "webcam-id"]


def test_preview_preserves_positive_webcam_offset(tmp_path: Path) -> None:
    pairs = tmp_path / "pairs"
    pairs.mkdir()
    _write_pair(pairs, offset_ms=200)
    plan = _plan(offset_ms=200)
    previewer = PauseCompactionPreviewer(
        gateway=StubGateway(),
        capabilities=_capabilities(),
        inspector=StubInspector(plan),
        synchronized_pairs_root=pairs,
    )

    result = previewer.preview(
        plan_id="a" * 64,
        synchronized_pair_receipt_id="b" * 64,
        target_timeline_name="Offset Preview",
    )

    webcam = next(
        placement
        for placement in result["placements"]
        if placement["role"] == "webcam_video"
    )
    assert webcam["source_start_frame"] == 0
    assert webcam["position_frames"] == 5


def test_preview_rejects_unapproved_or_mismatched_sources(tmp_path: Path) -> None:
    pairs = tmp_path / "pairs"
    pairs.mkdir()
    _write_pair(pairs)
    plan = _plan()

    with pytest.raises(PauseCompactionError, match="approval"):
        PauseCompactionPreviewer(
            gateway=StubGateway(),
            capabilities=_capabilities(),
            inspector=StubInspector(plan, approved=False),
            synchronized_pairs_root=pairs,
        ).preview(
            plan_id="a" * 64,
            synchronized_pair_receipt_id="b" * 64,
            target_timeline_name="Preview",
        )

    with pytest.raises(PauseCompactionError, match="file name"):
        PauseCompactionPreviewer(
            gateway=StubGateway(webcam_name="other.mkv"),
            capabilities=_capabilities(),
            inspector=StubInspector(plan),
            synchronized_pairs_root=pairs,
        ).preview(
            plan_id="a" * 64,
            synchronized_pair_receipt_id="b" * 64,
            target_timeline_name="Preview",
        )


def test_preview_rejects_invalid_cuts_and_unverified_metadata(
    tmp_path: Path,
) -> None:
    pairs = tmp_path / "pairs"
    pairs.mkdir()
    _write_pair(pairs)
    plan = _plan()
    plan["pause_analysis"]["proposed_cuts"] = [
        {"start_ms": 9000, "end_ms": 11000, "duration_ms": 2000}
    ]
    previewer = PauseCompactionPreviewer(
        gateway=StubGateway(),
        capabilities=_capabilities(),
        inspector=StubInspector(plan),
        synchronized_pairs_root=pairs,
    )
    with pytest.raises(PauseCompactionError, match="in bounds"):
        previewer.preview(
            plan_id="a" * 64,
            synchronized_pair_receipt_id="b" * 64,
            target_timeline_name="Preview",
        )

    with pytest.raises(PauseCompactionError, match="metadata.read"):
        PauseCompactionPreviewer(
            gateway=StubGateway(),
            capabilities={},
            inspector=StubInspector(_plan()),
            synchronized_pairs_root=pairs,
        ).preview(
            plan_id="a" * 64,
            synchronized_pair_receipt_id="b" * 64,
            target_timeline_name="Preview",
        )
