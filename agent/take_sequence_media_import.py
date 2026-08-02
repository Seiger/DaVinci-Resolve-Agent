"""M55.4 read-only Media Pool import preview for a mapped take sequence."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from agent.contracts import validate_contract

IMPORT_PREVIEW_VERSION = "1.0"
MAX_SOURCES = 100
MAX_MEDIA_POOL_ITEMS = 10_000
MAX_NAME_MATCHES = 100


class TakeSequenceMediaImportError(ValueError):
    """Raised when a safe Media Pool import preview cannot be produced."""


class TakeSequenceTimelineMappingReader(Protocol):
    """Read-only M55.3 live timeline mapping boundary."""

    def preview(
        self,
        *,
        binding_id: str,
        assembly_name: str,
        timeline_id: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...


class MediaPoolReader(Protocol):
    """Existing bounded provider-neutral Media Pool discovery boundary."""

    def media_pool_items(
        self,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...


class TakeSequenceMediaImportWorkflow:
    """Plan source imports conservatively without exposing paths or writing."""

    def __init__(
        self,
        mapping: TakeSequenceTimelineMappingReader,
        media_pool: MediaPoolReader,
    ) -> None:
        self._mapping = mapping
        self._media_pool = media_pool

    def preview(
        self,
        *,
        binding_id: str,
        assembly_name: str,
        timeline_id: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return a deterministic import plan bound to current Media Pool state."""
        mapping = self._mapping.preview(
            binding_id=binding_id,
            assembly_name=assembly_name,
            timeline_id=timeline_id,
            timeout_seconds=timeout_seconds,
        )
        mapping_plan_id = _sha256(mapping.get("plan_id"), "mapping plan ID")
        binding_identifier = _sha256(binding_id, "binding_id")
        if mapping.get("binding_id") != binding_identifier:
            raise TakeSequenceMediaImportError(
                "Timeline mapping targets a different source binding."
            )
        placements = mapping.get("placements")
        target = mapping.get("target_timeline")
        if not isinstance(placements, list) or not placements:
            raise TakeSequenceMediaImportError("Timeline mapping is incomplete.")
        if not isinstance(target, dict) or target.get("timeline_id") != timeline_id:
            raise TakeSequenceMediaImportError(
                "Timeline mapping target identity is invalid."
            )

        media_pool = _media_pool_snapshot(
            self._media_pool.media_pool_items(timeout_seconds)
        )
        sources = _unique_sources(placements)
        source_name_counts: dict[str, int] = {}
        for source in sources:
            key = source["display_name"].casefold()
            source_name_counts[key] = source_name_counts.get(key, 0) + 1
        candidates: list[dict[str, Any]] = []
        for source in sources:
            matches = [
                item
                for item in media_pool["items"]
                if item["name"].casefold() == source["display_name"].casefold()
            ]
            if len(matches) > MAX_NAME_MATCHES:
                raise TakeSequenceMediaImportError(
                    "Same-name Media Pool matches exceed the bounded review limit."
                )
            duplicate_source_name = (
                source_name_counts[source["display_name"].casefold()] > 1
            )
            candidates.append(
                {
                    **source,
                    "action": (
                        "review_source_name_collision"
                        if duplicate_source_name
                        else "review_name_collision"
                        if matches
                        else "import"
                    ),
                    "name_matches": matches,
                    "name_match_count": len(matches),
                }
            )
        collision_count = sum(
            candidate["action"] != "import"
            for candidate in candidates
        )
        payload = {
            "import_preview_version": IMPORT_PREVIEW_VERSION,
            "status": "preview",
            "mapping_plan_id": mapping_plan_id,
            "binding_id": binding_identifier,
            "target_timeline_id": timeline_id,
            "media_pool_snapshot_sha256": _canonical_sha256(media_pool),
            "media_pool_item_count": len(media_pool["items"]),
            "media_pool_folder_count": media_pool["folder_count"],
            "sources": candidates,
            "source_count": len(candidates),
            "collision_count": collision_count,
            "import_ready": collision_count == 0,
            "requires_review": collision_count > 0,
            "media_pool_verified": True,
            "paths_redacted": True,
            "media_pool_modified": False,
            "timeline_modified": False,
            "apply_supported": False,
        }
        result = {"plan_id": _canonical_sha256(payload), **payload}
        validate_contract("take-sequence-media-import-preview", result)
        return result


def _media_pool_snapshot(value: object) -> dict[str, Any]:
    items = value.get("items") if isinstance(value, dict) else None
    folder_count = value.get("folder_count") if isinstance(value, dict) else None
    if (
        not isinstance(items, list)
        or len(items) > MAX_MEDIA_POOL_ITEMS
        or not isinstance(folder_count, int)
        or isinstance(folder_count, bool)
        or not 0 <= folder_count <= 1_000
    ):
        raise TakeSequenceMediaImportError("Media Pool snapshot is invalid.")
    normalized: list[dict[str, Any]] = []
    asset_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "asset_id",
            "name",
            "folder_id",
            "folder_path",
        }:
            raise TakeSequenceMediaImportError("Media Pool item is invalid.")
        asset_id = _bounded_text(item["asset_id"], "Media Pool asset ID")
        name = _bounded_text(item["name"], "Media Pool item name", maximum=255)
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
            raise TakeSequenceMediaImportError("Media Pool item is invalid.")
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
            item["folder_path"],
            item["name"],
            item["asset_id"],
        )
    )
    return {"items": normalized, "folder_count": folder_count}


def _unique_sources(placements: list[object]) -> list[dict[str, Any]]:
    by_fingerprint: dict[str, dict[str, Any]] = {}
    for placement in placements:
        if not isinstance(placement, dict):
            raise TakeSequenceMediaImportError("Mapped placement is invalid.")
        fingerprint = _sha256(placement.get("fingerprint"), "source fingerprint")
        display_name = _bounded_text(
            placement.get("display_name"), "source display name", maximum=255
        )
        order = placement.get("order")
        if (
            not isinstance(order, int)
            or isinstance(order, bool)
            or not 1 <= order <= MAX_SOURCES
        ):
            raise TakeSequenceMediaImportError("Mapped source order is invalid.")
        existing = by_fingerprint.get(fingerprint)
        if existing is None:
            by_fingerprint[fingerprint] = {
                "source_key": fingerprint,
                "display_name": display_name,
                "orders": [order],
            }
        elif existing["display_name"] != display_name:
            raise TakeSequenceMediaImportError(
                "One source fingerprint has conflicting display names."
            )
        elif order in existing["orders"]:
            raise TakeSequenceMediaImportError("Mapped source order is duplicated.")
        else:
            existing["orders"].append(order)
    if not 1 <= len(by_fingerprint) <= MAX_SOURCES:
        raise TakeSequenceMediaImportError("Mapped source count is invalid.")
    sources = list(by_fingerprint.values())
    for source in sources:
        source["orders"].sort()
    return sorted(sources, key=lambda source: source["orders"][0])


def _bounded_text(value: object, name: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise TakeSequenceMediaImportError(
            f"{name} must contain 1 to {maximum} characters."
        )
    return value


def _sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TakeSequenceMediaImportError(
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
