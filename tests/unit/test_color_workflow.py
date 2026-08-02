"""M53 color discovery and deterministic preview tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.color_workflow import ColorTreatmentWorkflow, ColorWorkflowError
from agent.contracts import validate_contract

RECEIPT_ID = "a" * 64


class StubColorGateway:
    def __init__(self) -> None:
        self.items = _items()
        self.duplicate_calls = 0
        self.apply_calls = 0
        self.target_id = "timeline-m53"
        self.applied = False

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        assert timeout_seconds == 30
        assert timeline_id in {"timeline-m52", self.target_id}
        if timeline_id == self.target_id:
            target_items = [
                {
                    **item,
                    "timeline_item_id": f"target-{item['timeline_item_id']}",
                }
                for item in self.items
            ]
            return {
                "timeline_id": timeline_id,
                "name": "M53 Color Apply",
                "items": target_items,
            }
        return {
            "timeline_id": timeline_id,
            "name": "M52 Accepted",
            "items": self.items,
        }

    def color_environment(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        assert timeout_seconds == 30
        assert timeline_id in {"timeline-m52", self.target_id}
        timeline_name = (
            "M53 Color Apply" if timeline_id == self.target_id else "M52 Accepted"
        )
        version_name = (
            "DaVinci Agent Tutorial Clean v1"
            if timeline_id == self.target_id and self.applied
            else "Version 1"
        )
        color_item = dict(self.items[0])
        if timeline_id == self.target_id:
            color_item["timeline_item_id"] = "target-media-video-1"
        return {
            "timeline": {
                "timeline_id": timeline_id,
                "name": timeline_name,
            },
            "methods": {
                "GetCurrentVersion": True,
                "GetVersionNameList": True,
                "GetNodeGraph": True,
                "SetCDL": True,
                "AddVersion": True,
                "LoadVersionByName": True,
                "Graph.GetNumNodes": True,
                "Graph.GetNodeLabel": True,
                "Graph.GetLUT": True,
            },
            "items": [
                {
                    **color_item,
                    "current_version": {
                        "versionName": version_name,
                        "versionType": 0,
                    },
                    "local_versions": ["Version 1"],
                    "node_count": 1,
                    "nodes": [{"index": 1, "label": "", "lut": ""}],
                }
            ],
            "ready": True,
            "apply_candidate": True,
        }

    def duplicate_timeline(
        self,
        timeline_id: str,
        name: str,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        assert timeline_id == "timeline-m52"
        assert name == "M53 Color Apply"
        assert timeout_seconds == 30
        assert len(idempotency_key) == 64
        self.duplicate_calls += 1
        return {
            "source_timeline": {
                "timeline_id": timeline_id,
                "name": "M52 Accepted",
            },
            "timeline": {"timeline_id": self.target_id, "name": name},
        }

    def apply_color_preset(
        self,
        timeline_id: str,
        timeline_item_ids: list[str],
        preset_id: str,
        *,
        confirm_apply: bool,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        assert timeline_id == self.target_id
        assert timeline_item_ids == ["target-media-video-1"]
        assert preset_id == "tutorial-clean-v1"
        assert confirm_apply is True
        assert timeout_seconds == 30
        assert len(idempotency_key) == 64
        self.apply_calls += 1
        self.applied = True
        return {
            "timeline_id": timeline_id,
            "preset_id": preset_id,
            "version_name": "DaVinci Agent Tutorial Clean v1",
            "items": [
                {
                    "timeline_item_id": "target-media-video-1",
                    "version_name": "DaVinci Agent Tutorial Clean v1",
                    "version_type": 0,
                    "node_index": 1,
                }
            ],
        }


def test_color_preview_is_m52_bound_and_excludes_generated_items(
    tmp_path: Path,
) -> None:
    _write_receipt(tmp_path)
    workflow = ColorTreatmentWorkflow(
        gateway=StubColorGateway(),
        capabilities=lambda: {"clip.read": True, "timeline.duplicate": True},
        animation_receipts_root=tmp_path,
    )

    first = workflow.preview(
        animation_receipt_id=RECEIPT_ID,
        target_timeline_name="M53 Color Preview",
        preset_id="tutorial-clean-v1",
    )
    second = workflow.preview(
        animation_receipt_id=RECEIPT_ID,
        target_timeline_name="M53 Color Preview",
        preset_id="tutorial-clean-v1",
    )

    assert first == second
    assert first["apply_supported"] is True
    assert [item["timeline_item_id"] for item in first["targets"]] == [
        "media-video-1"
    ]
    validate_contract("color-treatment-preview", first)


def test_color_preview_rejects_changed_m52_timeline(tmp_path: Path) -> None:
    _write_receipt(tmp_path)
    gateway = StubColorGateway()
    gateway.items[0]["timeline_end_frame"] = 111
    workflow = ColorTreatmentWorkflow(
        gateway=gateway,
        capabilities=lambda: {"clip.read": True, "timeline.duplicate": True},
        animation_receipts_root=tmp_path,
    )

    with pytest.raises(ColorWorkflowError, match="changed"):
        workflow.preview(
            animation_receipt_id=RECEIPT_ID,
            target_timeline_name="M53 Color Preview",
            preset_id="tutorial-clean-v1",
        )


def test_color_apply_duplicates_uses_exact_plan_and_replays(
    tmp_path: Path,
) -> None:
    animation_root = tmp_path / "animation"
    receipts_root = tmp_path / "color"
    animation_root.mkdir()
    _write_receipt(animation_root)
    gateway = StubColorGateway()
    workflow = ColorTreatmentWorkflow(
        gateway=gateway,
        capabilities=lambda: {"clip.read": True, "timeline.duplicate": True},
        animation_receipts_root=animation_root,
        receipts_root=receipts_root,
    )
    preview = workflow.preview(
        animation_receipt_id=RECEIPT_ID,
        target_timeline_name="M53 Color Apply",
        preset_id="tutorial-clean-v1",
    )

    first = workflow.apply(
        animation_receipt_id=RECEIPT_ID,
        target_timeline_name="M53 Color Apply",
        preset_id="tutorial-clean-v1",
        expected_plan_id=preview["plan_id"],
        confirm_apply=True,
    )
    second = workflow.apply(
        animation_receipt_id=RECEIPT_ID,
        target_timeline_name="M53 Color Apply",
        preset_id="tutorial-clean-v1",
        expected_plan_id=preview["plan_id"],
        confirm_apply=True,
    )

    assert first == second
    assert first["status"] == "applied"
    assert first["target"] == {
        "timeline_id": "timeline-m53",
        "timeline_name": "M53 Color Apply",
    }
    assert gateway.duplicate_calls == 1
    assert gateway.apply_calls == 1
    validate_contract("color-treatment-result", first)


def _items() -> list[dict[str, Any]]:
    return [
        {
            "timeline_item_id": "media-video-1",
            "name": "screen.mkv",
            "track_type": "video",
            "track_index": 1,
            "source_type": "media",
            "timeline_start_frame": 0,
            "timeline_end_frame": 100,
            "source_start_frame": 0,
            "source_end_frame": 100,
        },
        {
            "timeline_item_id": "title-1",
            "name": "Accent Card",
            "track_type": "video",
            "track_index": 1,
            "source_type": "generated",
            "timeline_start_frame": 100,
            "timeline_end_frame": 120,
            "source_start_frame": None,
            "source_end_frame": None,
        },
    ]


def _write_receipt(root: Path) -> None:
    receipt = {
        "animation_apply_version": "1.0",
        "receipt_id": RECEIPT_ID,
        "status": "applied",
        "plan": {},
        "target": {
            "timeline_id": "timeline-m52",
            "timeline_name": "M52 Accepted",
        },
        "operations": [
            {
                "operation": "duplicate_timeline",
                "status": "applied",
                "result": {},
            },
            {
                "operation": "insert_animation_template",
                "status": "applied",
                "result": {},
            },
        ],
        "inserted_item": {},
        "readback": {
            "timeline_id": "timeline-m52",
            "name": "M52 Accepted",
            "items": _items(),
        },
    }
    (root / f"{RECEIPT_ID}.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )
