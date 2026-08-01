"""Provider-neutral M43 finalization of a compacted synchronized timeline."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import (
    pause_compaction_finalizations_directory,
    pause_compactions_directory,
    picture_in_picture_directory,
    synchronized_links_directory,
)
from transports.filesystem import atomic_write_json, read_json_object

FINALIZATION_VERSION = "1.0"
REQUIRED_CAPABILITIES = ("clip.link", "clip.read", "clip.transform")


class PauseCompactionFinalizationError(ValueError):
    """Raised when M42 segments cannot be finalized safely."""


class PauseCompactionFinalizationGateway(Protocol):
    """Provider-neutral bounded operations required by M43."""

    def set_clip_link_groups(
        self,
        timeline_id: str,
        groups: list[list[str]],
        linked: bool,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def set_clip_transforms(
        self,
        timeline_id: str,
        items: list[dict[str, Any]],
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]: ...


class PauseCompactionFinalizer:
    """Propagate approved screen links and webcam layout to M42 segments."""

    def __init__(
        self,
        *,
        gateway: PauseCompactionFinalizationGateway,
        capabilities: Callable[[], dict[str, Any]],
        pause_compactions_root: Path | None = None,
        picture_in_picture_root: Path | None = None,
        synchronized_links_root: Path | None = None,
        receipts_root: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._capabilities = capabilities
        self._pause_compactions_root = (
            pause_compactions_directory()
            if pause_compactions_root is None
            else pause_compactions_root
        )
        self._picture_in_picture_root = (
            picture_in_picture_directory()
            if picture_in_picture_root is None
            else picture_in_picture_root
        )
        self._synchronized_links_root = (
            synchronized_links_directory()
            if synchronized_links_root is None
            else synchronized_links_root
        )
        self._receipts_root = (
            pause_compaction_finalizations_directory()
            if receipts_root is None
            else receipts_root
        )

    def finalize(
        self,
        *,
        pause_compaction_receipt_id: str,
        picture_in_picture_receipt_id: str,
        synchronized_link_receipt_id: str,
        confirm_finalize: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Finalize one applied M42 timeline with durable batch writes."""
        inputs = _validated_inputs(
            pause_compaction_receipt_id,
            picture_in_picture_receipt_id,
            synchronized_link_receipt_id,
            confirm_finalize,
            timeout_seconds,
        )
        receipt_id = _receipt_id(inputs)
        receipt_path = self._receipts_root / f"{receipt_id}.json"
        if receipt_path.is_file():
            receipt = read_json_object(receipt_path)
            validate_contract("pause-compaction-finalization", receipt)
            if receipt.get("receipt_id") != receipt_id or receipt.get(
                "inputs"
            ) != inputs:
                raise PauseCompactionFinalizationError(
                    "Stored finalization inputs do not match the request."
                )
            if receipt.get("status") == "applied":
                return receipt
        else:
            receipt = self._build_receipt(receipt_id, inputs)
            self._persist(receipt_path, receipt)

        self._require_capabilities()
        timeline_id = receipt["target"]["timeline_id"]
        link_result = self._apply_step(
            receipt_path,
            receipt,
            0,
            lambda: self._gateway.set_clip_link_groups(
                timeline_id,
                receipt["link_groups"],
                True,
                timeout_seconds=float(timeout_seconds),
                idempotency_key=f"{receipt_id}:links",
            ),
        )
        _verify_link_result(timeline_id, receipt["link_groups"], link_result)
        transform_items = [
            {"timeline_item_id": item_id, **receipt["transform"]}
            for item_id in receipt["webcam_item_ids"]
        ]
        transform_result = self._apply_step(
            receipt_path,
            receipt,
            1,
            lambda: self._gateway.set_clip_transforms(
                timeline_id,
                transform_items,
                timeout_seconds=float(timeout_seconds),
                idempotency_key=f"{receipt_id}:transforms",
            ),
        )
        _verify_transform_result(
            timeline_id,
            receipt["webcam_item_ids"],
            receipt["transform"],
            transform_result,
        )
        readback = self._gateway.timeline_items(
            timeline_id,
            timeout_seconds=float(timeout_seconds),
        )
        _verify_identity_readback(receipt, readback)
        receipt["readback"] = readback
        receipt["status"] = "applied"
        self._persist(receipt_path, receipt)
        return receipt

    def _build_receipt(
        self,
        receipt_id: str,
        inputs: dict[str, str],
    ) -> dict[str, Any]:
        compaction = _load_applied_receipt(
            self._pause_compactions_root,
            inputs["pause_compaction_receipt_id"],
            "pause-compaction-result",
            "Pause-compaction",
        )
        layout = _load_applied_receipt(
            self._picture_in_picture_root,
            inputs["picture_in_picture_receipt_id"],
            "picture-in-picture-result",
            "Picture-in-picture",
        )
        link = _load_applied_receipt(
            self._synchronized_links_root,
            inputs["synchronized_link_receipt_id"],
            "synchronized-link-result",
            "Synchronized-link",
        )
        pair_id = _verified_source_binding(compaction, layout, link)
        target, link_groups, webcam_item_ids = _target_items(compaction)
        transform = _verified_transform(layout, compaction)
        return {
            "finalization_version": FINALIZATION_VERSION,
            "receipt_id": receipt_id,
            "status": "in_progress",
            "inputs": inputs,
            "target": {
                "synchronized_pair_receipt_id": pair_id,
                **target,
            },
            "link_groups": link_groups,
            "webcam_item_ids": webcam_item_ids,
            "transform": transform,
            "operations": [
                {"operation": operation, "status": "pending", "result": None}
                for operation in (
                    "set_clip_link_groups",
                    "set_clip_transforms",
                )
            ],
            "readback": None,
        }

    def _require_capabilities(self) -> None:
        capabilities = self._capabilities()
        unsupported = [
            capability
            for capability in REQUIRED_CAPABILITIES
            if capabilities.get(capability) is not True
        ]
        if unsupported:
            raise PauseCompactionFinalizationError(
                "Required Resolve capabilities are not verified: "
                + ", ".join(unsupported)
            )

    def _apply_step(
        self,
        receipt_path: Path,
        receipt: dict[str, Any],
        operation_index: int,
        callback: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        operation = receipt["operations"][operation_index]
        if operation["status"] == "applied":
            result = operation.get("result")
            if not isinstance(result, dict):
                raise PauseCompactionFinalizationError(
                    "Stored applied operation has no object result."
                )
            return result
        result = callback()
        if not isinstance(result, dict):
            raise PauseCompactionFinalizationError(
                f"{operation['operation']} returned an invalid result."
            )
        operation["status"] = "applied"
        operation["result"] = result
        self._persist(receipt_path, receipt)
        return result

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("pause-compaction-finalization", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)


def _validated_inputs(
    pause_compaction_receipt_id: str,
    picture_in_picture_receipt_id: str,
    synchronized_link_receipt_id: str,
    confirm_finalize: bool,
    timeout_seconds: float,
) -> dict[str, str]:
    values = {
        "pause_compaction_receipt_id": pause_compaction_receipt_id,
        "picture_in_picture_receipt_id": picture_in_picture_receipt_id,
        "synchronized_link_receipt_id": synchronized_link_receipt_id,
    }
    for name, value in values.items():
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise PauseCompactionFinalizationError(
                f"{name} must be a lowercase SHA-256 ID."
            )
    if confirm_finalize is not True:
        raise PauseCompactionFinalizationError("confirm_finalize must be true.")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= 300
    ):
        raise PauseCompactionFinalizationError(
            "timeout_seconds must be greater than zero and no more than 300."
        )
    return values


