"""M55.4 Media Pool import preview tests."""

from __future__ import annotations

from typing import Any

import pytest

from agent.contracts import validate_contract
from agent.take_sequence_media_import import (
    TakeSequenceMediaImportError,
    TakeSequenceMediaImportWorkflow,
)


class StubMapping:
    def __init__(self, placements: list[dict[str, Any]]) -> None:
        self.placements = placements

    def preview(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "plan_id": "a" * 64,
            "binding_id": kwargs["binding_id"],
            "target_timeline": {"timeline_id": kwargs["timeline_id"]},
            "placements": self.placements,
        }


class StubMediaPool:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.timeouts: list[float] = []

    def media_pool_items(self, timeout_seconds: float = 30) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        return {"items": self.items, "folder_count": 1}


def test_preview_plans_unique_imports_without_writing() -> None:
    media_pool = StubMediaPool([])
    workflow = TakeSequenceMediaImportWorkflow(
        StubMapping(
            [
                _placement(1, "take.mkv", "1" * 64),
                _placement(2, "take.mkv", "1" * 64),
                _placement(3, "other.mkv", "2" * 64),
            ]
        ),
        media_pool,
    )

    result = workflow.preview(
        binding_id="b" * 64,
        assembly_name="Approved",
        timeline_id="timeline-1",
        timeout_seconds=12.5,
    )

    assert media_pool.timeouts == [12.5]
    assert result["source_count"] == 2
    assert result["sources"][0]["orders"] == [1, 2]
    assert result["sources"][0]["action"] == "import"
    assert result["collision_count"] == 0
    assert result["import_ready"] is True
    assert result["requires_review"] is False
    assert result["media_pool_modified"] is False
    assert result["timeline_modified"] is False
    assert result["apply_supported"] is False
    validate_contract("take-sequence-media-import-preview", result)


def test_preview_blocks_same_name_as_ambiguous_collision() -> None:
    workflow = TakeSequenceMediaImportWorkflow(
        StubMapping([_placement(1, "Take.MKV", "1" * 64)]),
        StubMediaPool([_pool_item("asset-1", "take.mkv")]),
    )

    result = workflow.preview(
        binding_id="b" * 64,
        assembly_name="Approved",
        timeline_id="timeline-1",
    )

    assert result["sources"][0]["action"] == "review_name_collision"
    assert result["sources"][0]["name_matches"][0]["asset_id"] == "asset-1"
    assert result["collision_count"] == 1
    assert result["import_ready"] is False
    assert result["requires_review"] is True


def test_preview_is_deterministic_for_unordered_media_pool() -> None:
    mapping = StubMapping([_placement(1, "take.mkv", "1" * 64)])
    first = TakeSequenceMediaImportWorkflow(
        mapping,
        StubMediaPool(
            [_pool_item("asset-2", "take.mkv"), _pool_item("asset-1", "take.mkv")]
        ),
    ).preview(
        binding_id="b" * 64,
        assembly_name="Approved",
        timeline_id="timeline-1",
    )
    second = TakeSequenceMediaImportWorkflow(
        mapping,
        StubMediaPool(
            [_pool_item("asset-1", "take.mkv"), _pool_item("asset-2", "take.mkv")]
        ),
    ).preview(
        binding_id="b" * 64,
        assembly_name="Approved",
        timeline_id="timeline-1",
    )

    assert first == second


def test_preview_rejects_conflicting_names_for_one_fingerprint() -> None:
    workflow = TakeSequenceMediaImportWorkflow(
        StubMapping(
            [
                _placement(1, "first.mkv", "1" * 64),
                _placement(2, "second.mkv", "1" * 64),
            ]
        ),
        StubMediaPool([]),
    )

    with pytest.raises(TakeSequenceMediaImportError, match="conflicting"):
        workflow.preview(
            binding_id="b" * 64,
            assembly_name="Approved",
            timeline_id="timeline-1",
        )


def test_preview_rejects_unbounded_same_name_matches() -> None:
    workflow = TakeSequenceMediaImportWorkflow(
        StubMapping([_placement(1, "take.mkv", "1" * 64)]),
        StubMediaPool(
            [_pool_item(f"asset-{index}", "take.mkv") for index in range(101)]
        ),
    )

    with pytest.raises(TakeSequenceMediaImportError, match="bounded review"):
        workflow.preview(
            binding_id="b" * 64,
            assembly_name="Approved",
            timeline_id="timeline-1",
        )


def test_preview_blocks_different_sources_with_same_name() -> None:
    workflow = TakeSequenceMediaImportWorkflow(
        StubMapping(
            [
                _placement(1, "take.mkv", "1" * 64),
                _placement(2, "TAKE.MKV", "2" * 64),
            ]
        ),
        StubMediaPool([]),
    )

    result = workflow.preview(
        binding_id="b" * 64,
        assembly_name="Approved",
        timeline_id="timeline-1",
    )

    assert result["collision_count"] == 2
    assert result["import_ready"] is False
    assert all(
        source["action"] == "review_source_name_collision"
        for source in result["sources"]
    )


def _placement(order: int, name: str, fingerprint: str) -> dict[str, Any]:
    return {"order": order, "display_name": name, "fingerprint": fingerprint}


def _pool_item(asset_id: str, name: str) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "name": name,
        "folder_id": "folder-root",
        "folder_path": ["Master"],
    }
