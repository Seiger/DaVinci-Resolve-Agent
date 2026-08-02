"""M55.6 duplicate-timeline take-sequence workflow tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.contracts import validate_contract
from agent.take_sequence_timeline_apply import (
    REQUIRED_CAPABILITIES,
    TakeSequenceTimelineApplyError,
    TakeSequenceTimelineApplyWorkflow,
)

IMPORT_ID = "a" * 64
BINDING_ID = "b" * 64
MAPPING_ID = "c" * 64
SOURCE_KEY = "d" * 64


def _timeline_item(identifier: str) -> dict[str, Any]:
    return {
        "timeline_item_id": identifier,
        "name": "existing.mkv",
        "track_type": "video",
        "track_index": 1,
        "source_type": "media",
        "duration_frames": 60,
        "timeline_start_frame": 86_400,
        "timeline_end_frame": 86_460,
        "source_start_frame": 0,
        "source_end_frame": 59,
    }


class StubImports:
    def get(self, receipt_id: str) -> dict[str, Any]:
        assert receipt_id == IMPORT_ID
        return _import_receipt()


class StubMapping:
    def preview(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["binding_id"] == BINDING_ID
        return _mapping()


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


class StubAudio:
    def __init__(self, has_audio: bool = True) -> None:
        self.value = has_audio
        self.paths: list[Path] = []

    def has_audio(self, path: Path) -> bool:
        self.paths.append(path)
        return self.value


class StubGateway:
    def __init__(
        self,
        *,
        source_items: list[dict[str, Any]] | None = None,
        target_name_exists: bool = False,
        fail_once_at: str | None = None,
    ) -> None:
        self.source_items = source_items or []
        self.target_name_exists = target_name_exists
        self.fail_once_at = fail_once_at
        self.failed = False
        self.target_created = False
        self.target_items: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self.keys: list[str] = []

    def timelines(self, timeout_seconds: float = 30) -> list[dict[str, Any]]:
        values = [
            {"timeline_id": "timeline-source", "index": 1, "name": "Source"}
        ]
        if self.target_name_exists or self.target_created:
            values.append(
                {"timeline_id": "timeline-target", "index": 2, "name": "Draft"}
            )
        return values

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        if timeline_id == "timeline-source":
            return {
                "timeline_id": timeline_id,
                "name": "Source",
                "items": self.source_items,
            }
        assert timeline_id == "timeline-target"
        return {
            "timeline_id": timeline_id,
            "name": "Draft",
            "items": list(self.target_items),
        }

    def duplicate_timeline(
        self,
        timeline_id: str,
        name: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._call("duplicate_timeline", kwargs)
        self.target_created = True
        return {
            "source_timeline": {"timeline_id": timeline_id, "name": "Source"},
            "timeline": {"timeline_id": "timeline-target", "name": name},
            "backup_path": "managed-backup.drp",
        }

    def ensure_timeline_tracks(
        self,
        timeline_id: str,
        video_track_count: int,
        audio_track_count: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._call("ensure_timeline_tracks", kwargs)
        return {
            "timeline": {"timeline_id": timeline_id},
            "after": {
                "video_track_count": video_track_count,
                "audio_track_count": audio_track_count,
            },
            "backup_path": "managed-backup.drp",
        }

    def insert_clips(
        self,
        timeline_id: str,
        placements: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        operation = f"insert_{placements[0]['track_type']}"
        self._call(operation, kwargs)
        if self.fail_once_at == operation and not self.failed:
            self.failed = True
            raise RuntimeError("temporary provider failure")
        items: list[dict[str, Any]] = []
        for index, placement in enumerate(placements):
            item = {
                "placement_index": index,
                "asset_id": placement["asset_id"],
                "timeline_item_id": f"{placement['track_type']}-item-{index}",
                "name": "take.mkv",
                "timeline_start_frame": 86_400 + placement["position_frames"],
                "timeline_end_frame": 86_460 + placement["position_frames"],
                "source_start_frame": placement["source_start_frame"],
                "source_end_frame": placement["source_end_frame"],
                "track_type": placement["track_type"],
                "track_index": placement["track_index"],
            }
            items.append(item)
            self.target_items.append(
                {
                    "timeline_item_id": item["timeline_item_id"],
                    "name": item["name"],
                    "track_type": item["track_type"],
                    "track_index": item["track_index"],
                    "source_type": "media",
                    "duration_frames": 60,
                    "timeline_start_frame": item["timeline_start_frame"],
                    "timeline_end_frame": item["timeline_end_frame"],
                    "source_start_frame": item["source_start_frame"],
                    "source_end_frame": item["source_end_frame"],
                }
            )
        return {
            "timeline_id": timeline_id,
            "items": items,
            "backup_path": "managed-backup.drp",
        }

    def _call(self, operation: str, kwargs: dict[str, Any]) -> None:
        self.calls.append(operation)
        self.keys.append(kwargs["idempotency_key"])


def test_preview_binds_import_mapping_audio_and_empty_source(tmp_path: Path) -> None:
    workflow, _, audio = _workflow(tmp_path)

    result = workflow.preview(
        media_import_receipt_id=IMPORT_ID,
        target_timeline_name="Draft",
    )

    assert result["apply_supported"] is True
    assert result["source_timeline"]["item_count"] == 0
    assert result["placements"][0]["asset_id"] == "asset-1"
    assert result["placements"][0]["has_audio"] is True
    assert result["video_item_count"] == 1
    assert result["audio_item_count"] == 1
    assert str(tmp_path) not in json.dumps(result)
    assert len(audio.paths) == 1
    validate_contract("take-sequence-timeline-apply-preview", result)


def test_apply_duplicates_inserts_video_audio_and_replays(tmp_path: Path) -> None:
    workflow, gateway, _ = _workflow(tmp_path)
    preview = workflow.preview(
        media_import_receipt_id=IMPORT_ID,
        target_timeline_name="Draft",
    )

    first = workflow.apply(
        media_import_receipt_id=IMPORT_ID,
        target_timeline_name="Draft",
        expected_plan_id=preview["plan_id"],
        confirm_apply=True,
    )
    replay = workflow.apply(
        media_import_receipt_id=IMPORT_ID,
        target_timeline_name="Draft",
        expected_plan_id=preview["plan_id"],
        confirm_apply=True,
    )

    assert first == replay
    assert first["status"] == "applied"
    assert first["source_unchanged"] is True
    assert len(first["inserted_items"]) == 2
    assert gateway.calls == [
        "duplicate_timeline",
        "ensure_timeline_tracks",
        "insert_video",
        "insert_audio",
    ]
    assert len(set(gateway.keys)) == 4
    assert "backup_path" not in json.dumps(first)
    assert str(tmp_path) not in json.dumps(first)
    validate_contract("take-sequence-timeline-apply-result", first)


def test_apply_requires_confirmation_without_provider_write(tmp_path: Path) -> None:
    workflow, gateway, _ = _workflow(tmp_path)

    with pytest.raises(TakeSequenceTimelineApplyError, match="confirm_apply"):
        workflow.apply(
            media_import_receipt_id=IMPORT_ID,
            target_timeline_name="Draft",
            expected_plan_id="e" * 64,
            confirm_apply=False,
        )

    assert gateway.calls == []


def test_apply_rejects_changed_plan_without_provider_write(tmp_path: Path) -> None:
    workflow, gateway, _ = _workflow(tmp_path)

    with pytest.raises(TakeSequenceTimelineApplyError, match="expected_plan_id"):
        workflow.apply(
            media_import_receipt_id=IMPORT_ID,
            target_timeline_name="Draft",
            expected_plan_id="e" * 64,
            confirm_apply=True,
        )

    assert gateway.calls == []


def test_preview_reports_unverified_write_capability(tmp_path: Path) -> None:
    workflow, gateway, _ = _workflow(
        tmp_path,
        capabilities={
            capability: capability != "clip.range_insert"
            for capability in REQUIRED_CAPABILITIES
        },
    )

    preview = workflow.preview(
        media_import_receipt_id=IMPORT_ID,
        target_timeline_name="Draft",
    )

    assert preview["apply_supported"] is False
    assert preview["unsupported_capabilities"] == ["clip.range_insert"]
    assert gateway.calls == []


def test_apply_skips_audio_write_when_source_has_no_audio(tmp_path: Path) -> None:
    workflow, gateway, _ = _workflow(tmp_path, has_audio=False)
    preview = workflow.preview(
        media_import_receipt_id=IMPORT_ID,
        target_timeline_name="Draft",
    )

    result = workflow.apply(
        media_import_receipt_id=IMPORT_ID,
        target_timeline_name="Draft",
        expected_plan_id=preview["plan_id"],
        confirm_apply=True,
    )

    assert result["status"] == "applied"
    assert result["operations"][3]["status"] == "skipped"
    assert result["operations"][3]["backup_created"] is False
    assert len(result["inserted_items"]) == 1
    assert gateway.calls == [
        "duplicate_timeline",
        "ensure_timeline_tracks",
        "insert_video",
    ]


@pytest.mark.parametrize(
    ("gateway", "blocker"),
    [
        (
            StubGateway(source_items=[_timeline_item("existing")]),
            "source_timeline_not_empty",
        ),
        (StubGateway(target_name_exists=True), "target_timeline_name_exists"),
    ],
)
def test_preview_blocks_nonempty_source_or_existing_target_name(
    tmp_path: Path,
    gateway: StubGateway,
    blocker: str,
) -> None:
    workflow, _, _ = _workflow(tmp_path, gateway=gateway)

    preview = workflow.preview(
        media_import_receipt_id=IMPORT_ID,
        target_timeline_name="Draft",
    )

    assert preview["apply_supported"] is False
    assert blocker in preview["blockers"]
    assert gateway.calls == []


def test_recovery_resumes_only_failed_audio_step(tmp_path: Path) -> None:
    gateway = StubGateway(fail_once_at="insert_audio")
    workflow, _, _ = _workflow(tmp_path, gateway=gateway)
    preview = workflow.preview(
        media_import_receipt_id=IMPORT_ID,
        target_timeline_name="Draft",
    )

    with pytest.raises(RuntimeError, match="temporary provider failure"):
        workflow.apply(
            media_import_receipt_id=IMPORT_ID,
            target_timeline_name="Draft",
            expected_plan_id=preview["plan_id"],
            confirm_apply=True,
        )
    result = workflow.apply(
        media_import_receipt_id=IMPORT_ID,
        target_timeline_name="Draft",
        expected_plan_id=preview["plan_id"],
        confirm_apply=True,
    )

    assert result["status"] == "applied"
    assert gateway.calls == [
        "duplicate_timeline",
        "ensure_timeline_tracks",
        "insert_video",
        "insert_audio",
        "insert_audio",
    ]
    assert gateway.keys[-1] == gateway.keys[-2]


def _workflow(
    tmp_path: Path,
    *,
    gateway: StubGateway | None = None,
    has_audio: bool = True,
    capabilities: dict[str, bool] | None = None,
) -> tuple[TakeSequenceTimelineApplyWorkflow, StubGateway, StubAudio]:
    source = tmp_path / "take.mkv"
    source.write_bytes(b"source")
    active_gateway = gateway or StubGateway()
    audio = StubAudio(has_audio)
    workflow = TakeSequenceTimelineApplyWorkflow(
        imports=StubImports(),
        mapping=StubMapping(),
        bindings=StubBindings(source),
        gateway=active_gateway,
        capabilities=lambda: (
            {capability: True for capability in REQUIRED_CAPABILITIES}
            if capabilities is None
            else capabilities
        ),
        audio=audio,
        receipts_root=tmp_path / "receipts",
    )
    return workflow, active_gateway, audio


def _import_receipt() -> dict[str, Any]:
    return {
        "import_version": "1.0",
        "receipt_id": IMPORT_ID,
        "status": "applied",
        "plan_id": "1" * 64,
        "mapping_plan_id": MAPPING_ID,
        "binding_id": BINDING_ID,
        "assembly_name": "Assembly",
        "target_timeline_id": "timeline-source",
        "media_pool_before_sha256": "2" * 64,
        "media_pool_after_sha256": "3" * 64,
        "sources": [
            {
                "source_key": SOURCE_KEY,
                "display_name": "take.mkv",
                "orders": [1],
                "asset_id": "asset-1",
                "duration_frames": 600,
                "frame_rate": 60.0,
            }
        ],
        "source_count": 1,
        "backup_created": True,
        "paths_redacted": True,
        "media_pool_modified": True,
        "timeline_modified": False,
        "apply_supported": True,
    }


def _mapping() -> dict[str, Any]:
    return {
        "mapping_version": "1.0",
        "plan_id": MAPPING_ID,
        "status": "preview",
        "assembly_plan_id": "4" * 64,
        "binding_id": BINDING_ID,
        "target_timeline": {
            "timeline_id": "timeline-source",
            "name": "Source",
            "frame_rate": 60.0,
            "resolution_width": 1920,
            "resolution_height": 1080,
            "video_track_count": 1,
            "audio_track_count": 1,
        },
        "placements": [
            {
                "order": 1,
                "selected_candidate_id": "take-1",
                "display_name": "take.mkv",
                "fingerprint": SOURCE_KEY,
                "source_frame_rate": 60.0,
                "source_start_frame": 0,
                "source_end_frame": 59,
                "source_duration_frames": 60,
                "position_frames": 0,
                "timeline_duration_frames": 60,
                "timeline_end_position_frames": 60,
            }
        ],
        "placement_count": 1,
        "output_duration_frames": 60,
        "output_duration_seconds": 1.0,
        "warnings": [],
        "live_metadata_verified": True,
        "paths_redacted": True,
        "timeline_modified": False,
        "apply_supported": False,
    }
