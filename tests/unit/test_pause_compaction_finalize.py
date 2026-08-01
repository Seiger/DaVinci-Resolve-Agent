"""M43 compacted timeline finalization tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.pause_compaction_finalize import (
    REQUIRED_CAPABILITIES,
    PauseCompactionFinalizationError,
    PauseCompactionFinalizer,
)

COMPACTION_ID = "a" * 64
LAYOUT_ID = "b" * 64
LINK_ID = "c" * 64
PAIR_ID = "d" * 64


class StubGateway:
    def __init__(self, *, fail_once_at: str | None = None) -> None:
        self.fail_once_at = fail_once_at
        self.failed = False
        self.calls: list[str] = []
        self.link_groups: list[list[str]] = []
        self.transform_items: list[dict[str, Any]] = []

    def _record(self, operation: str) -> None:
        self.calls.append(operation)
        if self.fail_once_at == operation and not self.failed:
            self.failed = True
            raise RuntimeError("simulated interruption")

    def set_clip_link_groups(
        self,
        timeline_id: str,
        groups: list[list[str]],
        linked: bool,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._record("set_clip_link_groups")
        self.link_groups = groups
        return {
            "timeline_id": timeline_id,
            "linked": linked,
            "groups": [
                {
                    "group_index": group_index,
                    "items": [
                        {
                            "timeline_item_id": item_id,
                            "linked_item_ids": [
                                candidate
                                for candidate in group
                                if candidate != item_id
                            ],
                        }
                        for item_id in group
                    ],
                }
                for group_index, group in enumerate(groups)
            ],
        }

    def set_clip_transforms(
        self,
        timeline_id: str,
        items: list[dict[str, Any]],
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._record("set_clip_transforms")
        self.transform_items = items
        return {
            "timeline_id": timeline_id,
            "items": [
                {
                    "item_index": item_index,
                    "timeline_item_id": item["timeline_item_id"],
                    "properties": {
                        "Pan": item["position_x"],
                        "Tilt": item["position_y"],
                        "ZoomGang": True,
                        "ZoomX": item["zoom"],
                        "ZoomY": item["zoom"],
                    },
                }
                for item_index, item in enumerate(items)
            ],
        }

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self._record("timeline_items")
        item_ids = {
            item_id for group in self.link_groups for item_id in group
        } | {
            item["timeline_item_id"] for item in self.transform_items
        }
        return {
            "timeline_id": timeline_id,
            "items": [
                {"timeline_item_id": item_id}
                for item_id in sorted(item_ids)
            ],
        }


def _capabilities() -> dict[str, bool]:
    return {name: True for name in REQUIRED_CAPABILITIES}


def _write_receipts(
    root: Path,
    *,
    mismatched_layout: bool = False,
) -> tuple[Path, Path, Path]:
    compactions = root / "compactions"
    layouts = root / "layouts"
    links = root / "links"
    for directory in (compactions, layouts, links):
        directory.mkdir(parents=True)
    roles = (
        "screen_video",
        "screen_audio",
        "webcam_video",
        "screen_video",
        "screen_audio",
        "webcam_video",
    )
    placements = [
        {
            "segment_index": index // 3,
            "role": role,
            "asset_id": "webcam-asset" if role == "webcam_video" else "screen-asset",
        }
        for index, role in enumerate(roles)
    ]
    inserted_items = [
        {
            "placement_index": index,
            "timeline_item_id": f"item-{index}",
        }
        for index in range(6)
    ]
    compaction = {
        "apply_version": "1.0",
        "receipt_id": COMPACTION_ID,
        "status": "applied",
        "inputs": {
            "plan_id": "e" * 64,
            "synchronized_pair_receipt_id": PAIR_ID,
            "target_timeline_name": "M43 Target",
        },
        "preview_sha256": "f" * 64,
        "preview": {"placements": placements},
        "timeline": {"timeline_id": "timeline-43", "name": "M43 Target"},
        "placement_count": 6,
        "operations": [
            {
                "operation": "create_timeline",
                "status": "applied",
                "result": {},
            },
            {
                "operation": "ensure_timeline_tracks",
                "status": "applied",
                "result": {},
            },
            {
                "operation": "insert_clips",
                "status": "applied",
                "result": {"items": inserted_items},
            },
        ],
        "readback": {},
    }
    layout = {
        "layout_version": "1.0",
        "receipt_id": LAYOUT_ID,
        "status": "applied",
        "inputs": {
            "synchronized_pair_receipt_id": (
                "0" * 64 if mismatched_layout else PAIR_ID
            ),
            "size_percent": 25.0,
            "center_x_percent": 82.0,
            "center_y_percent": 82.0,
        },
        "source": {
            "timeline_id": "source-timeline",
            "webcam_asset_id": "webcam-asset",
            "webcam_timeline_item_id": "source-webcam",
        },
        "timeline_resolution": {"width": 1920, "height": 1080},
        "transform": {
            "position_x": 614.4,
            "position_y": -345.6,
            "zoom": 0.25,
        },
        "operation": {
            "operation": "set_webcam_transform",
            "status": "applied",
            "result": {},
        },
    }
    link = {
        "link_version": "1.0",
        "receipt_id": LINK_ID,
        "status": "applied",
        "inputs": {"synchronized_pair_receipt_id": PAIR_ID},
        "source": {
            "timeline_id": "source-timeline",
            "screen_video_timeline_item_id": "source-video",
            "screen_audio_timeline_item_id": "source-audio",
        },
        "operation": {
            "operation": "set_screen_pair_linked",
            "status": "applied",
            "result": {},
        },
    }
    (compactions / f"{COMPACTION_ID}.json").write_text(
        json.dumps(compaction), encoding="utf-8"
    )
    (layouts / f"{LAYOUT_ID}.json").write_text(
        json.dumps(layout), encoding="utf-8"
    )
    (links / f"{LINK_ID}.json").write_text(
        json.dumps(link), encoding="utf-8"
    )
    return compactions, layouts, links


def _finalizer(
    root: Path,
    gateway: StubGateway,
    *,
    capabilities: dict[str, bool] | None = None,
    mismatched_layout: bool = False,
) -> PauseCompactionFinalizer:
    compactions, layouts, links = _write_receipts(
        root, mismatched_layout=mismatched_layout
    )
    return PauseCompactionFinalizer(
        gateway=gateway,
        capabilities=lambda: _capabilities() if capabilities is None else capabilities,
        pause_compactions_root=compactions,
        picture_in_picture_root=layouts,
        synchronized_links_root=links,
        receipts_root=root / "finalizations",
    )


def _finalize(
    finalizer: PauseCompactionFinalizer,
    *,
    confirm_finalize: bool = True,
) -> dict[str, Any]:
    return finalizer.finalize(
        pause_compaction_receipt_id=COMPACTION_ID,
        picture_in_picture_receipt_id=LAYOUT_ID,
        synchronized_link_receipt_id=LINK_ID,
        confirm_finalize=confirm_finalize,
        timeout_seconds=45,
    )


def test_finalize_links_pairs_and_transforms_webcams_with_replay(
    tmp_path: Path,
) -> None:
    gateway = StubGateway()
    finalizer = _finalizer(tmp_path, gateway)

    result = _finalize(finalizer)
    calls_after_apply = list(gateway.calls)
    replay = _finalize(finalizer)

    assert result["status"] == "applied"
    assert result["link_groups"] == [
        ["item-0", "item-1"],
        ["item-3", "item-4"],
    ]
    assert result["webcam_item_ids"] == ["item-2", "item-5"]
    assert gateway.transform_items == [
        {
            "timeline_item_id": item_id,
            "position_x": 614.4,
            "position_y": -345.6,
            "zoom": 0.25,
        }
        for item_id in ("item-2", "item-5")
    ]
    assert calls_after_apply == [
        "set_clip_link_groups",
        "set_clip_transforms",
        "timeline_items",
    ]
    assert gateway.calls == calls_after_apply
    assert replay == result


def test_finalize_resumes_without_repeating_applied_link_batch(
    tmp_path: Path,
) -> None:
    gateway = StubGateway(fail_once_at="set_clip_transforms")
    finalizer = _finalizer(tmp_path, gateway)

    with pytest.raises(RuntimeError, match="simulated interruption"):
        _finalize(finalizer)
    result = _finalize(finalizer)

    assert result["status"] == "applied"
    assert gateway.calls == [
        "set_clip_link_groups",
        "set_clip_transforms",
        "set_clip_transforms",
        "timeline_items",
    ]


def test_finalize_requires_confirmation_capabilities_and_shared_source(
    tmp_path: Path,
) -> None:
    gateway = StubGateway()
    without_confirmation = _finalizer(tmp_path / "confirmation", gateway)
    with pytest.raises(PauseCompactionFinalizationError, match="confirm_finalize"):
        _finalize(without_confirmation, confirm_finalize=False)

    unsupported = _finalizer(tmp_path / "capabilities", gateway, capabilities={})
    with pytest.raises(PauseCompactionFinalizationError, match="not verified"):
        _finalize(unsupported)

    mismatched = _finalizer(
        tmp_path / "binding", gateway, mismatched_layout=True
    )
    with pytest.raises(PauseCompactionFinalizationError, match="do not share"):
        _finalize(mismatched)

    assert gateway.calls == []
