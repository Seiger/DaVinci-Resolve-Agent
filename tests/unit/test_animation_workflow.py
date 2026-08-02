"""M52 provider-neutral animation-template workflow tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.animation_workflow import (
    AnimationTemplateWorkflow,
    AnimationWorkflowError,
)
from agent.contracts import validate_contract

BROLL_RECEIPT_ID = "a" * 64
SOURCE_TIMELINE_ID = "timeline-m51"
TARGET_TIMELINE_ID = "timeline-m52"


class StubBroll:
    def status(
        self,
        receipt_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        assert receipt_id == BROLL_RECEIPT_ID
        assert timeout_seconds == 30
        return {
            "status": "applied",
            "target": {
                "timeline_id": SOURCE_TIMELINE_ID,
                "timeline_name": "M51 B-roll Apply Test",
            },
        }


class StubGateway:
    def __init__(self) -> None:
        self.duplicate_calls = 0
        self.insert_calls = 0
        self.source_items = [
            {
                "timeline_item_id": "source-item",
                "name": "Source",
                "track_type": "video",
                "track_index": 1,
                "timeline_start_frame": 86400,
                "timeline_end_frame": 86640,
                "duration_frames": 240,
                "enabled": True,
            }
        ]
        self.inserted_item = {
            "timeline_item_id": "animation-item",
            "name": "DaVinci Agent Accent Card",
            "track_type": "video",
            "track_index": 2,
            "timeline_start_frame": 86640,
            "timeline_end_frame": 86760,
            "duration_frames": 120,
        }

    def animation_template_environment(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        assert timeline_id == SOURCE_TIMELINE_ID
        return {
            "timeline": {
                "timeline_id": SOURCE_TIMELINE_ID,
                "name": "M51 B-roll Apply Test",
            },
            "methods": {
                "InsertFusionTitleIntoTimeline": True,
                "GetCurrentTimecode": True,
                "SetCurrentTimecode": True,
                "GetEndFrame": True,
                "GetSetting": True,
                "GetTrackCount": True,
                "GetItemListInTrack": True,
                "SetCurrentTimeline": True,
            },
            "templates": [
                {
                    "template_id": "accent-card-v1",
                    "resolve_name": "DaVinci Agent Accent Card",
                    "installed": True,
                    "sha256_matches": True,
                }
            ],
            "ready": True,
        }

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if timeline_id == SOURCE_TIMELINE_ID:
            return {
                "timeline_id": timeline_id,
                "name": "M51 B-roll Apply Test",
                "items": self.source_items,
            }
        assert timeline_id == TARGET_TIMELINE_ID
        return {
            "timeline_id": timeline_id,
            "name": "M52 Animation Apply Test",
            "items": [*self.source_items, self.inserted_item],
        }

    def duplicate_timeline(
        self,
        timeline_id: str,
        name: str,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.duplicate_calls += 1
        return {
            "source_timeline": {
                "timeline_id": timeline_id,
                "name": "M51 B-roll Apply Test",
            },
            "timeline": {"timeline_id": TARGET_TIMELINE_ID, "name": name},
            "backup_path": "backup-duplicate.drp",
        }

    def insert_animation_template(
        self,
        timeline_id: str,
        template_id: str,
        timecode: str,
        *,
        confirm_insert: bool,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.insert_calls += 1
        assert timeline_id == TARGET_TIMELINE_ID
        assert template_id == "accent-card-v1"
        assert timecode == "01:00:04:00"
        assert confirm_insert is True
        return {
            "timeline_id": timeline_id,
            "template_id": template_id,
            "resolve_name": "DaVinci Agent Accent Card",
            "requested_timecode": timecode,
            "requested_frame": 86640,
            "previous_timecode": "01:00:10:00",
            "fusion_comp_count": 1,
            "item": self.inserted_item,
            "backup_path": "backup-insert.drp",
        }


def _capabilities() -> dict[str, Any]:
    return {
        "animation.template.insert": True,
        "clip.read": True,
        "timeline.duplicate": True,
    }


def _inputs() -> dict[str, Any]:
    return {
        "broll_receipt_id": BROLL_RECEIPT_ID,
        "target_timeline_name": "M52 Animation Apply Test",
        "template_id": "accent-card-v1",
        "timecode": "01:00:04:00",
    }


def test_preview_is_deterministic_and_schema_valid(tmp_path: Path) -> None:
    workflow = AnimationTemplateWorkflow(
        gateway=StubGateway(),
        broll=StubBroll(),
        capabilities=_capabilities,
        receipts_root=tmp_path,
    )

    first = workflow.preview(**_inputs())
    second = workflow.preview(**_inputs())

    assert first == second
    assert first["apply_supported"] is True
    assert first["source"]["item_count"] == 1
    assert len(first["source"]["snapshot_sha256"]) == 64
    validate_contract("animation-template-preview", first)


def test_apply_duplicates_inserts_reads_back_and_replays(tmp_path: Path) -> None:
    gateway = StubGateway()
    workflow = AnimationTemplateWorkflow(
        gateway=gateway,
        broll=StubBroll(),
        capabilities=_capabilities,
        receipts_root=tmp_path,
    )
    preview = workflow.preview(**_inputs())

    first = workflow.apply(
        **_inputs(),
        expected_plan_id=preview["plan_id"],
        confirm_apply=True,
    )
    replay = workflow.apply(
        **_inputs(),
        expected_plan_id=preview["plan_id"],
        confirm_apply=True,
    )

    assert first == replay
    assert first["status"] == "applied"
    assert first["target"]["timeline_id"] == TARGET_TIMELINE_ID
    assert first["inserted_item"]["timeline_item_id"] == "animation-item"
    assert gateway.duplicate_calls == 1
    assert gateway.insert_calls == 1
    validate_contract("animation-template-result", first)


def test_apply_requires_confirmation_exact_plan_and_verified_capability(
    tmp_path: Path,
) -> None:
    blocked_capabilities = {
        "animation.template.insert": "unknown",
        "clip.read": True,
        "timeline.duplicate": True,
    }
    workflow = AnimationTemplateWorkflow(
        gateway=StubGateway(),
        broll=StubBroll(),
        capabilities=lambda: blocked_capabilities,
        receipts_root=tmp_path,
    )
    preview = workflow.preview(**_inputs())

    assert preview["apply_supported"] is False
    assert preview["unsupported_capabilities"] == [
        "animation.template.insert"
    ]
    with pytest.raises(AnimationWorkflowError, match="confirm_apply"):
        workflow.apply(
            **_inputs(),
            expected_plan_id=preview["plan_id"],
            confirm_apply=False,
        )
    with pytest.raises(AnimationWorkflowError, match="expected_plan_id"):
        workflow.apply(
            **_inputs(),
            expected_plan_id="f" * 64,
            confirm_apply=True,
        )
    with pytest.raises(AnimationWorkflowError, match="not verified"):
        workflow.apply(
            **_inputs(),
            expected_plan_id=preview["plan_id"],
            confirm_apply=True,
        )
