"""M42 confirmed pause-compaction apply tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.pause_compaction import (
    APPLY_CAPABILITIES,
    PauseCompactionApplier,
    PauseCompactionError,
)


class StubPreviewer:
    def __init__(self) -> None:
        self.calls = 0

    def preview(
        self,
        *,
        plan_id: str,
        synchronized_pair_receipt_id: str,
        target_timeline_name: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.calls += 1
        placements = [
            {
                "segment_index": 0,
                "role": role,
                "asset_id": "webcam" if role == "webcam_video" else "screen",
                "track_type": "audio" if role == "screen_audio" else "video",
                "track_index": 2 if role == "webcam_video" else 1,
                "source_start_frame": 10,
                "source_end_frame": 109,
                "position_frames": 5 if role == "webcam_video" else 0,
                "source_frame_rate": 60.0,
            }
            for role in ("screen_video", "screen_audio", "webcam_video")
        ]
        return {
            "preview_version": "1.0",
            "status": "preview",
            "apply_supported": True,
            "plan_id": plan_id,
            "plan_sha256": "c" * 64,
            "synchronized_pair_receipt_id": synchronized_pair_receipt_id,
            "target_timeline_name": target_timeline_name,
            "timeline": {
                "frame_rate": 24.0,
                "source_duration_ms": 2000,
                "removed_duration_ms": 500,
                "output_duration_ms": 1500,
                "output_duration_frames": 36,
            },
            "cuts": [
                {"start_ms": 1000, "end_ms": 1500, "duration_ms": 500}
            ],
            "kept_intervals": [
                {
                    "start_ms": 0,
                    "end_ms": 1000,
                    "duration_ms": 1000,
                    "output_start_ms": 0,
                },
                {
                    "start_ms": 1500,
                    "end_ms": 2000,
                    "duration_ms": 500,
                    "output_start_ms": 1000,
                },
            ],
            "placements": placements,
            "required_capabilities": list(APPLY_CAPABILITIES),
            "unsupported_capabilities": [],
        }


class StubGateway:
    def __init__(self, *, fail_once_at: str | None = None) -> None:
        self.fail_once_at = fail_once_at
        self.failed = False
        self.calls: list[str] = []
        self.items: list[dict[str, Any]] = []

    def _record(self, operation: str) -> None:
        self.calls.append(operation)
        if self.fail_once_at == operation and not self.failed:
            self.failed = True
            raise RuntimeError("simulated interruption")

    def create_timeline(
        self,
        name: str,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._record("create_timeline")
        return {"timeline": {"timeline_id": "timeline-42", "name": name}}

    def ensure_timeline_tracks(
        self,
        timeline_id: str,
        video_track_count: int,
        audio_track_count: int,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._record("ensure_timeline_tracks")
        return {"timeline": {"timeline_id": timeline_id}}

    def insert_clips(
        self,
        timeline_id: str,
        placements: list[dict[str, Any]],
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._record("insert_clips")
        self.items = [
            {
                "placement_index": index,
                "asset_id": placement["asset_id"],
                "timeline_item_id": f"item-{index}",
                "name": placement["asset_id"],
                "timeline_start_frame": 86_400 + placement["position_frames"],
                "timeline_end_frame": 86_500 + placement["position_frames"],
                "source_start_frame": placement["source_start_frame"],
                "source_end_frame": placement["source_end_frame"],
                "track_type": placement["track_type"],
                "track_index": placement["track_index"],
            }
            for index, placement in enumerate(placements)
        ]
        return {"timeline_id": timeline_id, "items": self.items}

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self._record("timeline_items")
        return {
            "timeline_id": timeline_id,
            "items": [
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"placement_index", "asset_id"}
                }
                for item in self.items
            ],
        }

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        raise AssertionError("The stub previewer supplies metadata.")


def _capabilities() -> dict[str, bool]:
    return {name: True for name in APPLY_CAPABILITIES}


def _apply(
    applier: PauseCompactionApplier,
    *,
    confirm_apply: bool = True,
) -> dict[str, Any]:
    return applier.apply(
        plan_id="a" * 64,
        synchronized_pair_receipt_id="b" * 64,
        target_timeline_name="M42 Compacted",
        confirm_apply=confirm_apply,
        timeout_seconds=45,
    )


def test_apply_creates_tracks_and_batch_inserts_with_durable_replay(
    tmp_path: Path,
) -> None:
    gateway = StubGateway()
    previewer = StubPreviewer()
    applier = PauseCompactionApplier(
        gateway=gateway,
        capabilities=_capabilities,
        previewer=previewer,
        receipts_root=tmp_path,
    )

    result = _apply(applier)
    calls_after_apply = list(gateway.calls)
    replay = _apply(applier)

    assert result["status"] == "applied"
    assert result["placement_count"] == 3
    assert result["timeline"] == {
        "timeline_id": "timeline-42",
        "name": "M42 Compacted",
    }
    assert calls_after_apply == [
        "create_timeline",
        "ensure_timeline_tracks",
        "insert_clips",
        "timeline_items",
    ]
    assert gateway.calls == calls_after_apply
    assert replay == result
    assert previewer.calls == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_apply_resumes_after_interrupted_batch_without_repeating_prior_steps(
    tmp_path: Path,
) -> None:
    gateway = StubGateway(fail_once_at="insert_clips")
    applier = PauseCompactionApplier(
        gateway=gateway,
        capabilities=_capabilities,
        previewer=StubPreviewer(),
        receipts_root=tmp_path,
    )

    with pytest.raises(RuntimeError, match="simulated interruption"):
        _apply(applier)
    result = _apply(applier)

    assert result["status"] == "applied"
    assert gateway.calls == [
        "create_timeline",
        "ensure_timeline_tracks",
        "insert_clips",
        "insert_clips",
        "timeline_items",
    ]


def test_apply_requires_confirmation_and_verified_capabilities(
    tmp_path: Path,
) -> None:
    gateway = StubGateway()
    previewer = StubPreviewer()
    without_confirmation = PauseCompactionApplier(
        gateway=gateway,
        capabilities=_capabilities,
        previewer=previewer,
        receipts_root=tmp_path,
    )
    with pytest.raises(PauseCompactionError, match="confirm_apply"):
        _apply(without_confirmation, confirm_apply=False)

    unsupported = PauseCompactionApplier(
        gateway=gateway,
        capabilities=lambda: {},
        previewer=previewer,
        receipts_root=tmp_path,
    )
    with pytest.raises(PauseCompactionError, match="not verified"):
        _apply(unsupported)

    assert gateway.calls == []
    assert previewer.calls == 0
