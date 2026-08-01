"""M38 synchronized screen/webcam assembly tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.synchronized_pair import (
    REQUIRED_CAPABILITIES,
    SynchronizedPairAssembler,
    SynchronizedPairError,
    _milliseconds_to_frames,
)


class StubGateway:
    def __init__(self, fail_once_at: str | None = None) -> None:
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
        return {"timeline": {"timeline_id": "timeline-38", "name": name}}

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self._record("editing_metadata")
        return {
            "timeline": {"timeline_id": timeline_id, "frame_rate": 24.0},
            "assets": [
                {
                    "asset_id": asset_ids[0],
                    "duration_frames": 600,
                    "frame_rate": 60.0,
                },
                {
                    "asset_id": asset_ids[1],
                    "duration_frames": 480,
                    "frame_rate": 60.0,
                },
            ],
        }

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

    def insert_clip(
        self,
        timeline_id: str,
        asset_id: str,
        source_start_frame: int,
        source_end_frame: int,
        position_frames: int,
        track_type: str,
        track_index: int,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        role = idempotency_key.rsplit(":", 1)[-1]
        self._record(role)
        item = {
            "timeline_item_id": f"item-{role}",
            "track_type": track_type,
            "track_index": track_index,
            "timeline_start_frame": position_frames,
            "source_start_frame": source_start_frame,
            "source_end_frame": source_end_frame,
        }
        self.items.append(item)
        return {"timeline_id": timeline_id, "asset_id": asset_id, "item": item}

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self._record("timeline_items")
        return {"timeline_id": timeline_id, "items": list(self.items)}


def _capabilities() -> dict[str, bool]:
    return {name: True for name in REQUIRED_CAPABILITIES}


def test_assemble_places_screen_video_audio_and_offset_webcam(
    tmp_path: Path,
) -> None:
    gateway = StubGateway()
    assembler = SynchronizedPairAssembler(
        gateway=gateway,
        capabilities=_capabilities,
        receipts_root=tmp_path,
    )

    result = assembler.assemble(
        timeline_name="M38 Synced Pair",
        screen_asset_id="screen",
        webcam_asset_id="webcam",
        webcam_offset_ms=200,
        confirm_sync=True,
    )
    replay = assembler.assemble(
        timeline_name="M38 Synced Pair",
        screen_asset_id="screen",
        webcam_asset_id="webcam",
        webcam_offset_ms=200,
        confirm_sync=True,
    )

    assert result["status"] == "applied"
    assert result["timeline_frame_rate"] == 24.0
    assert [placement["position_frames"] for placement in result["placements"]] == [
        0,
        0,
        5,
    ]
    assert [placement["track_type"] for placement in result["placements"]] == [
        "video",
        "audio",
        "video",
    ]
    assert [placement["track_index"] for placement in result["placements"]] == [
        1,
        1,
        2,
    ]
    assert [
        placement["source_end_frame"] for placement in result["placements"]
    ] == [599, 599, 479]
    assert replay == result
    assert gateway.calls.count("create_timeline") == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_partial_receipt_resumes_without_repeating_completed_steps(
    tmp_path: Path,
) -> None:
    gateway = StubGateway(fail_once_at="screen_audio")
    assembler = SynchronizedPairAssembler(
        gateway=gateway,
        capabilities=_capabilities,
        receipts_root=tmp_path,
    )
    def assemble() -> dict[str, Any]:
        return assembler.assemble(
            timeline_name="M38 Resume",
            screen_asset_id="screen",
            webcam_asset_id="webcam",
            webcam_offset_ms=-200,
            confirm_sync=True,
        )

    with pytest.raises(RuntimeError, match="simulated interruption"):
        assemble()
    result = assemble()

    assert result["status"] == "applied"
    assert gateway.calls.count("create_timeline") == 1
    assert gateway.calls.count("screen_video") == 1
    assert gateway.calls.count("screen_audio") == 2
    assert [placement["position_frames"] for placement in result["placements"]] == [
        5,
        5,
        0,
    ]


def test_sync_requires_confirmation_distinct_assets_and_capabilities(
    tmp_path: Path,
) -> None:
    assembler = SynchronizedPairAssembler(
        gateway=StubGateway(),
        capabilities=lambda: {},
        receipts_root=tmp_path,
    )
    with pytest.raises(SynchronizedPairError, match="confirm_sync"):
        assembler.assemble(
            timeline_name="M38",
            screen_asset_id="screen",
            webcam_asset_id="webcam",
            webcam_offset_ms=0,
            confirm_sync=False,
        )
    with pytest.raises(SynchronizedPairError, match="must differ"):
        assembler.assemble(
            timeline_name="M38",
            screen_asset_id="same",
            webcam_asset_id="same",
            webcam_offset_ms=0,
            confirm_sync=True,
        )
    with pytest.raises(SynchronizedPairError, match="not verified"):
        assembler.assemble(
            timeline_name="M38",
            screen_asset_id="screen",
            webcam_asset_id="webcam",
            webcam_offset_ms=0,
            confirm_sync=True,
        )


def test_millisecond_conversion_uses_nearest_target_frame() -> None:
    assert _milliseconds_to_frames(200, 24.0) == 5
    assert _milliseconds_to_frames(20, 24.0) == 0
    assert _milliseconds_to_frames(21, 24.0) == 1


def test_sync_rejects_unsafe_timeout(tmp_path: Path) -> None:
    assembler = SynchronizedPairAssembler(
        gateway=StubGateway(),
        capabilities=_capabilities,
        receipts_root=tmp_path,
    )

    with pytest.raises(SynchronizedPairError, match="timeout_seconds"):
        assembler.assemble(
            timeline_name="M38",
            screen_asset_id="screen",
            webcam_asset_id="webcam",
            webcam_offset_ms=0,
            confirm_sync=True,
            timeout_seconds=0,
        )
