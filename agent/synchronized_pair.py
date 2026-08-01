"""Provider-neutral M38 synchronized screen/webcam timeline assembly."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import synchronized_pairs_directory
from transports.filesystem import atomic_write_json, read_json_object

SYNC_VERSION = "1.0"
REQUIRED_CAPABILITIES = (
    "clip.insert",
    "clip.read",
    "media.metadata.read",
    "timeline.create",
    "timeline.track.create",
)


class SynchronizedPairError(ValueError):
    """Raised when a synchronized pair cannot be assembled safely."""


class SynchronizedPairGateway(Protocol):
    """Provider-neutral editing operations required by M38."""

    def create_timeline(
        self,
        name: str,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        *,
        timeout_seconds: float,
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

    def insert_clip(
        self,
        timeline_id: str,
        asset_id: str,
        source_start_frame: int,
        source_end_frame: int,
        position_frames: int,
        track_type: str,
        track_index: int,
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


class SynchronizedPairAssembler:
    """Create a new timeline and place one synchronized screen/webcam pair."""

    def __init__(
        self,
        *,
        gateway: SynchronizedPairGateway,
        capabilities: Callable[[], dict[str, Any]],
        receipts_root: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._capabilities = capabilities
        self._receipts_root = (
            synchronized_pairs_directory()
            if receipts_root is None
            else receipts_root
        )

    def assemble(
        self,
        *,
        timeline_name: str,
        screen_asset_id: str,
        webcam_asset_id: str,
        webcam_offset_ms: int,
        confirm_sync: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Assemble V1/A1/V2 with durable step-level replay safety."""
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 300
        ):
            raise SynchronizedPairError(
                "timeout_seconds must be greater than zero and no more than 300."
            )
        inputs = _validated_inputs(
            timeline_name,
            screen_asset_id,
            webcam_asset_id,
            webcam_offset_ms,
            confirm_sync,
        )
        receipt_id = _receipt_id(inputs)
        receipt_path = self._receipts_root / f"{receipt_id}.json"
        if receipt_path.is_file():
            receipt = read_json_object(receipt_path)
            validate_contract("synchronized-pair-result", receipt)
            if receipt["receipt_id"] != receipt_id or receipt["inputs"] != inputs:
                raise SynchronizedPairError(
                    "Stored synchronized-pair inputs do not match the request."
                )
            if receipt["status"] == "applied":
                return receipt
        else:
            receipt = _new_receipt(receipt_id, inputs)
            self._persist(receipt_path, receipt)

        self._require_capabilities()
        create_result = self._apply_step(
            receipt_path,
            receipt,
            0,
            lambda: self._gateway.create_timeline(
                inputs["timeline_name"],
                timeout_seconds=timeout_seconds,
                idempotency_key=_step_key(receipt_id, "create"),
            ),
        )
        timeline = _timeline_result(create_result)
        if timeline["name"] != inputs["timeline_name"]:
            raise SynchronizedPairError(
                "Created timeline name does not match the request."
            )
        receipt["timeline"] = timeline
        self._persist(receipt_path, receipt)

        if not receipt["placements"]:
            metadata = self._gateway.editing_metadata(
                timeline["timeline_id"],
                [inputs["screen_asset_id"], inputs["webcam_asset_id"]],
                timeout_seconds=timeout_seconds,
            )
            frame_rate, assets = _placement_metadata(metadata)
            receipt["timeline_frame_rate"] = frame_rate
            receipt["placements"] = _placements(inputs, frame_rate, assets)
            self._persist(receipt_path, receipt)

        self._apply_step(
            receipt_path,
            receipt,
            1,
            lambda: self._gateway.ensure_timeline_tracks(
                timeline["timeline_id"],
                2,
                1,
                timeout_seconds=timeout_seconds,
                idempotency_key=_step_key(receipt_id, "tracks"),
            ),
        )
        for operation_index, placement in enumerate(receipt["placements"], 2):
            self._apply_step(
                receipt_path,
                receipt,
                operation_index,
                partial(
                    self._gateway.insert_clip,
                    timeline["timeline_id"],
                    placement["asset_id"],
                    placement["source_start_frame"],
                    placement["source_end_frame"],
                    placement["position_frames"],
                    placement["track_type"],
                    placement["track_index"],
                    timeout_seconds=timeout_seconds,
                    idempotency_key=_step_key(
                        receipt_id,
                        placement["role"],
                    ),
                ),
            )

        readback = self._gateway.timeline_items(
            timeline["timeline_id"],
            timeout_seconds=timeout_seconds,
        )
        _verify_readback(receipt, readback)
        receipt["readback"] = readback
        receipt["status"] = "applied"
        self._persist(receipt_path, receipt)
        return receipt

    def _require_capabilities(self) -> None:
        capabilities = self._capabilities()
        unsupported = [
            name
            for name in REQUIRED_CAPABILITIES
            if capabilities.get(name) is not True
        ]
        if unsupported:
            raise SynchronizedPairError(
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
            result = operation["result"]
            if not isinstance(result, dict):
                raise SynchronizedPairError(
                    "Stored applied operation has no object result."
                )
            return result
        result = callback()
        if not isinstance(result, dict):
            raise SynchronizedPairError(
                f"{operation['operation']} returned an invalid result."
            )
        operation["status"] = "applied"
        operation["result"] = result
        self._persist(receipt_path, receipt)
        return result

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("synchronized-pair-result", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)


def _validated_inputs(
    timeline_name: str,
    screen_asset_id: str,
    webcam_asset_id: str,
    webcam_offset_ms: int,
    confirm_sync: bool,
) -> dict[str, Any]:
    normalized_name = timeline_name.strip()
    if not normalized_name or len(normalized_name) > 128:
        raise SynchronizedPairError(
            "timeline_name must contain 1 to 128 characters."
        )
    for field, value in (
        ("screen_asset_id", screen_asset_id),
        ("webcam_asset_id", webcam_asset_id),
    ):
        if not isinstance(value, str) or not value or len(value) > 128:
            raise SynchronizedPairError(
                f"{field} must contain 1 to 128 characters."
            )
    if screen_asset_id == webcam_asset_id:
        raise SynchronizedPairError("Screen and webcam asset IDs must differ.")
    if (
        not isinstance(webcam_offset_ms, int)
        or isinstance(webcam_offset_ms, bool)
        or not -30_000 <= webcam_offset_ms <= 30_000
    ):
        raise SynchronizedPairError(
            "webcam_offset_ms must be an integer from -30000 to 30000."
        )
    if confirm_sync is not True:
        raise SynchronizedPairError("confirm_sync must be true.")
    return {
        "timeline_name": normalized_name,
        "screen_asset_id": screen_asset_id,
        "webcam_asset_id": webcam_asset_id,
        "webcam_offset_ms": webcam_offset_ms,
    }


def _new_receipt(receipt_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    operations = [
        "create_timeline",
        "ensure_timeline_tracks",
        "insert_screen_video",
        "insert_screen_audio",
        "insert_webcam_video",
    ]
    return {
        "sync_version": SYNC_VERSION,
        "receipt_id": receipt_id,
        "status": "in_progress",
        "inputs": inputs,
        "timeline": None,
        "timeline_frame_rate": None,
        "placements": [],
        "operations": [
            {"operation": operation, "status": "pending", "result": None}
            for operation in operations
        ],
        "readback": None,
    }


def _receipt_id(inputs: dict[str, Any]) -> str:
    payload = json.dumps(
        {"sync_version": SYNC_VERSION, "inputs": inputs},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _step_key(receipt_id: str, step: str) -> str:
    return f"{receipt_id}:{step}"


def _timeline_result(result: dict[str, Any]) -> dict[str, str]:
    timeline = result.get("timeline")
    if not isinstance(timeline, dict):
        raise SynchronizedPairError("Timeline creation returned no timeline.")
    timeline_id = timeline.get("timeline_id")
    name = timeline.get("name")
    if not isinstance(timeline_id, str) or not timeline_id:
        raise SynchronizedPairError("Created timeline has no canonical ID.")
    if not isinstance(name, str) or not name:
        raise SynchronizedPairError("Created timeline has no name.")
    return {"timeline_id": timeline_id, "name": name}


def _placement_metadata(
    metadata: dict[str, Any],
) -> tuple[float, dict[str, dict[str, Any]]]:
    timeline = metadata.get("timeline")
    raw_assets = metadata.get("assets")
    if not isinstance(timeline, dict) or not isinstance(raw_assets, list):
        raise SynchronizedPairError("Editing metadata response is invalid.")
    frame_rate = timeline.get("frame_rate")
    if (
        not isinstance(frame_rate, (int, float))
        or isinstance(frame_rate, bool)
        or not math.isfinite(float(frame_rate))
        or float(frame_rate) <= 0
    ):
        raise SynchronizedPairError("Target timeline frame rate is invalid.")
    assets: dict[str, dict[str, Any]] = {}
    for asset in raw_assets:
        if not isinstance(asset, dict):
            raise SynchronizedPairError("Asset editing metadata is invalid.")
        asset_id = asset.get("asset_id")
        duration = asset.get("duration_frames")
        if (
            not isinstance(asset_id, str)
            or not asset_id
            or not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration < 2
        ):
            raise SynchronizedPairError("Asset placement metadata is invalid.")
        assets[asset_id] = asset
    return float(frame_rate), assets


def _placements(
    inputs: dict[str, Any],
    timeline_frame_rate: float,
    assets: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    screen_id = inputs["screen_asset_id"]
    webcam_id = inputs["webcam_asset_id"]
    if screen_id not in assets or webcam_id not in assets:
        raise SynchronizedPairError("Requested asset metadata is incomplete.")
    offset_ms = inputs["webcam_offset_ms"]
    screen_position = _milliseconds_to_frames(
        max(0, -offset_ms), timeline_frame_rate
    )
    webcam_position = _milliseconds_to_frames(
        max(0, offset_ms), timeline_frame_rate
    )
    return [
        {
            "role": "screen_video",
            "asset_id": screen_id,
            "track_type": "video",
            "track_index": 1,
            "source_start_frame": 0,
            "source_end_frame": assets[screen_id]["duration_frames"] - 1,
            "position_frames": screen_position,
        },
        {
            "role": "screen_audio",
            "asset_id": screen_id,
            "track_type": "audio",
            "track_index": 1,
            "source_start_frame": 0,
            "source_end_frame": assets[screen_id]["duration_frames"] - 1,
            "position_frames": screen_position,
        },
        {
            "role": "webcam_video",
            "asset_id": webcam_id,
            "track_type": "video",
            "track_index": 2,
            "source_start_frame": 0,
            "source_end_frame": assets[webcam_id]["duration_frames"] - 1,
            "position_frames": webcam_position,
        },
    ]


def _milliseconds_to_frames(milliseconds: int, frame_rate: float) -> int:
    """Round a non-negative time offset to the nearest target frame."""
    return math.floor((milliseconds * frame_rate / 1000.0) + 0.5)


def _verify_readback(receipt: dict[str, Any], readback: dict[str, Any]) -> None:
    items = readback.get("items")
    if not isinstance(items, list):
        raise SynchronizedPairError("Timeline item readback is invalid.")
    discovered = {
        item.get("timeline_item_id"): item
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("timeline_item_id"), str)
    }
    for operation, placement in zip(
        receipt["operations"][2:],
        receipt["placements"],
        strict=True,
    ):
        result = operation.get("result")
        item = result.get("item") if isinstance(result, dict) else None
        item_id = item.get("timeline_item_id") if isinstance(item, dict) else None
        actual = discovered.get(item_id)
        actual_source_end = (
            actual.get("source_end_frame")
            if isinstance(actual, dict)
            else None
        )
        if (
            not isinstance(actual, dict)
            or actual.get("track_type") != placement["track_type"]
            or actual.get("track_index") != placement["track_index"]
            or actual.get("source_start_frame") != 0
            or not isinstance(actual_source_end, int)
            or isinstance(actual_source_end, bool)
            or not 0 < actual_source_end <= placement["source_end_frame"]
        ):
            raise SynchronizedPairError(
                f"Readback failed for {placement['role']}."
            )