def _load_applied_receipt(
    root: Path,
    receipt_id: str,
    contract_name: Any,
    label: str,
) -> dict[str, Any]:
    path = root / f"{receipt_id}.json"
    if not path.is_file():
        raise PauseCompactionFinalizationError(f"{label} receipt was not found.")
    receipt = read_json_object(path)
    validate_contract(contract_name, receipt)
    if receipt.get("receipt_id") != receipt_id or receipt.get("status") != "applied":
        raise PauseCompactionFinalizationError(
            f"{label} receipt must be canonical and fully applied."
        )
    return receipt


def _verified_source_binding(
    compaction: dict[str, Any],
    layout: dict[str, Any],
    link: dict[str, Any],
) -> str:
    compaction_inputs = compaction.get("inputs")
    layout_inputs = layout.get("inputs")
    link_inputs = link.get("inputs")
    pair_ids = {
        value.get("synchronized_pair_receipt_id")
        for value in (compaction_inputs, layout_inputs, link_inputs)
        if isinstance(value, dict)
    }
    if len(pair_ids) != 1:
        raise PauseCompactionFinalizationError(
            "M42, M39, and M40 receipts do not share one synchronized pair."
        )
    pair_id = next(iter(pair_ids))
    if not isinstance(pair_id, str) or len(pair_id) != 64:
        raise PauseCompactionFinalizationError(
            "Shared synchronized-pair receipt ID is invalid."
        )
    return pair_id


