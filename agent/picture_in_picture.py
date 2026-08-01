"""Provider-neutral M39 synchronized webcam picture-in-picture layout."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

from agent.contracts import validate_contract
from agent.paths import (
    picture_in_picture_directory,
    synchronized_pairs_directory,
)
from transports.filesystem import atomic_write_json, read_json_object

LAYOUT_VERSION = "1.0"
REQUIRED_CAPABILITIES = ("clip.transform", "media.metadata.read")


class PictureInPictureError(ValueError):
    """Raised when a synchronized webcam layout cannot be applied safely."""


class PictureInPictureGateway(Protocol):
    """Provider-neutral operations required by the M39 layout workflow."""

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]: ...

    def set_clip_transform(
        self,
        timeline_id: str,
        timeline_item_id: str,
        *,
        position_x: float | None = None,
        position_y: float | None = None,
        zoom: float | None = None,
        rotation_degrees: float | None = None,
        opacity_percent: float | None = None,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...


class PictureInPictureComposer:
    """Lay out the webcam item produced by one applied M38 receipt."""

    def __init__(
        self,
        *,
        gateway: PictureInPictureGateway,
        capabilities: Callable[[], dict[str, Any]],
        synchronized_pairs_root: Path | None = None,
        receipts_root: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._capabilities = capabilities
        self._synchronized_pairs_root = (
            synchronized_pairs_directory()
            if synchronized_pairs_root is None
            else synchronized_pairs_root
        )
        self._receipts_root = (
            picture_in_picture_directory()
            if receipts_root is None
            else receipts_root
        )

    def compose(
        self,
        *,
        synchronized_pair_receipt_id: str,
        size_percent: float,
        center_x_percent: float,
        center_y_percent: float,
        confirm_layout: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Apply a normalized layout with durable idempotent readback."""
        inputs = _validated_inputs(
            synchronized_pair_receipt_id,
            size_percent,
            center_x_percent,
            center_y_percent,
            confirm_layout,
            timeout_seconds,
        )
        source = self._load_synchronized_pair(
            inputs["synchronized_pair_receipt_id"]
        )
        self._require_capabilities()
        source_details = _source_details(source)
        receipt_id = _receipt_id(inputs)
        receipt_path = self._receipts_root / f"{receipt_id}.json"
        if receipt_path.is_file():
            receipt = read_json_object(receipt_path)
            validate_contract("picture-in-picture-result", receipt)
            if receipt["receipt_id"] != receipt_id or receipt["inputs"] != inputs:
                raise PictureInPictureError(
                    "Stored picture-in-picture inputs do not match the request."
                )
            if receipt["status"] == "applied":
                return receipt
        else:
            receipt = _new_receipt(receipt_id, inputs, source_details)
            self._persist(receipt_path, receipt)

        metadata = self._gateway.editing_metadata(
            source_details["timeline_id"],
            [source_details["webcam_asset_id"]],
            timeout_seconds=float(timeout_seconds),
        )
        transform = _normalized_transform(metadata, inputs)
        receipt["timeline_resolution"] = transform.pop("timeline_resolution")
        receipt["transform"] = transform
        self._persist(receipt_path, receipt)

        result = self._gateway.set_clip_transform(
            source_details["timeline_id"],
            source_details["webcam_timeline_item_id"],
            position_x=transform["position_x"],
            position_y=transform["position_y"],
            zoom=transform["zoom"],
            timeout_seconds=float(timeout_seconds),
            idempotency_key=f"{receipt_id}:webcam-layout",
        )
        _verify_transform_result(source_details, transform, result)
        receipt["operation"] = {
            "operation": "set_webcam_transform",
            "status": "applied",
            "result": result,
        }
        receipt["status"] = "applied"
        self._persist(receipt_path, receipt)
        return receipt

    def _load_synchronized_pair(self, receipt_id: str) -> dict[str, Any]:
        path = self._synchronized_pairs_root / f"{receipt_id}.json"
        if not path.is_file():
            raise PictureInPictureError(
                "Synchronized-pair receipt was not found."
            )
        receipt = read_json_object(path)
        validate_contract("synchronized-pair-result", receipt)
        if receipt.get("receipt_id") != receipt_id:
            raise PictureInPictureError(
                "Synchronized-pair receipt identity does not match its file."
            )
        if receipt.get("status") != "applied":
            raise PictureInPictureError(
                "Synchronized-pair receipt must be fully applied."
            )
        return receipt

    def _require_capabilities(self) -> None:
        capabilities = self._capabilities()
        unsupported = [
            name
            for name in REQUIRED_CAPABILITIES
            if capabilities.get(name) is not True
        ]
        if unsupported:
            raise PictureInPictureError(
                "Required Resolve capabilities are not verified: "
                + ", ".join(unsupported)
            )

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("picture-in-picture-result", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)


