"""M44 finalized timeline render preparation tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.finalized_render import (
    FinalizedRenderPreparationError,
    FinalizedRenderPreparer,
)

FINALIZATION_ID = "a" * 64


class StubGateway:
    def __init__(self, *, timeline_id: str = "timeline-final") -> None:
        self.timeline_id = timeline_id
        self.calls: list[dict[str, Any]] = []

    def prepare_render_job(
        self,
        custom_name: str,
        *,
        timeline_id: str,
        profile: str,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "custom_name": custom_name,
                "timeline_id": timeline_id,
                "profile": profile,
                "timeout_seconds": timeout_seconds,
                "idempotency_key": idempotency_key,
            }
        )
        return {
            "job_id": "job-final",
            "timeline_id": self.timeline_id,
            "timeline_name": "M42 Final",
            "preset": profile,
            "format": "MP4",
            "codec": "H264",
            "width": 1920,
            "height": 1080,
            "target_directory": "managed",
            "custom_name": custom_name,
            "started": False,
        }


def _write_finalization(root: Path) -> None:
    root.mkdir(parents=True)
    receipt = {
        "finalization_version": "1.0",
        "receipt_id": FINALIZATION_ID,
        "status": "applied",
        "inputs": {
            "pause_compaction_receipt_id": "b" * 64,
            "picture_in_picture_receipt_id": "c" * 64,
            "synchronized_link_receipt_id": "d" * 64,
        },
        "target": {
            "synchronized_pair_receipt_id": "e" * 64,
            "timeline_id": "timeline-final",
            "timeline_name": "M42 Final",
        },
        "link_groups": [["video", "audio"]],
        "webcam_item_ids": ["webcam"],
        "transform": {
            "position_x": 614.4,
            "position_y": -345.6,
            "zoom": 0.25,
        },
        "operations": [
            {
                "operation": "set_clip_link_groups",
                "status": "applied",
                "result": {},
            },
            {
                "operation": "set_clip_transforms",
                "status": "applied",
                "result": {},
            },
        ],
        "readback": {},
    }
    (root / f"{FINALIZATION_ID}.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )


def _preparer(
    tmp_path: Path,
    gateway: StubGateway,
    *,
    capability: bool = True,
) -> FinalizedRenderPreparer:
    finalizations = tmp_path / "finalizations"
    _write_finalization(finalizations)
    return FinalizedRenderPreparer(
        gateway=gateway,
        capabilities=lambda: {"render.configure": capability},
        finalizations_root=finalizations,
        receipts_root=tmp_path / "receipts",
    )


def test_prepares_finalized_timeline_once_and_replays(tmp_path: Path) -> None:
    gateway = StubGateway()
    preparer = _preparer(tmp_path, gateway)

    first = preparer.prepare(
        finalization_receipt_id=FINALIZATION_ID,
        custom_name="M44 Final",
        profile="youtube-1080p-h264-v1",
        confirm_prepare=True,
        timeout_seconds=45,
    )
    replay = preparer.prepare(
        finalization_receipt_id=FINALIZATION_ID,
        custom_name="M44 Final",
        profile="youtube-1080p-h264-v1",
        confirm_prepare=True,
        timeout_seconds=45,
    )

    assert first == replay
    assert first["status"] == "applied"
    assert first["operation"]["result"]["job_id"] == "job-final"
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["timeline_id"] == "timeline-final"


def test_requires_confirmation_and_live_capability(tmp_path: Path) -> None:
    gateway = StubGateway()
    preparer = _preparer(tmp_path / "confirmation", gateway)

    with pytest.raises(FinalizedRenderPreparationError, match="confirm_prepare"):
        preparer.prepare(
            finalization_receipt_id=FINALIZATION_ID,
            custom_name="M44 Final",
            profile="youtube-1080p-h264-v1",
            confirm_prepare=False,
        )

    blocked = _preparer(tmp_path / "capability", gateway, capability=False)
    with pytest.raises(FinalizedRenderPreparationError, match="render.configure"):
        blocked.prepare(
            finalization_receipt_id=FINALIZATION_ID,
            custom_name="M44 Final",
            profile="youtube-1080p-h264-v1",
            confirm_prepare=True,
        )
    assert gateway.calls == []


def test_rejects_render_job_for_another_timeline(tmp_path: Path) -> None:
    gateway = StubGateway(timeline_id="timeline-wrong")
    preparer = _preparer(tmp_path, gateway)

    with pytest.raises(FinalizedRenderPreparationError, match="policy"):
        preparer.prepare(
            finalization_receipt_id=FINALIZATION_ID,
            custom_name="M44 Final",
            profile="youtube-1080p-h264-v1",
            confirm_prepare=True,
        )
