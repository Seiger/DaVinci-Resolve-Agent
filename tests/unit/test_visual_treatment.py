"""Tests for M49 standard-title and static reframing workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.visual_treatment import VisualTreatmentError, VisualTreatmentWorkflow


class StubGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def set_clip_transforms(
        self,
        timeline_id: str,
        items: list[dict[str, Any]],
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.calls.append(("transforms", idempotency_key))
        return {"timeline_id": timeline_id, "items": items, "backup_path": "backup.drp"}

    def insert_title(
        self,
        timeline_id: str,
        title_name: str,
        timecode: str,
        *,
        confirm_insert: bool,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]:
        assert confirm_insert is True
        self.calls.append(("title", idempotency_key))
        return {
            "timeline_id": timeline_id,
            "title_name": title_name,
            "requested_timecode": timecode,
            "item": {"timeline_item_id": "title-1"},
            "backup_path": "backup.drp",
        }


def _workflow(
    root: Path,
    gateway: StubGateway,
    **capabilities: bool,
) -> VisualTreatmentWorkflow:
    return VisualTreatmentWorkflow(
        gateway=gateway,
        capabilities=lambda: capabilities,
        receipts_root=root,
    )


def test_preview_normalizes_static_visual_operations(tmp_path: Path) -> None:
    workflow = _workflow(
        tmp_path,
        StubGateway(),
        **{"clip.transform": True, "title.insert": True},
    )

    preview = workflow.preview(
        "timeline-1",
        [{"timeline_item_id": "clip-1", "zoom": 1.25, "position_x": 120}],
        [{"title_name": "Text", "timecode": "01:00:05:00"}],
    )

    assert preview["ready"] is True
    assert preview["required_capabilities"] == ["clip.transform", "title.insert"]
    assert preview["inputs"]["transforms"][0]["position_x"] == 120.0
    assert len(preview["receipt_id"]) == 64


def test_preview_reports_unverified_title_capability(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path, StubGateway(), **{"clip.transform": True})

    preview = workflow.preview(
        "timeline-1",
        [],
        [{"title_name": "Text", "timecode": "01:00:05:00"}],
    )

    assert preview["ready"] is False
    assert preview["missing_capabilities"] == ["title.insert"]


def test_apply_is_confirmed_durable_and_replay_safe(tmp_path: Path) -> None:
    gateway = StubGateway()
    workflow = _workflow(
        tmp_path,
        gateway,
        **{"clip.transform": True, "title.insert": True},
    )
    arguments = (
        "timeline-1",
        [{"timeline_item_id": "clip-1", "zoom": 1.2}],
        [{"title_name": "Text", "timecode": "01:00:03:00"}],
    )

    first = workflow.apply(*arguments, confirm_apply=True)
    second = workflow.apply(*arguments, confirm_apply=True)

    assert first == second
    assert first["status"] == "applied"
    assert [call[0] for call in gateway.calls] == ["transforms", "title"]


def test_apply_rejects_missing_confirmation(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path, StubGateway(), **{"clip.transform": True})

    with pytest.raises(VisualTreatmentError, match="confirm_apply"):
        workflow.apply(
            "timeline-1",
            [{"timeline_item_id": "clip-1", "zoom": 1.1}],
            [],
            confirm_apply=False,
        )


@pytest.mark.parametrize(
    ("transforms", "titles", "message"),
    [
        ([], [], "At least one"),
        ([{"timeline_item_id": "clip-1", "zoom": -1}], [], "zoom"),
        ([], [{"title_name": "Text", "timecode": "bad"}], "timecode"),
    ],
)
def test_preview_rejects_invalid_inputs(
    tmp_path: Path,
    transforms: list[dict[str, Any]],
    titles: list[dict[str, Any]],
    message: str,
) -> None:
    workflow = _workflow(tmp_path, StubGateway())

    with pytest.raises(VisualTreatmentError, match=message):
        workflow.preview("timeline-1", transforms, titles)
