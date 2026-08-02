"""M55.5 confirmed receipt-backed Media Pool import workflow."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import take_sequence_media_imports_directory
from transports.filesystem import atomic_write_json, read_json_object

IMPORT_VERSION = "1.0"
MAX_MEDIA_POOL_ITEMS = 10_000


class TakeSequenceMediaImportApplyError(ValueError):
    """Raised when confirmed sequence media cannot be imported safely."""


class MediaImportPreviewReader(Protocol):
    def preview(
        self,
        *,
        binding_id: str,
        assembly_name: str,
        timeline_id: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...


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


class MediaImportGateway(Protocol):
    def import_media(
        self,
        paths: list[str],
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...

    def media_pool_items(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...


class TakeSequenceMediaImporter:
    """Import exact bound sources once and persist a path-redacted receipt."""

    def __init__(
        self,
        previewer: MediaImportPreviewReader,
        mapping: TimelineMappingReader,
        bindings: PrivateBindingReader,
        gateway: MediaImportGateway,
        receipts_root: Path | None = None,
    ) -> None:
        self._previewer = previewer
        self._mapping = mapping
        self._bindings = bindings
        self._gateway = gateway
        self._receipts_root = (
            receipts_root or take_sequence_media_imports_directory()
        )

    def apply(
        self,
        *,
        binding_id: str,
        assembly_name: str,
        timeline_id: str,
        expected_plan_id: str,
        confirm_import: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Execute one exact reviewed batch import with durable idempotency."""
        inputs = _inputs(
            binding_id,
            assembly_name,
            timeline_id,
            expected_plan_id,
            confirm_import,
        )
        receipt_id = _canonical_sha256(inputs)
        receipt_path = self._receipts_root / f"{receipt_id}.json"
        if receipt_path.is_file():
            return self.get(receipt_id)

        preview = self._previewer.preview(
            binding_id=inputs["binding_id"],
            assembly_name=inputs["assembly_name"],
            timeline_id=inputs["timeline_id"],
            timeout_seconds=timeout_seconds,
        )
        if preview.get("plan_id") != inputs["expected_plan_id"]:
            raise TakeSequenceMediaImportApplyError(
                "expected_plan_id does not match the current import preview."
            )
        if preview.get("import_ready") is not True or preview.get(
            "requires_review"
        ) is not False:
            raise TakeSequenceMediaImportApplyError(
                "Media import preview requires collision review."
            )
        mapping_plan_id = _sha256(
            preview.get("mapping_plan_id"), "mapping plan ID"
        )
        media_pool_before = _sha256(
            preview.get("media_pool_snapshot_sha256"),
            "Media Pool snapshot ID",
        )
        sources = preview.get("sources")
        if not isinstance(sources, list) or not sources or any(
            not isinstance(source, dict) or source.get("action") != "import"
            for source in sources
        ):
            raise TakeSequenceMediaImportApplyError(
                "Media import preview sources are invalid."
            )
        if len(sources) > 100:
            raise TakeSequenceMediaImportApplyError(
                "Media import preview exceeds the bounded source limit."
            )

        mapping = self._mapping.preview(
            binding_id=inputs["binding_id"],
            assembly_name=inputs["assembly_name"],
            timeline_id=inputs["timeline_id"],
            timeout_seconds=timeout_seconds,
        )
        if mapping.get("plan_id") != mapping_plan_id:
            raise TakeSequenceMediaImportApplyError(
                "Timeline mapping changed after import preview."
            )
        source_metadata = _mapping_sources(mapping)
        private_sources = _private_sources(
            self._bindings.resolve_sources(inputs["binding_id"])
        )
        paths: list[str] = []
        for source in sources:
            source_key = _sha256(source.get("source_key"), "source key")
            display_name = _bounded_text(
                source.get("display_name"), "source display name", maximum=255
            )
            _orders(source.get("orders"))
            private = private_sources.get(source_key)
            mapped = source_metadata.get(source_key)
            if private is None or mapped is None:
                raise TakeSequenceMediaImportApplyError(
                    "Import source is missing from the verified binding or mapping."
                )
            if private["display_name"] != display_name:
                raise TakeSequenceMediaImportApplyError(
                    "Import source name changed after preview."
                )
            paths.append(private["path"])

        result = self._gateway.import_media(
            paths,
            timeout_seconds=timeout_seconds,
            idempotency_key=f"m55:{receipt_id[:24]}:import",
        )
        imported = _imported_items(result, sources)
        asset_ids = [item["asset_id"] for item in imported]
        metadata = self._gateway.editing_metadata(
            inputs["timeline_id"],
            asset_ids,
            timeout_seconds=timeout_seconds,
        )
        verified = _verify_metadata(
            metadata,
            inputs["timeline_id"],
            imported,
            source_metadata,
            sources,
        )
        after = _media_pool_identity(
            self._gateway.media_pool_items(timeout_seconds)
        )
        _verify_media_pool_readback(after, imported)
        receipt = {
            "import_version": IMPORT_VERSION,
            "receipt_id": receipt_id,
            "status": "applied",
            "plan_id": inputs["expected_plan_id"],
            "mapping_plan_id": mapping_plan_id,
            "binding_id": inputs["binding_id"],
            "assembly_name": inputs["assembly_name"],
            "target_timeline_id": inputs["timeline_id"],
            "media_pool_before_sha256": media_pool_before,
            "media_pool_after_sha256": _canonical_sha256(after),
            "sources": verified,
            "source_count": len(verified),
            "backup_created": True,
            "paths_redacted": True,
            "media_pool_modified": True,
            "timeline_modified": False,
            "apply_supported": True,
        }
        validate_contract("take-sequence-media-import-result", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(receipt_path, receipt)
        return receipt

    def get(self, receipt_id: str) -> dict[str, Any]:
        """Return one durable path-redacted confirmed import receipt."""
        identifier = _sha256(receipt_id, "receipt_id")
        path = self._receipts_root / f"{identifier}.json"
        if not path.is_file():
            raise TakeSequenceMediaImportApplyError(
                "The media import receipt was not found."
            )
        receipt = read_json_object(path)
        validate_contract("take-sequence-media-import-result", receipt)
        if receipt.get("receipt_id") != identifier:
            raise TakeSequenceMediaImportApplyError(
                "Stored media import receipt identity is invalid."
            )
        return receipt


def _inputs(
    binding_id: str,
    assembly_name: str,
    timeline_id: str,
    expected_plan_id: str,
    confirm_import: bool,
) -> dict[str, Any]:
    if confirm_import is not True:
        raise TakeSequenceMediaImportApplyError("confirm_import must be true.")
    if not isinstance(assembly_name, str) or not 1 <= len(assembly_name.strip()) <= 128:
        raise TakeSequenceMediaImportApplyError(
            "assembly_name must contain 1 to 128 characters."
        )
    if not isinstance(timeline_id, str) or not 1 <= len(timeline_id) <= 128:
        raise TakeSequenceMediaImportApplyError(
            "timeline_id must contain 1 to 128 characters."
        )
    return {
        "import_version": IMPORT_VERSION,
        "binding_id": _sha256(binding_id, "binding_id"),
        "assembly_name": assembly_name.strip(),
        "timeline_id": timeline_id,
        "expected_plan_id": _sha256(expected_plan_id, "expected_plan_id"),
    }


def _private_sources(values: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for source in values:
        fingerprint = _sha256(source.get("fingerprint"), "source fingerprint")
        path = source.get("path")
        display_name = source.get("display_name")
        if (
            not isinstance(path, str)
            or not Path(path).is_absolute()
            or not isinstance(display_name, str)
            or not display_name
        ):
            raise TakeSequenceMediaImportApplyError(
                "Private binding source is invalid."
            )
        existing = result.get(fingerprint)
        value = {"path": path, "display_name": display_name}
        if existing is not None and existing != value:
            raise TakeSequenceMediaImportApplyError(
                "Private binding fingerprint is ambiguous."
            )
        result[fingerprint] = value
    return result


def _mapping_sources(mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    placements = mapping.get("placements")
    if not isinstance(placements, list) or not placements:
        raise TakeSequenceMediaImportApplyError("Timeline mapping is incomplete.")
    result: dict[str, dict[str, Any]] = {}
    for placement in placements:
        if not isinstance(placement, dict):
            raise TakeSequenceMediaImportApplyError("Mapped placement is invalid.")
        key = _sha256(placement.get("fingerprint"), "source fingerprint")
        rate = _positive_number(placement.get("source_frame_rate"), "source FPS")
        end = placement.get("source_end_frame")
        if not isinstance(end, int) or isinstance(end, bool) or end < 0:
            raise TakeSequenceMediaImportApplyError(
                "Mapped source frame bound is invalid."
            )
        current = result.get(key)
        if current is None:
            result[key] = {"frame_rate": rate, "max_source_end_frame": end}
        elif not math.isclose(current["frame_rate"], rate, abs_tol=1e-6):
            raise TakeSequenceMediaImportApplyError(
                "Mapped source frame rate is inconsistent."
            )
        else:
            current["max_source_end_frame"] = max(
                current["max_source_end_frame"], end
            )
    return result


def _imported_items(
    result: object,
    sources: list[dict[str, Any]],
) -> list[dict[str, str]]:
    items = result.get("items") if isinstance(result, dict) else None
    backup_path = result.get("backup_path") if isinstance(result, dict) else None
    if (
        not isinstance(items, list)
        or len(items) != len(sources)
        or not isinstance(backup_path, str)
        or not backup_path
    ):
        raise TakeSequenceMediaImportApplyError(
            "Resolve import result is incomplete."
        )
    by_name: dict[str, dict[str, str]] = {}
    asset_ids: set[str] = set()
    for item in items:
        asset_id = item.get("asset_id") if isinstance(item, dict) else None
        name = item.get("name") if isinstance(item, dict) else None
        if (
            not isinstance(asset_id, str)
            or not asset_id
            or asset_id in asset_ids
            or not isinstance(name, str)
            or not name
            or name.casefold() in by_name
        ):
            raise TakeSequenceMediaImportApplyError(
                "Resolve imported media identity is ambiguous."
            )
        asset_ids.add(asset_id)
        by_name[name.casefold()] = {"asset_id": asset_id, "name": name}
    imported: list[dict[str, str]] = []
    for source in sources:
        item = by_name.get(str(source["display_name"]).casefold())
        if item is None:
            raise TakeSequenceMediaImportApplyError(
                "Resolve import did not return every planned source name."
            )
        imported.append(item)
    return imported


def _verify_metadata(
    metadata: object,
    timeline_id: str,
    imported: list[dict[str, str]],
    mapped: dict[str, dict[str, Any]],
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    timeline = metadata.get("timeline") if isinstance(metadata, dict) else None
    assets = metadata.get("assets") if isinstance(metadata, dict) else None
    if (
        not isinstance(timeline, dict)
        or timeline.get("timeline_id") != timeline_id
        or not isinstance(assets, list)
        or len(assets) != len(imported)
    ):
        raise TakeSequenceMediaImportApplyError(
            "Imported media metadata readback is invalid."
        )
    assets_by_id = {
        asset.get("asset_id"): asset for asset in assets if isinstance(asset, dict)
    }
    verified: list[dict[str, Any]] = []
    for source, item in zip(sources, imported, strict=True):
        asset = assets_by_id.get(item["asset_id"])
        source_key = str(source["source_key"])
        expected = mapped[source_key]
        if not isinstance(asset, dict):
            raise TakeSequenceMediaImportApplyError(
                "Imported asset is missing from metadata readback."
            )
        duration = asset.get("duration_frames")
        frame_rate = asset.get("frame_rate")
        verified_frame_rate = _optional_positive_number(frame_rate)
        if (
            asset.get("name") != item["name"]
            or not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration <= expected["max_source_end_frame"]
            or verified_frame_rate is None
            or not math.isclose(
                verified_frame_rate,
                expected["frame_rate"],
                rel_tol=0.0,
                abs_tol=1e-6,
            )
        ):
            raise TakeSequenceMediaImportApplyError(
                "Imported asset metadata does not cover the approved source ranges."
            )
        verified.append(
            {
                "source_key": source_key,
                "display_name": source["display_name"],
                "orders": source["orders"],
                "asset_id": item["asset_id"],
                "duration_frames": duration,
                "frame_rate": verified_frame_rate,
            }
        )
    return verified


def _media_pool_identity(value: object) -> dict[str, Any]:
    items = value.get("items") if isinstance(value, dict) else None
    folder_count = value.get("folder_count") if isinstance(value, dict) else None
    if (
        not isinstance(items, list)
        or len(items) > MAX_MEDIA_POOL_ITEMS
        or not isinstance(folder_count, int)
        or isinstance(folder_count, bool)
        or not 0 <= folder_count <= 1_000
    ):
        raise TakeSequenceMediaImportApplyError("Media Pool readback is invalid.")
    normalized: list[dict[str, Any]] = []
    asset_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "asset_id",
            "name",
            "folder_id",
            "folder_path",
        }:
            raise TakeSequenceMediaImportApplyError("Media Pool item is invalid.")
        asset_id = _bounded_text(item["asset_id"], "Media Pool asset ID")
        name = _bounded_text(
            item["name"], "Media Pool item name", maximum=255
        )
        folder_id = _bounded_text(item["folder_id"], "Media Pool folder ID")
        folder_path = item["folder_path"]
        if (
            asset_id in asset_ids
            or not isinstance(folder_path, list)
            or not 1 <= len(folder_path) <= 1_000
            or not all(
                isinstance(part, str) and 1 <= len(part) <= 255
                for part in folder_path
            )
        ):
            raise TakeSequenceMediaImportApplyError("Media Pool item is invalid.")
        asset_ids.add(asset_id)
        normalized.append(
            {
                "asset_id": asset_id,
                "name": name,
                "folder_id": folder_id,
                "folder_path": list(folder_path),
            }
        )
    normalized.sort(
        key=lambda item: (
            str(item["folder_path"]),
            str(item["name"]),
            str(item["asset_id"]),
        )
    )
    return {"items": normalized, "folder_count": folder_count}


def _verify_media_pool_readback(
    snapshot: dict[str, Any],
    imported: list[dict[str, str]],
) -> None:
    identities = {
        (item.get("asset_id"), item.get("name"))
        for item in snapshot["items"]
        if isinstance(item, dict)
    }
    if any((item["asset_id"], item["name"]) not in identities for item in imported):
        raise TakeSequenceMediaImportApplyError(
            "Imported assets did not persist in Media Pool readback."
        )


def _positive_number(value: object, name: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise TakeSequenceMediaImportApplyError(f"{name} is invalid.")
    return float(value)


def _bounded_text(value: object, name: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise TakeSequenceMediaImportApplyError(f"{name} is invalid.")
    return value


def _orders(value: object) -> list[int]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 100
        or any(
            not isinstance(order, int)
            or isinstance(order, bool)
            or not 1 <= order <= 100
            for order in value
        )
        or len(set(value)) != len(value)
    ):
        raise TakeSequenceMediaImportApplyError("source orders are invalid.")
    return value


def _optional_positive_number(value: object) -> float | None:
    try:
        return _positive_number(value, "frame rate")
    except TakeSequenceMediaImportApplyError:
        return None


def _sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TakeSequenceMediaImportApplyError(
            f"{name} must be a lowercase SHA-256 ID."
        )
    return value


def _canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
