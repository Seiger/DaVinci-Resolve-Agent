"""M55.5 confirmed Media Pool import tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.contracts import validate_contract
from agent.take_sequence_media_import_apply import (
    TakeSequenceMediaImportApplyError,
    TakeSequenceMediaImporter,
)

SOURCE_KEY = "1" * 64
PLAN_ID = "a" * 64
MAPPING_ID = "c" * 64
BINDING_ID = "b" * 64


class StubPreview:
    def __init__(self, *, import_ready: bool = True) -> None:
        self.import_ready = import_ready

    def preview(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "plan_id": PLAN_ID,
            "mapping_plan_id": MAPPING_ID,
            "binding_id": kwargs["binding_id"],
            "media_pool_snapshot_sha256": "d" * 64,
            "sources": [
                {
                    "source_key": SOURCE_KEY,
                    "display_name": "take.mkv",
                    "orders": [1],
                    "action": (
                        "import"
                        if self.import_ready
                        else "review_name_collision"
                    ),
                }
            ],
            "import_ready": self.import_ready,
            "requires_review": not self.import_ready,
        }


class StubMapping:
    def preview(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "plan_id": MAPPING_ID,
            "binding_id": kwargs["binding_id"],
            "placements": [
                {
                    "fingerprint": SOURCE_KEY,
                    "source_frame_rate": 60.0,
                    "source_end_frame": 599,
                }
            ],
        }


class StubBindings:
    def __init__(self, source: Path) -> None:
        self.source = source

    def resolve_sources(self, binding_id: str) -> list[dict[str, Any]]:
        assert binding_id == BINDING_ID
        return [
            {
                "fingerprint": SOURCE_KEY,
                "display_name": "take.mkv",
                "path": str(self.source.resolve()),
            }
        ]


class StubGateway:
    def __init__(self) -> None:
        self.import_calls: list[dict[str, Any]] = []

    def import_media(self, paths: list[str], **kwargs: Any) -> dict[str, Any]:
        self.import_calls.append({"paths": paths, **kwargs})
        return {
            "items": [{"asset_id": "asset-1", "name": "take.mkv"}],
            "backup_path": "managed-backup.drp",
        }

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "timeline": {"timeline_id": timeline_id},
            "assets": [
                {
                    "asset_id": asset_ids[0],
                    "name": "take.mkv",
                    "duration_frames": 600,
                    "frame_rate": 60.0,
                }
            ],
        }

    def media_pool_items(self, timeout_seconds: float = 30) -> dict[str, Any]:
        return {
            "items": [
                {
                    "asset_id": "asset-1",
                    "name": "take.mkv",
                    "folder_id": "folder-root",
                    "folder_path": ["Master"],
                }
            ],
            "folder_count": 1,
        }


def test_confirmed_import_persists_redacted_receipt_and_replays(
    tmp_path: Path,
) -> None:
    source = tmp_path / "take.mkv"
    source.write_bytes(b"source")
    gateway = StubGateway()
    workflow = TakeSequenceMediaImporter(
        StubPreview(),
        StubMapping(),
        StubBindings(source),
        gateway,
        tmp_path / "receipts",
    )

    first = _apply(workflow)
    replay = _apply(workflow)

    assert first == replay
    assert first["status"] == "applied"
    assert first["sources"][0]["asset_id"] == "asset-1"
    assert first["backup_created"] is True
    assert first["media_pool_modified"] is True
    assert first["timeline_modified"] is False
    assert str(tmp_path) not in json.dumps(first)
    assert len(gateway.import_calls) == 1
    assert gateway.import_calls[0]["idempotency_key"].startswith("m55:")
    validate_contract("take-sequence-media-import-result", first)
    assert workflow.get(first["receipt_id"]) == first


def test_import_requires_confirmation_before_provider_call(tmp_path: Path) -> None:
    source = tmp_path / "take.mkv"
    source.write_bytes(b"source")
    gateway = StubGateway()
    workflow = TakeSequenceMediaImporter(
        StubPreview(),
        StubMapping(),
        StubBindings(source),
        gateway,
        tmp_path / "receipts",
    )

    with pytest.raises(TakeSequenceMediaImportApplyError, match="confirm_import"):
        workflow.apply(
            binding_id=BINDING_ID,
            assembly_name="Approved",
            timeline_id="timeline-1",
            expected_plan_id=PLAN_ID,
            confirm_import=False,
        )

    assert gateway.import_calls == []


def test_import_rejects_changed_plan_or_collision(tmp_path: Path) -> None:
    source = tmp_path / "take.mkv"
    source.write_bytes(b"source")
    gateway = StubGateway()
    changed = TakeSequenceMediaImporter(
        StubPreview(),
        StubMapping(),
        StubBindings(source),
        gateway,
        tmp_path / "changed",
    )
    blocked = TakeSequenceMediaImporter(
        StubPreview(import_ready=False),
        StubMapping(),
        StubBindings(source),
        gateway,
        tmp_path / "blocked",
    )

    with pytest.raises(TakeSequenceMediaImportApplyError, match="expected_plan_id"):
        changed.apply(
            binding_id=BINDING_ID,
            assembly_name="Approved",
            timeline_id="timeline-1",
            expected_plan_id="e" * 64,
            confirm_import=True,
        )
    with pytest.raises(TakeSequenceMediaImportApplyError, match="collision"):
        _apply(blocked)

    assert gateway.import_calls == []


def test_import_rejects_asset_too_short_for_approved_range(tmp_path: Path) -> None:
    source = tmp_path / "take.mkv"
    source.write_bytes(b"source")
    gateway = StubGateway()
    original = gateway.editing_metadata

    def short_metadata(*args: Any, **kwargs: Any) -> dict[str, Any]:
        value = original(*args, **kwargs)
        value["assets"][0]["duration_frames"] = 599
        return value

    gateway.editing_metadata = short_metadata  # type: ignore[method-assign]
    workflow = TakeSequenceMediaImporter(
        StubPreview(),
        StubMapping(),
        StubBindings(source),
        gateway,
        tmp_path / "receipts",
    )

    with pytest.raises(TakeSequenceMediaImportApplyError, match="does not cover"):
        _apply(workflow)


def test_retry_after_readback_failure_reuses_provider_idempotency_key(
    tmp_path: Path,
) -> None:
    source = tmp_path / "take.mkv"
    source.write_bytes(b"source")

    class FlakyGateway(StubGateway):
        def __init__(self) -> None:
            super().__init__()
            self.metadata_calls = 0

        def editing_metadata(
            self,
            timeline_id: str,
            asset_ids: list[str],
            **kwargs: Any,
        ) -> dict[str, Any]:
            self.metadata_calls += 1
            if self.metadata_calls == 1:
                raise RuntimeError("temporary readback failure")
            return super().editing_metadata(timeline_id, asset_ids, **kwargs)

    gateway = FlakyGateway()
    workflow = TakeSequenceMediaImporter(
        StubPreview(),
        StubMapping(),
        StubBindings(source),
        gateway,
        tmp_path / "receipts",
    )

    with pytest.raises(RuntimeError, match="temporary readback"):
        _apply(workflow)
    result = _apply(workflow)

    assert result["status"] == "applied"
    assert len(gateway.import_calls) == 2
    assert gateway.import_calls[0]["idempotency_key"] == (
        gateway.import_calls[1]["idempotency_key"]
    )


def _apply(workflow: TakeSequenceMediaImporter) -> dict[str, Any]:
    return workflow.apply(
        binding_id=BINDING_ID,
        assembly_name="Approved",
        timeline_id="timeline-1",
        expected_plan_id=PLAN_ID,
        confirm_import=True,
        timeout_seconds=12.5,
    )