def _validated_inputs(
    receipt_id: str,
    size_percent: float,
    center_x_percent: float,
    center_y_percent: float,
    confirm_layout: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    if (
        not isinstance(receipt_id, str)
        or len(receipt_id) != 64
        or any(character not in "0123456789abcdef" for character in receipt_id)
    ):
        raise PictureInPictureError(
            "synchronized_pair_receipt_id must be a lowercase SHA-256 ID."
        )
    normalized: dict[str, float] = {}
    for name, value, minimum, maximum in (
        ("size_percent", size_percent, 10.0, 50.0),
        ("center_x_percent", center_x_percent, 0.0, 100.0),
        ("center_y_percent", center_y_percent, 0.0, 100.0),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not minimum <= float(value) <= maximum
        ):
            raise PictureInPictureError(
                f"{name} must be a finite number from {minimum} to {maximum}."
            )
        normalized[name] = float(value)
    if confirm_layout is not True:
        raise PictureInPictureError("confirm_layout must be true.")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= 300
    ):
        raise PictureInPictureError(
            "timeout_seconds must be greater than zero and no more than 300."
        )
    return {
        "synchronized_pair_receipt_id": receipt_id,
        **normalized,
    }


def _source_details(receipt: dict[str, Any]) -> dict[str, str]:
    timeline = receipt.get("timeline")
    inputs = receipt.get("inputs")
    operations = receipt.get("operations")
    webcam_operation = operations[4] if isinstance(operations, list) else None
    result = (
        webcam_operation.get("result")
        if isinstance(webcam_operation, dict)
        else None
    )
    item = result.get("item") if isinstance(result, dict) else None
    timeline_id = timeline.get("timeline_id") if isinstance(timeline, dict) else None
    webcam_asset_id = (
        inputs.get("webcam_asset_id") if isinstance(inputs, dict) else None
    )
    item_id = item.get("timeline_item_id") if isinstance(item, dict) else None
    if not all(
        isinstance(value, str) and value
        for value in (timeline_id, webcam_asset_id, item_id)
    ):
        raise PictureInPictureError(
            "Synchronized-pair receipt has no canonical webcam item."
        )
    return {
        "timeline_id": cast(str, timeline_id),
        "webcam_asset_id": cast(str, webcam_asset_id),
        "webcam_timeline_item_id": cast(str, item_id),
    }


def _normalized_transform(
    metadata: dict[str, Any], inputs: dict[str, Any]
) -> dict[str, Any]:
    timeline = metadata.get("timeline")
    width = timeline.get("resolution_width") if isinstance(timeline, dict) else None
    height = (
        timeline.get("resolution_height") if isinstance(timeline, dict) else None
    )
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or width < 1
        or not isinstance(height, int)
        or isinstance(height, bool)
        or height < 1
    ):
        raise PictureInPictureError(
            "Target timeline resolution metadata is invalid."
        )
    return {
        "position_x": (inputs["center_x_percent"] / 100.0 - 0.5) * width,
        "position_y": (0.5 - inputs["center_y_percent"] / 100.0) * height,
        "zoom": inputs["size_percent"] / 100.0,
        "timeline_resolution": {"width": width, "height": height},
    }


def _verify_transform_result(
    source: dict[str, str],
    transform: dict[str, float],
    result: dict[str, Any],
) -> None:
    properties = result.get("properties")
    expected = {
        "Pan": transform["position_x"],
        "Tilt": transform["position_y"],
        "ZoomX": transform["zoom"],
        "ZoomY": transform["zoom"],
        "ZoomGang": True,
    }
    if (
        result.get("timeline_id") != source["timeline_id"]
        or result.get("timeline_item_id")
        != source["webcam_timeline_item_id"]
        or not isinstance(properties, dict)
    ):
        raise PictureInPictureError(
            "Webcam transform returned invalid item identity or readback."
        )
    for key, expected_value in expected.items():
        actual = properties.get(key)
        if isinstance(expected_value, bool):
            matches = actual is expected_value
        else:
            matches = (
                isinstance(actual, (int, float))
                and not isinstance(actual, bool)
                and math.isclose(
                    float(actual), expected_value, rel_tol=1e-9, abs_tol=1e-6
                )
            )
        if not matches:
            raise PictureInPictureError(
                f"Webcam transform readback does not match {key}."
            )


def _receipt_id(inputs: dict[str, Any]) -> str:
    payload = json.dumps(
        {"layout_version": LAYOUT_VERSION, "inputs": inputs},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _new_receipt(
    receipt_id: str,
    inputs: dict[str, Any],
    source: dict[str, str],
) -> dict[str, Any]:
    return {
        "layout_version": LAYOUT_VERSION,
        "receipt_id": receipt_id,
        "status": "in_progress",
        "inputs": inputs,
        "source": source,
        "timeline_resolution": None,
        "transform": None,
        "operation": {
            "operation": "set_webcam_transform",
            "status": "pending",
            "result": None,
        },
    }
