"""M55.3 live timeline mapping preview tests."""

from __future__ import annotations

from typing import Any

import pytest

from agent.contracts import validate_contract
from agent.take_sequence_timeline_mapping import (
    TakeSequenceTimelineMappingError,
    TakeSequenceTimelineMappingWorkflow,
)


class StubAssembly:
    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self.entries = entries

    def preview(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "plan_id": "a" * 64,
            "binding_id": kwargs["binding_id"],
            "entries": self.entries,
            "total_duration_seconds": sum(
                entry["source_range"]["end_seconds"]
                - entry["source_range"]["start_seconds"]
                for entry in self.entries
            ),
            "warnings": [],
        }


class StubTimelineMetadata:
    def __init__(self, metadata: dict[str, Any] | None = None) -> None:
        self.metadata = metadata or _metadata()
        self.calls: list[tuple[str, list[str], float]] = []

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        self.calls.append((timeline_id, asset_ids, timeout_seconds))
        return self.metadata


def test_mapping_uses_live_timeline_rate_and_contiguous_positions() -> None:
    metadata = StubTimelineMetadata()
    workflow = TakeSequenceTimelineMappingWorkflow(
        StubAssembly(
            [
                _entry(1, "take-a", 2.0, 5.5, 60.0),
                _entry(2, "take-b", 0.0, 4.0, 30.0),
            ]
        ),
        metadata,
    )

    result = workflow.preview(
        binding_id="b" * 64,
        assembly_name="Approved assembly",
        timeline_id="timeline-1",
        timeout_seconds=12.5,
    )

    assert metadata.calls == [("timeline-1", [], 12.5)]
    assert result["target_timeline"]["frame_rate"] == 24.0
    assert result["placements"][0]["source_start_frame"] == 120
    assert result["placements"][0]["source_end_frame"] == 329
    assert result["placements"][0]["timeline_duration_frames"] == 84
    assert result["placements"][1]["position_frames"] == 84
    assert result["placements"][1]["timeline_end_position_frames"] == 180
    assert result["output_duration_frames"] == 180
    assert result["output_duration_seconds"] == 7.5
    assert result["live_metadata_verified"] is True
    assert result["timeline_modified"] is False
    assert result["apply_supported"] is False
    validate_contract("take-sequence-timeline-preview", result)


def test_mapping_is_deterministic() -> None:
    workflow = TakeSequenceTimelineMappingWorkflow(
        StubAssembly([_entry(1, "take-a", 0.0, 5.0, 60.0)]),
        StubTimelineMetadata(),
    )

    first = workflow.preview(
        binding_id="b" * 64,
        assembly_name="Approved",
        timeline_id="timeline-1",
    )
    second = workflow.preview(
        binding_id="b" * 64,
        assembly_name="Approved",
        timeline_id="timeline-1",
    )

    assert first == second


def test_mapping_rejects_wrong_live_timeline_identity() -> None:
    metadata = _metadata()
    metadata["timeline"]["timeline_id"] = "other"
    workflow = TakeSequenceTimelineMappingWorkflow(
        StubAssembly([_entry(1, "take-a", 0.0, 5.0, 60.0)]),
        StubTimelineMetadata(metadata),
    )

    with pytest.raises(TakeSequenceTimelineMappingError, match="invalid"):
        workflow.preview(
            binding_id="b" * 64,
            assembly_name="Approved",
            timeline_id="timeline-1",
        )


def test_mapping_rejects_subframe_source_range() -> None:
    workflow = TakeSequenceTimelineMappingWorkflow(
        StubAssembly([_entry(1, "take-a", 0.0, 0.001, 24.0)]),
        StubTimelineMetadata(),
    )

    with pytest.raises(TakeSequenceTimelineMappingError, match="less than one"):
        workflow.preview(
            binding_id="b" * 64,
            assembly_name="Approved",
            timeline_id="timeline-1",
        )


def _entry(
    order: int,
    candidate_id: str,
    start: float,
    end: float,
    frame_rate: float,
) -> dict[str, Any]:
    return {
        "order": order,
        "selected_candidate_id": candidate_id,
        "display_name": f"{candidate_id}.mkv",
        "fingerprint": str(order) * 64,
        "source_range": {"start_seconds": start, "end_seconds": end},
        "video": {"frame_rate": frame_rate, "width": 1920, "height": 1080},
    }


def _metadata() -> dict[str, Any]:
    return {
        "timeline": {
            "timeline_id": "timeline-1",
            "name": "M55 Target",
            "frame_rate": 24.0,
            "resolution_width": 1920,
            "resolution_height": 1080,
            "video_track_count": 1,
            "audio_track_count": 1,
        },
        "assets": [],
    }
