"""M40 synchronized screen video/audio link tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.synchronized_link import (
    REQUIRED_CAPABILITIES,
    SynchronizedLinkError,
    SynchronizedScreenLinker,
)


class StubGateway:
    def __init__(self, *, omit_peer: bool = False) -> None:
        self.omit_peer = omit_peer
        self.calls = 0
        self.arguments: dict[str, Any] = {}

    def set_clips_linked(
        self,
        timeline_id: str,
        timeline_item_ids: list[str],
        linked: bool,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.calls += 1
        self.arguments = {
            "timeline_id": timeline_id,
            "timeline_item_ids": timeline_item_ids,
            "linked": linked,
            "timeout_seconds": timeout_seconds,
            "idempotency_key": idempotency_key,
        }
        return {
            "timeline_id": timeline_id,
            "linked": linked,
            "items": [
                {
                    "timeline_item_id": item_id,
                    "linked_item_ids": (
                        []
                        if self.omit_peer
                        else [
                            peer_id
                            for peer_id in timeline_item_ids
                            if peer_id != item_id
                        ]
                    ),
                }
                for item_id in timeline_item_ids
            ],
        }


def _write_pair(root: Path, receipt_id: str = "a" * 64) -> None:
    operations = []
    for operation, item_id in (
        ("create_timeline", None),
        ("ensure_timeline_tracks", None),
        ("insert_screen_video", "screen-video"),
        ("insert_screen_audio", "screen-audio"),
        ("insert_webcam_video", "webcam-video"),
    ):
        operations.append(
            {
                "operation": operation,
                "status": "applied",
                "result": (
                    {} if item_id is None else {"item": {"timeline_item_id": item_id}}
                ),
            }
        )
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
        "operations": operations,
        "readback": {},
    }
    (root / f"{receipt_id}.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )


def _capabilities() -> dict[str, bool]:
    return {name: True for name in REQUIRED_CAPABILITIES}


def test_link_uses_only_m38_screen_items_and_replays(tmp_path: Path) -> None:
    pairs = tmp_path / "pairs"
    links = tmp_path / "links"
    pairs.mkdir()
    _write_pair(pairs)
    gateway = StubGateway()
    linker = SynchronizedScreenLinker(
        gateway=gateway,
        capabilities=_capabilities,
        synchronized_pairs_root=pairs,
        receipts_root=links,
    )

    result = linker.link(
        synchronized_pair_receipt_id="a" * 64,
        confirm_link=True,
        timeout_seconds=45,
    )
    replay = linker.link(
        synchronized_pair_receipt_id="a" * 64,
        confirm_link=True,
        timeout_seconds=45,
    )

    assert result["status"] == "applied"
    assert result["source"] == {
        "timeline_id": "timeline-38",
        "screen_video_timeline_item_id": "screen-video",
        "screen_audio_timeline_item_id": "screen-audio",
    }
    assert replay == result
    assert gateway.calls == 1
    assert gateway.arguments["timeline_item_ids"] == [
        "screen-video",
        "screen-audio",
    ]
    assert gateway.arguments["linked"] is True
    assert gateway.arguments["idempotency_key"].endswith(":screen-pair")


def test_link_requires_confirmation_receipt_and_capability(tmp_path: Path) -> None:
    pairs = tmp_path / "pairs"
    pairs.mkdir()
    _write_pair(pairs)
    linker = SynchronizedScreenLinker(
        gateway=StubGateway(),
        capabilities=lambda: {},
        synchronized_pairs_root=pairs,
        receipts_root=tmp_path / "links",
    )

    with pytest.raises(SynchronizedLinkError, match="confirm_link"):
        linker.link(
            synchronized_pair_receipt_id="a" * 64,
            confirm_link=False,
        )
    with pytest.raises(SynchronizedLinkError, match="not found"):
        linker.link(
            synchronized_pair_receipt_id="b" * 64,
            confirm_link=True,
        )
    with pytest.raises(SynchronizedLinkError, match="not verified"):
        linker.link(
            synchronized_pair_receipt_id="a" * 64,
            confirm_link=True,
        )


def test_link_rejects_missing_mutual_readback(tmp_path: Path) -> None:
    pairs = tmp_path / "pairs"
    pairs.mkdir()
    _write_pair(pairs)
    linker = SynchronizedScreenLinker(
        gateway=StubGateway(omit_peer=True),
        capabilities=_capabilities,
        synchronized_pairs_root=pairs,
        receipts_root=tmp_path / "links",
    )

    with pytest.raises(SynchronizedLinkError, match="mutual link"):
        linker.link(
            synchronized_pair_receipt_id="a" * 64,
            confirm_link=True,
        )


def test_link_rejects_invalid_timeout(tmp_path: Path) -> None:
    pairs = tmp_path / "pairs"
    pairs.mkdir()
    _write_pair(pairs)
    linker = SynchronizedScreenLinker(
        gateway=StubGateway(),
        capabilities=_capabilities,
        synchronized_pairs_root=pairs,
        receipts_root=tmp_path / "links",
    )

    with pytest.raises(SynchronizedLinkError, match="timeout_seconds"):
        linker.link(
            synchronized_pair_receipt_id="a" * 64,
            confirm_link=True,
            timeout_seconds=0,
        )