def _target_items(
    compaction: dict[str, Any],
) -> tuple[dict[str, str], list[list[str]], list[str]]:
    timeline = compaction.get("timeline")
    preview = compaction.get("preview")
    operations = compaction.get("operations")
    insert_operation = operations[2] if isinstance(operations, list) else None
    insert_result = (
        insert_operation.get("result")
        if isinstance(insert_operation, dict)
        else None
    )
    placements = preview.get("placements") if isinstance(preview, dict) else None
    items = insert_result.get("items") if isinstance(insert_result, dict) else None
    timeline_id = timeline.get("timeline_id") if isinstance(timeline, dict) else None
    timeline_name = timeline.get("name") if isinstance(timeline, dict) else None
    if (
        not isinstance(timeline_id, str)
        or not isinstance(timeline_name, str)
        or not isinstance(placements, list)
        or not isinstance(items, list)
        or len(placements) != len(items)
    ):
        raise PauseCompactionFinalizationError(
            "Pause-compaction receipt has invalid target items."
        )
    segments: dict[int, dict[str, str]] = {}
    all_ids: set[str] = set()
    for placement_index, (placement, item) in enumerate(
        zip(placements, items, strict=True)
    ):
        if not isinstance(placement, dict) or not isinstance(item, dict):
            raise PauseCompactionFinalizationError(
                "Pause-compaction placement binding is invalid."
            )
        segment_index = placement.get("segment_index")
        role = placement.get("role")
        item_id = item.get("timeline_item_id")
        if (
            item.get("placement_index") != placement_index
            or not isinstance(segment_index, int)
            or isinstance(segment_index, bool)
            or role not in {"screen_video", "screen_audio", "webcam_video"}
            or not isinstance(item_id, str)
            or not item_id
            or item_id in all_ids
        ):
            raise PauseCompactionFinalizationError(
                "Pause-compaction placement identity is invalid."
            )
        segment = segments.setdefault(segment_index, {})
        if role in segment:
            raise PauseCompactionFinalizationError(
                "Pause-compaction segment contains a duplicate role."
            )
        segment[role] = item_id
        all_ids.add(item_id)
    link_groups: list[list[str]] = []
    webcam_item_ids: list[str] = []
    for segment_index in sorted(segments):
        segment = segments[segment_index]
        screen_roles = {"screen_video", "screen_audio"}.intersection(segment)
        if screen_roles and len(screen_roles) != 2:
            raise PauseCompactionFinalizationError(
                "A compacted segment has an incomplete screen video/audio pair."
            )
        if len(screen_roles) == 2:
            link_groups.append(
                [segment["screen_video"], segment["screen_audio"]]
            )
        webcam_id = segment.get("webcam_video")
        if webcam_id is not None:
            webcam_item_ids.append(webcam_id)
    if not link_groups or not webcam_item_ids:
        raise PauseCompactionFinalizationError(
            "Compacted timeline has no bounded links or webcam items to finalize."
        )
    return (
        {"timeline_id": timeline_id, "timeline_name": timeline_name},
        link_groups,
        webcam_item_ids,
    )


def _verified_transform(
    layout: dict[str, Any],
    compaction: dict[str, Any],
) -> dict[str, float]:
    transform = layout.get("transform")
    source = layout.get("source")
    preview = compaction.get("preview")
    placements = preview.get("placements") if isinstance(preview, dict) else None
    webcam_asset_id = (
        source.get("webcam_asset_id") if isinstance(source, dict) else None
    )
    webcam_asset_ids = {
        placement.get("asset_id")
        for placement in placements or []
        if isinstance(placement, dict) and placement.get("role") == "webcam_video"
    }
    if (
        not isinstance(transform, dict)
        or not isinstance(webcam_asset_id, str)
        or webcam_asset_ids != {webcam_asset_id}
    ):
        raise PauseCompactionFinalizationError(
            "Picture-in-picture receipt does not match M42 webcam assets."
        )
    normalized: dict[str, float] = {}
    for name in ("position_x", "position_y", "zoom"):
        value = transform.get(name)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
        ):
            raise PauseCompactionFinalizationError(
                "Picture-in-picture transform is invalid."
            )
        normalized[name] = float(value)
    return normalized


