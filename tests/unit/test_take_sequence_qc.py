from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from agent.take_sequence_qc import TakeSequenceQcError, TakeSequenceQcWorkflow

SHA = "a" * 64


class StubApplications:
    def __init__(self, receipt: dict[str, Any]) -> None:
        self.receipt = receipt
        self.calls: list[tuple[str, float]] = []

    def get(
        self,
        receipt_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.calls.append((receipt_id, timeout_seconds))
        return deepcopy(self.receipt)


def _receipt() -> dict[str, Any]:
    placements = [
        {
            "order": 1,
            "source_key": "b" * 64,
            "display_name": "take-1.mkv",
            "source_start_frame": 10,
            "source_end_frame": 20,
            "position_frames": 0,
            "timeline_end_position_frames": 10,
            "asset_id": "asset-1",
            "has_audio": True,
        },
        {
            "order": 2,
            "source_key": "c" * 64,
            "display_name": "take-2.mkv",
            "source_start_frame": 30,
            "source_end_frame": 40,
            "position_frames": 10,
            "timeline_end_position_frames": 20,
            "asset_id": "asset-2",
            "has_audio": False,
        },
    ]
    inserted = [
        {
            "timeline_item_id": "video-1",
            "name": "take-1.mkv",
            "track_type": "video",
            "track_index": 1,
            "timeline_start_frame": 100,
            "timeline_end_frame": 110,
            "source_start_frame": 10,
            "source_end_frame": 20,
        },
        {
            "timeline_item_id": "video-2",
            "name": "take-2.mkv",
            "track_type": "video",
            "track_index": 1,
            "timeline_start_frame": 110,
            "timeline_end_frame": 120,
            "source_start_frame": 30,
            "source_end_frame": 40,
        },
        {
            "timeline_item_id": "audio-1",
            "name": "take-1.mkv",
            "track_type": "audio",
            "track_index": 1,
            "timeline_start_frame": 100,
            "timeline_end_frame": 110,
            "source_start_frame": 10,
            "source_end_frame": 20,
        },
    ]
    operation_names = [
        "duplicate_timeline",
        "ensure_timeline_tracks",
        "insert_video",
        "insert_audio",
    ]
    return {
        "apply_version": "1.0",
        "receipt_id": SHA,
        "status": "applied",
        "inputs": {
            "media_import_receipt_id": "d" * 64,
            "target_timeline_name": "M55.7 QC",
            "expected_plan_id": "e" * 64,
        },
        "plan": {"placements": placements},
        "target_timeline": {"timeline_id": "timeline-2", "name": "M55.7 QC"},
        "operations": [
            {
                "operation": name,
                "status": "applied",
                "backup_created": index == 0,
                "result": {},
            }
            for index, name in enumerate(operation_names)
        ],
        "inserted_items": inserted,
        "target_readback_sha256": "f" * 64,
        "source_unchanged": True,
        "paths_redacted": True,
    }


def _workflow(
    tmp_path: Path,
    receipt: dict[str, Any] | None = None,
) -> tuple[TakeSequenceQcWorkflow, StubApplications]:
    applications = StubApplications(receipt or _receipt())
    return (
        TakeSequenceQcWorkflow(
            applications,
            reports_root=tmp_path / "reports",
            reviews_root=tmp_path / "reviews",
        ),
        applications,
    )


def test_inspect_proves_exact_structure_and_names_unverified_areas(
    tmp_path: Path,
) -> None:
    workflow, applications = _workflow(tmp_path)

    report = workflow.inspect(SHA, timeout_seconds=12)

    assert report["status"] == "ready_for_review"
    assert report["summary"] == {
        "placement_count": 2,
        "video_item_count": 2,
        "audio_item_count": 1,
        "gap_count": 0,
    }
    assert report["manual_review_required"] is True
    assert report["timeline_modified"] is False
    assert report["unverified_areas"] == [
        "dialogue_audio_processing",
        "subtitle_content_and_alignment",
        "color_treatment",
        "visual_and_editorial_quality",
    ]
    assert applications.calls == [(SHA, 12.0)]
    assert (tmp_path / "reports" / f"{report['report_id']}.json").is_file()


def test_get_revalidates_live_receipt(tmp_path: Path) -> None:
    workflow, applications = _workflow(tmp_path)
    report = workflow.inspect(SHA)

    assert workflow.get(report["report_id"]) == report
    assert len(applications.calls) == 2


def test_review_is_immutable_and_revalidates_report(tmp_path: Path) -> None:
    workflow, _ = _workflow(tmp_path)
    report = workflow.inspect(SHA)

    review = workflow.review(
        report_id=report["report_id"],
        decision="approve",
        note="Монтаж переглянуто.",
    )

    assert review["decision"] == "approve"
    assert review["timeline_modified"] is False
    assert workflow.get_review(report["report_id"]) == review
    assert (
        workflow.review(
            report_id=report["report_id"],
            decision="approve",
            note="Монтаж переглянуто.",
        )
        == review
    )
    with pytest.raises(TakeSequenceQcError, match="different review"):
        workflow.review(report_id=report["report_id"], decision="reject")


def test_inspect_rejects_non_contiguous_video(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["plan"]["placements"][1]["position_frames"] = 11
    receipt["plan"]["placements"][1]["timeline_end_position_frames"] = 21
    receipt["inserted_items"][1]["timeline_start_frame"] = 111
    receipt["inserted_items"][1]["timeline_end_frame"] = 121
    workflow, _ = _workflow(tmp_path, receipt)

    with pytest.raises(TakeSequenceQcError, match="not contiguous"):
        workflow.inspect(SHA)


def test_inspect_rejects_misaligned_audio(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["inserted_items"][2]["timeline_start_frame"] = 101
    receipt["inserted_items"][2]["timeline_end_frame"] = 111
    workflow, _ = _workflow(tmp_path, receipt)

    with pytest.raises(TakeSequenceQcError, match="one timeline origin"):
        workflow.inspect(SHA)
