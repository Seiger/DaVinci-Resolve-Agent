"""M55.6 duplicate-timeline application for an imported take sequence."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import av

from agent.contracts import validate_contract
from agent.paths import take_sequence_timeline_applications_directory
from transports.filesystem import atomic_write_json, read_json_object

PLAN_VERSION = "1.0"
APPLY_VERSION = "1.0"
MAX_ITEMS = 100
REQUIRED_CAPABILITIES = (
    "timeline.read",
    "timeline.duplicate",
    "timeline.track.create",
    "clip.read",
    "clip.range_insert",
    "media.metadata.read",
)


class TakeSequenceTimelineApplyError(ValueError):
    """Raised when an M55.6 preview or application is unsafe."""


class MediaImportReceiptReader(Protocol):
    def get(self, receipt_id: str) -> dict[str, Any]: ...


class TimelineMappingReader(Protocol):
    def preview(
        self,
        *,
        binding_id: str,
        assembly_name: str,
        timeline_id: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...


class PrivateBindingReader(Protocol):
    def resolve_sources(self, binding_id: str) -> list[dict[str, Any]]: ...


class TimelineApplyGateway(Protocol):
    def timelines(self, timeout_seconds: float = 30) -> list[dict[str, Any]]: ...

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...

    def duplicate_timeline(
        self,
        timeline_id: str,
        name: str,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def ensure_timeline_tracks(
        self,
        timeline_id: str,
        video_track_count: int,
        audio_track_count: int,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def insert_clips(
        self,
        timeline_id: str,
        placements: list[dict[str, Any]],
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...


class AudioStreamInspector(Protocol):
    def has_audio(self, path: Path) -> bool: ...


class PyAvAudioStreamInspector:
    """Detect an audio stream locally without decoding or exposing its path."""

    def has_audio(self, path: Path) -> bool:
        try:
            with av.open(str(path)) as container:
                return next(iter(container.streams.audio), None) is not None
        except (av.error.FFmpegError, OSError, ValueError) as error:
            raise TakeSequenceTimelineApplyError(
                f"Could not inspect bound source audio: {path.name}"
            ) from error


class TakeSequenceTimelineApplyWorkflow:
    """Preview and apply exact imported ranges to a duplicate empty timeline."""

    def __init__(
        self,
        *,
        imports: MediaImportReceiptReader,
        mapping: TimelineMappingReader,
        bindings: PrivateBindingReader,
        gateway: TimelineApplyGateway,
        capabilities: Callable[[], dict[str, Any]],
        audio: AudioStreamInspector | None = None,
        receipts_root: Path | None = None,
    ) -> None:
        self._imports = imports
        self._mapping = mapping
        self._bindings = bindings
        self._gateway = gateway
        self._capabilities = capabilities
        self._audio = audio or PyAvAudioStreamInspector()
        self._receipts_root = (
            receipts_root or take_sequence_timeline_applications_directory()
        )

    def preview(
        self,
        *,
        media_import_receipt_id: str,
        target_timeline_name: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Build an exact path-redacted duplicate-timeline application plan."""
        return self._preview(
            media_import_receipt_id=media_import_receipt_id,
            target_timeline_name=target_timeline_name,
            timeout_seconds=_timeout(timeout_seconds),
            check_target_name=True,
        )

    def apply(
        self,
        *,
        media_import_receipt_id: str,
        target_timeline_name: str,
        expected_plan_id: str,
        confirm_apply: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Apply one exact reviewed M55.6 plan with durable step replay."""
        if confirm_apply is not True:
            raise TakeSequenceTimelineApplyError("confirm_apply must be true.")
        import_id = _sha256(
            media_import_receipt_id, "media_import_receipt_id"
        )
        target_name = _timeline_name(target_timeline_name)
        expected_id = _sha256(expected_plan_id, "expected_plan_id")
        timeout = _timeout(timeout_seconds)
        inputs = {
            "media_import_receipt_id": import_id,
            "target_timeline_name": target_name,
            "expected_plan_id": expected_id,
        }
        receipt_id = _canonical_sha256(
            {"apply_version": APPLY_VERSION, "inputs": inputs}
        )
        path = self._receipts_root / f"{receipt_id}.json"
        existing: dict[str, Any] | None = None
        if path.is_file():
            existing = read_json_object(path)
            validate_contract("take-sequence-timeline-apply-result", existing)
            if (
                existing.get("receipt_id") != receipt_id
                or existing.get("inputs") != inputs
            ):
                raise TakeSequenceTimelineApplyError(
                    "Stored timeline application receipt does not match inputs."
                )
            if existing.get("status") == "applied":
                return self.get(receipt_id, timeout_seconds=timeout)

        plan = self._preview(
            media_import_receipt_id=import_id,
            target_timeline_name=target_name,
            timeout_seconds=timeout,
            check_target_name=existing is None,
        )
        if plan["plan_id"] != expected_id:
            raise TakeSequenceTimelineApplyError(
                "expected_plan_id does not match the current timeline preview."
            )
        if plan["apply_supported"] is not True:
            reasons = plan["blockers"] + plan["unsupported_capabilities"]
            raise TakeSequenceTimelineApplyError(
                "Timeline application is blocked: " + ", ".join(reasons)
            )
        if existing is None:
            receipt = _new_receipt(receipt_id, inputs, plan)
            self._persist(path, receipt)
        else:
            receipt = existing
            if receipt.get("plan") != plan:
                raise TakeSequenceTimelineApplyError(
                    "Current timeline application plan changed during recovery."
                )

        source = plan["source_timeline"]
        duplicate_result = self._step(
            path,
            receipt,
            0,
            lambda: self._gateway.duplicate_timeline(
                source["timeline_id"],
                target_name,
                timeout_seconds=timeout,
                idempotency_key=_step_key(receipt_id, "duplicate"),
            ),
            _sanitize_duplicate,
        )
        target = _duplicate_target(duplicate_result, source, target_name)
        receipt["target_timeline"] = target
        self._persist(path, receipt)

        audio_count = plan["audio_item_count"]
        track_result = self._step(
            path,
            receipt,
            1,
            lambda: self._gateway.ensure_timeline_tracks(
                target["timeline_id"],
                1,
                1 if audio_count else 0,
                timeout_seconds=timeout,
                idempotency_key=_step_key(receipt_id, "tracks"),
            ),
            _sanitize_tracks,
        )
        if audio_count and track_result["audio_track_count"] < 1:
            raise TakeSequenceTimelineApplyError("Target has no audio track.")
        video_placements = [
            _provider_placement(placement, "video")
            for placement in plan["placements"]
        ]
        video_result = self._step(
            path,
            receipt,
            2,
            lambda: self._gateway.insert_clips(
                target["timeline_id"],
                video_placements,
                timeout_seconds=timeout,
                idempotency_key=_step_key(receipt_id, "video"),
            ),
            _sanitize_insert,
        )
        inserted = _verify_batch_result(
            target["timeline_id"],
            video_placements,
            video_result,
            [
                placement["timeline_end_position_frames"]
                - placement["position_frames"]
                for placement in plan["placements"]
            ],
        )

        audio_placements = [
            _provider_placement(placement, "audio")
            for placement in plan["placements"]
            if placement["has_audio"]
        ]
        if audio_placements:
            audio_result = self._step(
                path,
                receipt,
                3,
                lambda: self._gateway.insert_clips(
                    target["timeline_id"],
                    audio_placements,
                    timeout_seconds=timeout,
                    idempotency_key=_step_key(receipt_id, "audio"),
                ),
                _sanitize_insert,
            )
            inserted.extend(
                _verify_batch_result(
                    target["timeline_id"],
                    audio_placements,
                    audio_result,
                    [
                        placement["timeline_end_position_frames"]
                        - placement["position_frames"]
                        for placement in plan["placements"]
                        if placement["has_audio"]
                    ],
                )
            )
        else:
            receipt["operations"][3] = {
                "operation": "insert_audio",
                "status": "skipped",
                "backup_created": False,
                "result": None,
            }
            self._persist(path, receipt)

        target_readback = self._gateway.timeline_items(
            target["timeline_id"], timeout_seconds=timeout
        )
        _verify_target_readback(target, inserted, target_readback)
        source_readback = self._gateway.timeline_items(
            source["timeline_id"], timeout_seconds=timeout
        )
        source_after = _timeline_snapshot(
            source_readback, source["timeline_id"], source["name"]
        )
        if source_after["snapshot_sha256"] != source["snapshot_sha256"]:
            raise TakeSequenceTimelineApplyError(
                "Source timeline changed during duplicate-timeline application."
            )
        receipt["inserted_items"] = inserted
        receipt["target_readback_sha256"] = _canonical_sha256(
            _timeline_snapshot(target_readback, target["timeline_id"], target_name)
        )
        receipt["source_unchanged"] = True
        receipt["status"] = "applied"
        self._persist(path, receipt)
        return receipt

    def get(
        self,
        receipt_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return one receipt and verify an applied target/source live."""
        identifier = _sha256(receipt_id, "receipt_id")
        path = self._receipts_root / f"{identifier}.json"
        if not path.is_file():
            raise TakeSequenceTimelineApplyError(
                "The timeline application receipt was not found."
            )
        receipt = read_json_object(path)
        validate_contract("take-sequence-timeline-apply-result", receipt)
        if receipt.get("receipt_id") != identifier:
            raise TakeSequenceTimelineApplyError(
                "Stored timeline application receipt identity is invalid."
            )
        if receipt.get("status") != "applied":
            return receipt
        timeout = _timeout(timeout_seconds)
        target = receipt["target_timeline"]
        target_readback = self._gateway.timeline_items(
            target["timeline_id"], timeout_seconds=timeout
        )
        _verify_target_readback(
            target, receipt["inserted_items"], target_readback
        )
        source = receipt["plan"]["source_timeline"]
        source_readback = self._gateway.timeline_items(
            source["timeline_id"], timeout_seconds=timeout
        )
        source_after = _timeline_snapshot(
            source_readback, source["timeline_id"], source["name"]
        )
        if source_after["snapshot_sha256"] != source["snapshot_sha256"]:
            raise TakeSequenceTimelineApplyError(
                "Source timeline no longer matches the application receipt."
            )
        return receipt

    def _preview(
        self,
        *,
        media_import_receipt_id: str,
        target_timeline_name: str,
        timeout_seconds: float,
        check_target_name: bool,
    ) -> dict[str, Any]:
        import_id = _sha256(
            media_import_receipt_id, "media_import_receipt_id"
        )
        target_name = _timeline_name(target_timeline_name)
        receipt = self._imports.get(import_id)
        validate_contract("take-sequence-media-import-result", receipt)
        if receipt.get("receipt_id") != import_id or receipt.get("status") != "applied":
            raise TakeSequenceTimelineApplyError(
                "A completed M55.5 media import receipt is required."
            )
        mapping = self._mapping.preview(
            binding_id=receipt["binding_id"],
            assembly_name=receipt["assembly_name"],
            timeline_id=receipt["target_timeline_id"],
            timeout_seconds=timeout_seconds,
        )
        validate_contract("take-sequence-timeline-preview", mapping)
        if mapping.get("plan_id") != receipt.get("mapping_plan_id"):
            raise TakeSequenceTimelineApplyError(
                "Current timeline mapping does not match the import receipt."
            )
        source_target = mapping["target_timeline"]
        if target_name == source_target["name"]:
            raise TakeSequenceTimelineApplyError(
                "target_timeline_name must differ from the source timeline."
            )
        source_readback = self._gateway.timeline_items(
            source_target["timeline_id"], timeout_seconds=timeout_seconds
        )
        source_snapshot = _timeline_snapshot(
            source_readback,
            source_target["timeline_id"],
            source_target["name"],
        )
        blockers: list[str] = []
        if source_snapshot["item_count"] != 0:
            blockers.append("source_timeline_not_empty")
        target_available = True
        if check_target_name:
            target_available = _target_name_available(
                self._gateway.timelines(timeout_seconds), target_name
            )
            if not target_available:
                blockers.append("target_timeline_name_exists")

        imported = _imported_sources(receipt["sources"])
        private = _private_sources(
            self._bindings.resolve_sources(receipt["binding_id"])
        )
        audio_by_source: dict[str, bool] = {}
        placements: list[dict[str, Any]] = []
        for raw in mapping["placements"]:
            placement = _mapped_placement(raw)
            source_key = placement["source_key"]
            imported_source = imported.get(source_key)
            private_source = private.get(source_key)
            if imported_source is None or private_source is None:
                raise TakeSequenceTimelineApplyError(
                    "Mapped source is missing from import or private binding."
                )
            if (
                placement["order"] not in imported_source["orders"]
                or placement["display_name"] != imported_source["display_name"]
                or placement["display_name"] != private_source["display_name"]
            ):
                raise TakeSequenceTimelineApplyError(
                    "Mapped source identity changed after media import."
                )
            has_audio = audio_by_source.get(source_key)
            if has_audio is None:
                has_audio = self._audio.has_audio(Path(private_source["path"]))
                audio_by_source[source_key] = has_audio
            placements.append(
                {
                    **placement,
                    "asset_id": imported_source["asset_id"],
                    "has_audio": has_audio,
                }
            )

        capabilities = self._capabilities()
        if not isinstance(capabilities, dict):
            raise TakeSequenceTimelineApplyError(
                "Resolve capability snapshot is invalid."
            )
        unsupported = [
            capability
            for capability in REQUIRED_CAPABILITIES
            if capabilities.get(capability) is not True
        ]
        audio_count = sum(placement["has_audio"] for placement in placements)
        warnings = []
        if audio_count < len(placements):
            warnings.append(
                "One or more approved sources have no local audio stream; only "
                "their video ranges will be inserted."
            )
        payload = {
            "timeline_apply_plan_version": PLAN_VERSION,
            "status": "preview",
            "inputs": {
                "media_import_receipt_id": import_id,
                "target_timeline_name": target_name,
            },
            "import_receipt_sha256": _canonical_sha256(receipt),
            "mapping_plan_id": receipt["mapping_plan_id"],
            "source_timeline": source_snapshot,
            "target_name_available": target_available,
            "placements": placements,
            "placement_count": len(placements),
            "video_item_count": len(placements),
            "audio_item_count": audio_count,
            "required_capabilities": list(REQUIRED_CAPABILITIES),
            "unsupported_capabilities": unsupported,
            "blockers": blockers,
            "warnings": warnings,
            "paths_redacted": True,
            "source_timeline_modified": False,
            "apply_supported": not blockers and not unsupported,
        }
        result = {"plan_id": _canonical_sha256(payload), **payload}
        validate_contract("take-sequence-timeline-apply-preview", result)
        return result

    def _step(
        self,
        path: Path,
        receipt: dict[str, Any],
        index: int,
        callback: Callable[[], dict[str, Any]],
        sanitizer: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        operation = receipt["operations"][index]
        if operation["status"] == "applied":
            result = operation.get("result")
            if not isinstance(result, dict):
                raise TakeSequenceTimelineApplyError(
                    "Applied timeline operation has no stored result."
                )
            return result
        raw = callback()
        if not isinstance(raw, dict):
            raise TakeSequenceTimelineApplyError(
                "Timeline provider operation returned no object."
            )
        result = sanitizer(raw)
        operation["status"] = "applied"
        operation["backup_created"] = True
        operation["result"] = result
        self._persist(path, receipt)
        return result

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("take-sequence-timeline-apply-preview", receipt["plan"])
        validate_contract("take-sequence-timeline-apply-result", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)


def _new_receipt(
    receipt_id: str,
    inputs: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "apply_version": APPLY_VERSION,
        "receipt_id": receipt_id,
        "status": "in_progress",
        "inputs": inputs,
        "plan": plan,
        "target_timeline": None,
        "operations": [
            {
                "operation": operation,
                "status": "pending",
                "backup_created": False,
                "result": None,
            }
            for operation in (
                "duplicate_timeline",
                "ensure_timeline_tracks",
                "insert_video",
                "insert_audio",
            )
        ],
        "inserted_items": [],
        "target_readback_sha256": None,
        "source_unchanged": False,
        "paths_redacted": True,
    }


def _sanitize_duplicate(value: dict[str, Any]) -> dict[str, Any]:
    _backup(value)
    source = value.get("source_timeline")
    target = value.get("timeline")
    if not isinstance(source, dict) or not isinstance(target, dict):
        raise TakeSequenceTimelineApplyError("Duplicate result is incomplete.")
    return {
        "source_timeline": _timeline_identity(source),
        "timeline": _timeline_identity(target),
    }


def _sanitize_tracks(value: dict[str, Any]) -> dict[str, Any]:
    _backup(value)
    timeline = value.get("timeline")
    after = value.get("after")
    if not isinstance(timeline, dict) or not isinstance(after, dict):
        raise TakeSequenceTimelineApplyError("Track result is incomplete.")
    timeline_id = _bounded_text(timeline.get("timeline_id"), "timeline ID")
    video = _non_negative_int(after.get("video_track_count"), "video tracks")
    audio = _non_negative_int(after.get("audio_track_count"), "audio tracks")
    if video < 1:
        raise TakeSequenceTimelineApplyError("Target has no video track.")
    return {
        "timeline_id": timeline_id,
        "video_track_count": video,
        "audio_track_count": audio,
    }


def _sanitize_insert(value: dict[str, Any]) -> dict[str, Any]:
    _backup(value)
    timeline_id = _bounded_text(value.get("timeline_id"), "timeline ID")
    items = value.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise TakeSequenceTimelineApplyError("Insert result items are invalid.")
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise TakeSequenceTimelineApplyError("Inserted item is invalid.")
        placement_index = _non_negative_int(
            item.get("placement_index"), "placement index"
        )
        if placement_index >= MAX_ITEMS:
            raise TakeSequenceTimelineApplyError(
                "Inserted placement index exceeds the bounded limit."
            )
        normalized.append(
            {
                "placement_index": placement_index,
                "asset_id": _bounded_text(item.get("asset_id"), "asset ID"),
                "timeline_item_id": _bounded_text(
                    item.get("timeline_item_id"), "timeline item ID"
                ),
                "name": _bounded_text(item.get("name"), "item name", 255),
                "timeline_start_frame": _non_negative_int(
                    item.get("timeline_start_frame"), "timeline start"
                ),
                "timeline_end_frame": _positive_int(
                    item.get("timeline_end_frame"), "timeline end"
                ),
                "source_start_frame": _non_negative_int(
                    item.get("source_start_frame"), "source start"
                ),
                "source_end_frame": _non_negative_int(
                    item.get("source_end_frame"), "source end"
                ),
                "track_type": _track_type(item.get("track_type")),
                "track_index": _positive_int(
                    item.get("track_index"), "track index"
                ),
            }
        )
    return {"timeline_id": timeline_id, "items": normalized}


def _backup(value: dict[str, Any]) -> None:
    backup = value.get("backup_path")
    if not isinstance(backup, str) or not backup:
        raise TakeSequenceTimelineApplyError(
            "Provider write did not report a project backup."
        )


def _duplicate_target(
    result: dict[str, Any], source: dict[str, Any], expected_name: str
) -> dict[str, str]:
    actual_source = result.get("source_timeline")
    target = result.get("timeline")
    if (
        actual_source
        != {"timeline_id": source["timeline_id"], "name": source["name"]}
        or not isinstance(target, dict)
        or target.get("name") != expected_name
        or target.get("timeline_id") == source["timeline_id"]
    ):
        raise TakeSequenceTimelineApplyError(
            "Duplicate timeline identity does not match the reviewed plan."
        )
    return _timeline_identity(target)


def _timeline_identity(value: dict[str, Any]) -> dict[str, str]:
    return {
        "timeline_id": _bounded_text(value.get("timeline_id"), "timeline ID"),
        "name": _bounded_text(value.get("name"), "timeline name"),
    }


def _timeline_snapshot(
    value: object, expected_id: str, expected_name: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TakeSequenceTimelineApplyError("Timeline readback is invalid.")
    if value.get("timeline_id") != expected_id or value.get("name") != expected_name:
        raise TakeSequenceTimelineApplyError(
            "Timeline readback identity changed."
        )
    items = value.get("items")
    if not isinstance(items, list) or len(items) > 200:
        raise TakeSequenceTimelineApplyError("Timeline item readback is invalid.")
    normalized: list[dict[str, Any]] = []
    item_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise TakeSequenceTimelineApplyError("Timeline item is invalid.")
        item_id = _bounded_text(item.get("timeline_item_id"), "timeline item ID")
        if item_id in item_ids:
            raise TakeSequenceTimelineApplyError(
                "Timeline item identity is duplicated."
            )
        item_ids.add(item_id)
        normalized.append(
            {
                "timeline_item_id": item_id,
                "name": _bounded_text(item.get("name"), "timeline item name", 255),
                "track_type": _track_type(item.get("track_type")),
                "track_index": _positive_int(item.get("track_index"), "track index"),
                "source_type": _bounded_text(
                    item.get("source_type"), "source type", 16
                ),
                "duration_frames": _positive_int(
                    item.get("duration_frames"), "duration frames"
                ),
                "timeline_start_frame": _non_negative_int(
                    item.get("timeline_start_frame"), "timeline start"
                ),
                "timeline_end_frame": _positive_int(
                    item.get("timeline_end_frame"), "timeline end"
                ),
                "source_start_frame": item.get("source_start_frame"),
                "source_end_frame": item.get("source_end_frame"),
            }
        )
        normalized_item = normalized[-1]
        if (
            normalized_item["timeline_end_frame"]
            <= normalized_item["timeline_start_frame"]
            or normalized_item["duration_frames"]
            != normalized_item["timeline_end_frame"]
            - normalized_item["timeline_start_frame"]
            or (
                normalized_item["source_type"] == "media"
                and (
                    not isinstance(normalized_item["source_start_frame"], int)
                    or isinstance(normalized_item["source_start_frame"], bool)
                    or not isinstance(normalized_item["source_end_frame"], int)
                    or isinstance(normalized_item["source_end_frame"], bool)
                )
            )
            or (
                normalized_item["source_type"] == "generated"
                and (
                    normalized_item["source_start_frame"] is not None
                    or normalized_item["source_end_frame"] is not None
                )
            )
            or normalized_item["source_type"] not in {"media", "generated"}
        ):
            raise TakeSequenceTimelineApplyError("Timeline item bounds are invalid.")
    normalized.sort(
        key=lambda item: (
            item["track_type"],
            item["track_index"],
            item["timeline_start_frame"],
            item["timeline_item_id"],
        )
    )
    identity = {
        "timeline_id": expected_id,
        "name": expected_name,
        "items": normalized,
        "item_count": len(normalized),
    }
    return {**identity, "snapshot_sha256": _canonical_sha256(identity)}


def _target_name_available(values: object, target_name: str) -> bool:
    if not isinstance(values, list) or len(values) > 1_000:
        raise TakeSequenceTimelineApplyError("Timeline list is invalid.")
    names: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            raise TakeSequenceTimelineApplyError("Timeline list item is invalid.")
        _bounded_text(value.get("timeline_id"), "timeline ID")
        names.append(_bounded_text(value.get("name"), "timeline name"))
    return target_name.casefold() not in {name.casefold() for name in names}


def _imported_sources(values: object) -> dict[str, dict[str, Any]]:
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_ITEMS:
        raise TakeSequenceTimelineApplyError("Imported source list is invalid.")
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict):
            raise TakeSequenceTimelineApplyError("Imported source is invalid.")
        key = _sha256(value.get("source_key"), "source key")
        result[key] = {
            "asset_id": _bounded_text(value.get("asset_id"), "asset ID"),
            "display_name": _bounded_text(
                value.get("display_name"), "display name", 255
            ),
            "orders": _orders(value.get("orders")),
        }
    if len(result) != len(values):
        raise TakeSequenceTimelineApplyError("Imported source key is duplicated.")
    return result


def _private_sources(values: object) -> dict[str, dict[str, str]]:
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_ITEMS:
        raise TakeSequenceTimelineApplyError("Private source list is invalid.")
    result: dict[str, dict[str, str]] = {}
    for value in values:
        if not isinstance(value, dict):
            raise TakeSequenceTimelineApplyError("Private source is invalid.")
        key = _sha256(value.get("fingerprint"), "source fingerprint")
        path = value.get("path")
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise TakeSequenceTimelineApplyError("Private source path is invalid.")
        current = {
            "path": path,
            "display_name": _bounded_text(
                value.get("display_name"), "display name", 255
            ),
        }
        existing = result.get(key)
        if existing is not None and existing != current:
            raise TakeSequenceTimelineApplyError(
                "Private source fingerprint is ambiguous."
            )
        result[key] = current
    return result


def _mapped_placement(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TakeSequenceTimelineApplyError("Mapped placement is invalid.")
    start = _non_negative_int(value.get("source_start_frame"), "source start")
    end = _non_negative_int(value.get("source_end_frame"), "source end")
    position = _non_negative_int(value.get("position_frames"), "position")
    timeline_end = _positive_int(
        value.get("timeline_end_position_frames"), "timeline end"
    )
    if end <= start or timeline_end <= position:
        raise TakeSequenceTimelineApplyError("Mapped placement range is invalid.")
    return {
        "order": _positive_int(value.get("order"), "order"),
        "source_key": _sha256(value.get("fingerprint"), "source fingerprint"),
        "display_name": _bounded_text(
            value.get("display_name"), "display name", 255
        ),
        "source_start_frame": start,
        "source_end_frame": end,
        "position_frames": position,
        "timeline_end_position_frames": timeline_end,
    }


def _provider_placement(value: dict[str, Any], track_type: str) -> dict[str, Any]:
    return {
        "asset_id": value["asset_id"],
        "source_start_frame": value["source_start_frame"],
        "source_end_frame": value["source_end_frame"],
        "position_frames": value["position_frames"],
        "track_type": track_type,
        "track_index": 1,
    }


def _verify_batch_result(
    timeline_id: str,
    placements: list[dict[str, Any]],
    result: dict[str, Any],
    expected_durations: list[int],
) -> list[dict[str, Any]]:
    items = result.get("items")
    if result.get("timeline_id") != timeline_id or not isinstance(items, list):
        raise TakeSequenceTimelineApplyError("Batch insertion result is invalid.")
    if len(items) != len(placements) or len(expected_durations) != len(placements):
        raise TakeSequenceTimelineApplyError(
            "Batch insertion did not return every planned item."
        )
    origins: set[int] = set()
    item_ids: set[str] = set()
    verified: list[dict[str, Any]] = []
    for index, (placement, item) in enumerate(zip(placements, items, strict=True)):
        if not isinstance(item, dict):
            raise TakeSequenceTimelineApplyError("Inserted item is invalid.")
        item_id = _bounded_text(item.get("timeline_item_id"), "timeline item ID")
        start = _non_negative_int(item.get("timeline_start_frame"), "timeline start")
        end = _positive_int(item.get("timeline_end_frame"), "timeline end")
        source_start = _non_negative_int(
            item.get("source_start_frame"), "source start"
        )
        source_end = _non_negative_int(item.get("source_end_frame"), "source end")
        if (
            item.get("placement_index") != index
            or item.get("asset_id") != placement["asset_id"]
            or item.get("track_type") != placement["track_type"]
            or item.get("track_index") != 1
            or item_id in item_ids
            or end <= start
            or end - start != expected_durations[index]
            or source_start != placement["source_start_frame"]
            or not source_start < source_end <= placement["source_end_frame"]
        ):
            raise TakeSequenceTimelineApplyError(
                f"Inserted item {index} does not match the reviewed placement."
            )
        item_ids.add(item_id)
        origins.add(start - placement["position_frames"])
        verified.append(
            {
                "timeline_item_id": item_id,
                "name": _bounded_text(item.get("name"), "item name", 255),
                "track_type": placement["track_type"],
                "track_index": 1,
                "timeline_start_frame": start,
                "timeline_end_frame": end,
                "source_start_frame": source_start,
                "source_end_frame": source_end,
            }
        )
    if len(origins) != 1:
        raise TakeSequenceTimelineApplyError(
            "Inserted items do not share one timeline origin."
        )
    return verified


def _verify_target_readback(
    target: dict[str, Any],
    inserted: list[dict[str, Any]],
    readback: object,
) -> None:
    snapshot = _timeline_snapshot(
        readback, target["timeline_id"], target["name"]
    )
    if snapshot["item_count"] != len(inserted):
        raise TakeSequenceTimelineApplyError(
            "Target timeline contains unexpected items after application."
        )
    discovered = {
        item["timeline_item_id"]: item for item in snapshot["items"]
    }
    fields = (
        "name",
        "track_type",
        "track_index",
        "timeline_start_frame",
        "timeline_end_frame",
        "source_start_frame",
        "source_end_frame",
    )
    for item in inserted:
        actual = discovered.get(item["timeline_item_id"])
        if (
            actual is None
            or actual.get("source_type") != "media"
            or actual.get("duration_frames")
            != item["timeline_end_frame"] - item["timeline_start_frame"]
            or any(actual.get(field) != item[field] for field in fields)
        ):
            raise TakeSequenceTimelineApplyError(
                "Inserted timeline item did not persist exactly."
            )


def _orders(value: object) -> list[int]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= MAX_ITEMS
        or any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or not 1 <= item <= MAX_ITEMS
            for item in value
        )
        or len(set(value)) != len(value)
    ):
        raise TakeSequenceTimelineApplyError("Source orders are invalid.")
    return value


def _timeline_name(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 128:
        raise TakeSequenceTimelineApplyError(
            "target_timeline_name must contain 1 to 128 characters."
        )
    return value.strip()


def _track_type(value: object) -> str:
    if value not in {"video", "audio"}:
        raise TakeSequenceTimelineApplyError("Timeline track type is invalid.")
    return str(value)


def _bounded_text(value: object, name: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise TakeSequenceTimelineApplyError(f"{name} is invalid.")
    return value


def _positive_int(value: object, name: str) -> int:
    result = _non_negative_int(value, name)
    if result <= 0:
        raise TakeSequenceTimelineApplyError(f"{name} must be positive.")
    return result


def _non_negative_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TakeSequenceTimelineApplyError(f"{name} is invalid.")
    return value


def _timeout(value: object) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or not 0 < float(value) <= 300
    ):
        raise TakeSequenceTimelineApplyError(
            "timeout_seconds must be greater than zero and no more than 300."
        )
    return float(value)


def _sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TakeSequenceTimelineApplyError(
            f"{name} must be a lowercase SHA-256 ID."
        )
    return value


def _step_key(receipt_id: str, operation: str) -> str:
    return hashlib.sha256(f"{receipt_id}:{operation}".encode()).hexdigest()


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