def _verify_link_result(
    timeline_id: str,
    expected_groups: list[list[str]],
    result: dict[str, Any],
) -> None:
    groups = result.get("groups")
    if (
        result.get("timeline_id") != timeline_id
        or result.get("linked") is not True
        or not isinstance(groups, list)
        or len(groups) != len(expected_groups)
    ):
        raise PauseCompactionFinalizationError("Batch link result is invalid.")
    for group_index, (expected_ids, group) in enumerate(
        zip(expected_groups, groups, strict=True)
    ):
        items = group.get("items") if isinstance(group, dict) else None
        if (
            not isinstance(group, dict)
            or group.get("group_index") != group_index
            or not isinstance(items, list)
            or len(items) != 2
        ):
            raise PauseCompactionFinalizationError(
                f"Batch link group {group_index} is invalid."
            )
        discovered = {
            item.get("timeline_item_id"): item
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("timeline_item_id"), str)
        }
        if set(discovered) != set(expected_ids):
            raise PauseCompactionFinalizationError(
                f"Batch link group {group_index} returned unexpected IDs."
            )
        for item_id, item in discovered.items():
            peer_id = next(iter(set(expected_ids) - {item_id}))
            linked_ids = item.get("linked_item_ids")
            if not isinstance(linked_ids, list) or peer_id not in linked_ids:
                raise PauseCompactionFinalizationError(
                    f"Batch link group {group_index} is not mutual."
                )


def _verify_transform_result(
    timeline_id: str,
    expected_ids: list[str],
    transform: dict[str, float],
    result: dict[str, Any],
) -> None:
    items = result.get("items")
    if (
        result.get("timeline_id") != timeline_id
        or not isinstance(items, list)
        or len(items) != len(expected_ids)
    ):
        raise PauseCompactionFinalizationError(
            "Batch transform result is invalid."
        )
    expected_properties = {
        "Pan": transform["position_x"],
        "Tilt": transform["position_y"],
        "ZoomGang": True,
        "ZoomX": transform["zoom"],
        "ZoomY": transform["zoom"],
    }
    for item_index, (expected_id, item) in enumerate(
        zip(expected_ids, items, strict=True)
    ):
        properties = item.get("properties") if isinstance(item, dict) else None
        if (
            not isinstance(item, dict)
            or item.get("item_index") != item_index
            or item.get("timeline_item_id") != expected_id
            or not isinstance(properties, dict)
        ):
            raise PauseCompactionFinalizationError(
                f"Batch transform item {item_index} is invalid."
            )
        for key, expected in expected_properties.items():
            actual = properties.get(key)
            matches = (
                actual is expected
                if isinstance(expected, bool)
                else isinstance(actual, (int, float))
                and not isinstance(actual, bool)
                and math.isclose(
                    float(actual), expected, rel_tol=1e-9, abs_tol=1e-6
                )
            )
            if not matches:
                raise PauseCompactionFinalizationError(
                    f"Batch transform readback does not match {key}."
                )


def _verify_identity_readback(
    receipt: dict[str, Any],
    readback: dict[str, Any],
) -> None:
    items = readback.get("items")
    if (
        readback.get("timeline_id") != receipt["target"]["timeline_id"]
        or not isinstance(items, list)
    ):
        raise PauseCompactionFinalizationError(
            "Finalized timeline identity readback is invalid."
        )
    expected_ids = {
        item_id
        for group in receipt["link_groups"]
        for item_id in group
    } | set(receipt["webcam_item_ids"])
    actual_ids = {
        item.get("timeline_item_id")
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("timeline_item_id"), str)
    }
    if not expected_ids <= actual_ids:
        raise PauseCompactionFinalizationError(
            "Finalized timeline no longer contains every canonical item."
        )


def _receipt_id(inputs: dict[str, str]) -> str:
    payload = json.dumps(
        {"finalization_version": FINALIZATION_VERSION, "inputs": inputs},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
