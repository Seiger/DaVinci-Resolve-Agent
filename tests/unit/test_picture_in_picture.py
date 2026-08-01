"""M39 synchronized webcam picture-in-picture tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.picture_in_picture import (
    REQUIRED_CAPABILITIES,
    PictureInPictureComposer,
    PictureInPictureError,
)


class StubGateway:
    def __init__(self) -> None:
        self.metadata_calls = 0
        self.transform_calls = 0
        self.arguments: dict[str, Any] = {}

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.metadata_calls += 1
        return {
            "timeline": {
                "timeline_id": timeline_id,
                "resolution_width": 1920,
                "resolution_height": 1080,
            },
            "assets": [{"asset_id": asset_ids[0]}],
        }

    def set_clip_transform(
        self,
        timeline_id: str,
        timeline_item_id: str,
        *,
        position_x: float | None = None,
        position_y: float | None = None,
        zoom: float | None = None,
        rotation_degrees: float | None = None,
        opacity_percent: float | None = None,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.transform_calls += 1
        self.arguments = {
            "timeline_id": timeline_id,
            "timeline_item_id": timeline_item_id,
            "position_x": position_x,
            "position_y": position_y,
            "zoom": zoom,
            "timeout_seconds": timeout_seconds,
            "idempotency_key": idempotency_key,
        }
        return {
            "timeline_id": timeline_id,
            "timeline_item_id": timeline_item_id,
            "properties": {
                "Pan": position_x,
                "Tilt": position_y,
                "ZoomGang": True,
                "ZoomX": zoom,
                "ZoomY": zoom,
            },
        }


def _write_pair(root: Path, receipt_id: str = "a" * 64) -> None:
    receipt = {
        "sync_version": "1.0",
        "receipt_id": receipt_id,
        "status": "applied",
        "inputs": {
            "timeline_name": "M38",
            "screen_asset_id": "screen",
            "webcam_asset_id": "webcam",
            "webcam_offset_ms": 0,
        },
        "timeline": {"timeline_id": "timeline-38", "name": "M38"},
        "timeline_frame_rate": 24.0,
        "placements": [
            {
                "role": role,
                "asset_id": "webcam" if role == "webcam_video" else "screen",
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
                "result": (
                    {
                        "item": {
                            "timeline_item_id": "webcam-item",
                        }
                    }
                    if operation == "insert_webcam_video"
                    else {}
                ),
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
    (root / f"{receipt_id}.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )


def _capabilities() -> dict[str, bool]:
    return {name: True for name in REQUIRED_CAPABILITIES}


def test_compose_applies_normalized_transform_and_replays(tmp_path: Path) -> None:
    pairs = tmp_path / "pairs"
    layouts = tmp_path / "layouts"
    pairs.mkdir()
    _write_pair(pairs)
    gateway = StubGateway()
    composer = PictureInPictureComposer(
        gateway=gateway,
        capabilities=_capabilities,
        synchronized_pairs_root=pairs,
        receipts_root=layouts,
    )

    result = composer.compose(
        synchronized_pair_receipt_id="a" * 64,
        size_percent=25,
        center_x_percent=82,
        center_y_percent=82,
        confirm_layout=True,
        timeout_seconds=45,
    )
    replay = composer.compose(
        synchronized_pair_receipt_id="a" * 64,
        size_percent=25,
        center_x_percent=82,
        center_y_percent=82,
        confirm_layout=True,
        timeout_seconds=45,
    )

    assert result["status"] == "applied"
    assert result["timeline_resolution"] == {"width": 1920, "height": 1080}
    assert result["transform"] == {
        "position_x": pytest.approx(614.4),
        "position_y": pytest.approx(-345.6),
        "zoom": 0.25,
    }
    assert replay == result
    assert gateway.metadata_calls == 1
    assert gateway.transform_calls == 1
    assert gateway.arguments["timeline_item_id"] == "webcam-item"
    assert gateway.arguments["idempotency_key"].endswith(":webcam-layout")


def test_compose_requires_confirmation_receipt_and_capabilities(
    tmp_path: Path,
) -> None:
    pairs = tmp_path / "pairs"
    pairs.mkdir()
    _write_pair(pairs)
    composer = PictureInPictureComposer(
        gateway=StubGateway(),
        capabilities=lambda: {},
        synchronized_pairs_root=pairs,
        receipts_root=tmp_path / "layouts",
    )

    with pytest.raises(PictureInPictureError, match="confirm_layout"):
        composer.compose(
            synchronized_pair_receipt_id="a" * 64,
            size_percent=25,
            center_x_percent=82,
            center_y_percent=82,
            confirm_layout=False,
        )
    with pytest.raises(PictureInPictureError, match="not found"):
        composer.compose(
            synchronized_pair_receipt_id="b" * 64,
            size_percent=25,
            center_x_percent=82,
            center_y_percent=82,
            confirm_layout=True,
        )
    with pytest.raises(PictureInPictureError, match="not verified"):
        composer.compose(
            synchronized_pair_receipt_id="a" * 64,
            size_percent=25,
            center_x_percent=82,
            center_y_percent=82,
            confirm_layout=True,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("size_percent", 9),
        ("center_x_percent", 101),
        ("center_y_percent", -1),
        ("timeout_seconds", 0),
    ],
)
def test_compose_rejects_out_of_bounds_values(
    tmp_path: Path, field: str, value: float
) -> None:
    pairs = tmp_path / "pairs"
    pairs.mkdir()
    _write_pair(pairs)
    composer = PictureInPictureComposer(
        gateway=StubGateway(),
        capabilities=_capabilities,
        synchronized_pairs_root=pairs,
        receipts_root=tmp_path / "layouts",
    )
    arguments: dict[str, Any] = {
        "synchronized_pair_receipt_id": "a" * 64,
        "size_percent": 25,
        "center_x_percent": 82,
        "center_y_percent": 82,
        "confirm_layout": True,
        "timeout_seconds": 30,
    }
    arguments[field] = value

    with pytest.raises(PictureInPictureError, match=field):
        composer.compose(**arguments)
