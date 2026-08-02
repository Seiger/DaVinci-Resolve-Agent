"""Provider-neutral M51 B-roll planning and bounded application."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import broll_applications_directory
from transports.filesystem import atomic_write_json, read_json_object

BROLL_PLAN_VERSION = "1.0"
BROLL_APPLY_VERSION = "1.0"
MAX_FRAME_VALUE = 2_147_483_647
MAX_PLACEMENTS = 100
MIN_BROLL_TRACK = 3
MAX_BROLL_TRACK = 8
REQUIRED_CAPABILITIES = (
    "clip.range_insert",
    "clip.read",
    "media.metadata.read",
    "timeline.duplicate",
    "timeline.track.create",
)


class BrollError(ValueError):
    """Raised when an M51 plan or application is unsafe or inconsistent."""


class BaselineEditInspector(Protocol):
    """Completed M50 status boundary required by B-roll planning."""

    def status(
        self,
        receipt_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...


class BrollGateway(Protocol):
    """Documented provider operations used by the M51 workflow."""

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]: ...

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float,
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


class BrollWorkflow:
    """Preview reviewed B-roll ranges and apply them to a duplicate timeline."""

    def __init__(
        self,
        *,
        gateway: BrollGateway,
        baseline: BaselineEditInspector,
        capabilities: Callable[[], dict[str, Any]],
        receipts_root: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._baseline = baseline
        self._capabilities = capabilities
        self._receipts_root = receipts_root or broll_applications_directory()

    def preview(
        self,
        *,
        baseline_edit_receipt_id: str,
        target_timeline_name: str,
        placements: list[dict[str, Any]],
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return a read-only, capability-aware B-roll review plan."""
        receipt_id = _sha256(
            baseline_edit_receipt_id,
            "baseline_edit_receipt_id",
        )
        target_name = _timeline_name(target_timeline_name)
        raw_placements = _placement_inputs(placements)
        timeout = _timeout(timeout_seconds)
        capabilities = self._capabilities()
        for capability in ("clip.read", "media.metadata.read"):
            if capabilities.get(capability) is not True:
                raise BrollError(
                    f"Required Resolve capability is not verified: {capability}"
                )

        baseline = self._baseline.status(receipt_id, timeout_seconds=timeout)
        source_target = baseline.get("target")
        if (
            baseline.get("status") != "complete"
            or not isinstance(source_target, dict)
            or not isinstance(source_target.get("timeline_id"), str)
            or not isinstance(source_target.get("timeline_name"), str)
        ):
            raise BrollError("A completed M50 baseline receipt is required.")
        source_id = str(source_target["timeline_id"])
        source_name = str(source_target["timeline_name"])
        if target_name == source_name:
            raise BrollError("target_timeline_name must differ from the baseline.")

        live = self._gateway.timeline_items(source_id, timeout_seconds=timeout)
        source = _source_timeline(live, source_id, source_name)
        asset_ids = list(dict.fromkeys(item["asset_id"] for item in raw_placements))
        metadata = self._gateway.editing_metadata(
            source_id,
            asset_ids,
            timeout_seconds=timeout,
        )
        timeline_metadata, assets = _metadata(metadata, source, asset_ids)
        normalized = _normalize_placements(
            raw_placements,
            assets,
            timeline_metadata["frame_rate"],
            source["duration_frames"],
        )
        _reject_collisions(normalized, live, source["timeline_start_frame"])
        unsupported = sorted(
            capability
            for capability in REQUIRED_CAPABILITIES
            if capabilities.get(capability) is not True
        )
        inputs = {
            "baseline_edit_receipt_id": receipt_id,
            "target_timeline_name": target_name,
            "placements": raw_placements,
        }
        plan_payload = {
            "broll_plan_version": BROLL_PLAN_VERSION,
            "status": "preview",
            "apply_supported": not unsupported,
            "inputs": inputs,
            "source": {**source, **timeline_metadata},
            "assets": list(assets.values()),
            "placements": normalized,
            "required_capabilities": list(REQUIRED_CAPABILITIES),
            "unsupported_capabilities": unsupported,
        }
        result = {
            **plan_payload,
            "plan_id": _canonical_sha256(plan_payload),
        }
        validate_contract("broll-preview", result)
        return result

    def apply(
        self,
        *,
        baseline_edit_receipt_id: str,
        target_timeline_name: str,
        placements: list[dict[str, Any]],
        expected_plan_id: str,
        confirm_apply: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Apply one exact reviewed plan to a duplicated baseline timeline."""
        if confirm_apply is not True:
            raise BrollError("confirm_apply must be true.")
        expected_id = _sha256(expected_plan_id, "expected_plan_id")
        timeout = _timeout(timeout_seconds)
        preview = self.preview(
            baseline_edit_receipt_id=baseline_edit_receipt_id,
            target_timeline_name=target_timeline_name,
            placements=placements,
            timeout_seconds=timeout,
        )
        if preview["plan_id"] != expected_id:
            raise BrollError("expected_plan_id does not match the current preview.")
        if preview["apply_supported"] is not True:
            raise BrollError(
                "Required Resolve capabilities are not verified: "
                + ", ".join(preview["unsupported_capabilities"])
            )

        receipt_id = _canonical_sha256(
            {
                "broll_apply_version": BROLL_APPLY_VERSION,
                "plan_id": expected_id,
            }
        )
        path = self._receipts_root / f"{receipt_id}.json"
        if path.is_file():
            receipt = read_json_object(path)
            validate_contract("broll-result", receipt)
            if (
                receipt.get("receipt_id") != receipt_id
                or receipt.get("plan") != preview
            ):
                raise BrollError("Stored B-roll receipt does not match the plan.")
            if receipt.get("status") == "applied":
                return receipt
        else:
            receipt = _new_receipt(receipt_id, preview)
            self._persist(path, receipt)

        source = preview["source"]
        duplicate = self._step(
            path,
            receipt,
            0,
            lambda: self._gateway.duplicate_timeline(
                source["timeline_id"],
                preview["inputs"]["target_timeline_name"],
                timeout_seconds=timeout,
                idempotency_key=_step_key(receipt_id, "duplicate"),
            ),
        )
        target = _duplicate_target(
            duplicate,
            source["timeline_id"],
            preview["inputs"]["target_timeline_name"],
        )
        receipt["target"] = target
        self._persist(path, receipt)

        video_tracks = max(
            source["video_track_count"],
            max(item["track_index"] for item in preview["placements"]),
        )
        self._step(
            path,
            receipt,
            1,
            lambda: self._gateway.ensure_timeline_tracks(
                target["timeline_id"],
                video_tracks,
                source["audio_track_count"],
                timeout_seconds=timeout,
                idempotency_key=_step_key(receipt_id, "tracks"),
            ),
        )
        provider_placements = [
            _provider_placement(item) for item in preview["placements"]
        ]
        inserted = self._step(
            path,
            receipt,
            2,
            lambda: self._gateway.insert_clips(
                target["timeline_id"],
                provider_placements,
                timeout_seconds=timeout,
                idempotency_key=_step_key(receipt_id, "insert"),
            ),
        )
        inserted_items = _verify_insert_result(
            target["timeline_id"],
            provider_placements,
            inserted,
        )
        readback = self._gateway.timeline_items(
            target["timeline_id"], timeout_seconds=timeout
        )
        _verify_readback(target, inserted_items, readback)
        receipt["inserted_items"] = inserted_items
        receipt["readback"] = readback
        receipt["status"] = "applied"
        self._persist(path, receipt)
        return receipt

    def _step(
        self,
        path: Path,
        receipt: dict[str, Any],
        index: int,
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        step = receipt["operations"][index]
        if step["status"] == "applied":
            result = step.get("result")
            if not isinstance(result, dict):
                raise BrollError("Applied B-roll operation has no result.")
            return result
        result = operation()
        if not isinstance(result, dict):
            raise BrollError("B-roll provider operation returned no object.")
        step["status"] = "applied"
        step["result"] = result
        self._persist(path, receipt)
        return result

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("broll-result", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)


def _placement_inputs(placements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(placements, list) or not 1 <= len(placements) <= MAX_PLACEMENTS:
        raise BrollError("placements must contain between 1 and 100 items.")
    normalized: list[dict[str, Any]] = []
    required = {
        "asset_id",
        "source_start_frame",
        "source_end_frame",
        "position_frames",
        "track_index",
        "purpose",
    }
    for index, placement in enumerate(placements):
        if not isinstance(placement, dict) or set(placement) != required:
            raise BrollError(f"B-roll placement {index} fields are invalid.")
        asset_id = placement["asset_id"]
        purpose = placement["purpose"]
        source_start = _frame(placement["source_start_frame"], "source_start_frame")
        source_end = _frame(placement["source_end_frame"], "source_end_frame")
        position = _frame(placement["position_frames"], "position_frames")
        track_index = placement["track_index"]
        if not isinstance(asset_id, str) or not 1 <= len(asset_id) <= 128:
            raise BrollError(f"B-roll placement {index} asset_id is invalid.")
        if not isinstance(purpose, str) or not 1 <= len(purpose.strip()) <= 240:
            raise BrollError(f"B-roll placement {index} purpose is invalid.")
        if not source_start < source_end:
            raise BrollError("B-roll source ranges must contain at least two frames.")
        if (
            not isinstance(track_index, int)
            or isinstance(track_index, bool)
            or not MIN_BROLL_TRACK <= track_index <= MAX_BROLL_TRACK
        ):
            raise BrollError("B-roll track_index must be between 3 and 8.")
        normalized.append(
            {
                "asset_id": asset_id,
                "source_start_frame": source_start,
                "source_end_frame": source_end,
                "position_frames": position,
                "track_index": track_index,
                "purpose": purpose.strip(),
            }
        )
    return normalized


def _source_timeline(
    live: dict[str, Any], expected_id: str, expected_name: str
) -> dict[str, Any]:
    items = live.get("items")
    if (
        live.get("timeline_id") != expected_id
        or live.get("name") != expected_name
        or not isinstance(items, list)
        or not items
    ):
        raise BrollError("Live baseline timeline identity or items are invalid.")
    starts: list[int] = []
    ends: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start = item.get("timeline_start_frame")
        end = item.get("timeline_end_frame")
        if (
            isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
            and end > start
        ):
            starts.append(start)
            ends.append(end)
    if not starts:
        raise BrollError("Live baseline has no bounded timeline items.")
    timeline_start = min(starts)
    timeline_end = max(ends)
    return {
        "timeline_id": expected_id,
        "timeline_name": expected_name,
        "timeline_start_frame": timeline_start,
        "timeline_end_frame": timeline_end,
        "duration_frames": timeline_end - timeline_start,
    }


def _metadata(
    metadata: dict[str, Any],
    source: dict[str, Any],
    expected_assets: list[str],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    timeline = metadata.get("timeline")
    raw_assets = metadata.get("assets")
    if not isinstance(timeline, dict) or not isinstance(raw_assets, list):
        raise BrollError("B-roll editing metadata is invalid.")
    frame_rate = _positive_number(timeline.get("frame_rate"), "timeline frame rate")
    video_tracks = _positive_count(timeline.get("video_track_count"), "video tracks")
    audio_tracks = _positive_count(timeline.get("audio_track_count"), "audio tracks")
    if timeline.get("timeline_id") != source["timeline_id"]:
        raise BrollError("Editing metadata targets a different timeline.")
    assets: dict[str, dict[str, Any]] = {}
    for asset in raw_assets:
        if not isinstance(asset, dict):
            raise BrollError("B-roll asset metadata is invalid.")
        asset_id = asset.get("asset_id")
        name = asset.get("name")
        duration = asset.get("duration_frames")
        asset_rate = asset.get("frame_rate")
        if (
            not isinstance(asset_id, str)
            or not isinstance(name, str)
            or not isinstance(duration, int)
            or isinstance(duration, bool)
            or not 2 <= duration <= MAX_FRAME_VALUE
        ):
            raise BrollError("B-roll asset metadata is invalid.")
        assets[asset_id] = {
            "asset_id": asset_id,
            "name": name,
            "duration_frames": duration,
            "frame_rate": _positive_number(asset_rate, "asset frame rate"),
        }
    if set(assets) != set(expected_assets):
        raise BrollError("B-roll metadata did not return every requested asset.")
    return (
        {
            "frame_rate": frame_rate,
            "video_track_count": video_tracks,
            "audio_track_count": audio_tracks,
        },
        assets,
    )


def _normalize_placements(
    placements: list[dict[str, Any]],
    assets: dict[str, dict[str, Any]],
    timeline_rate: float,
    timeline_duration: int,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, placement in enumerate(placements):
        asset = assets[placement["asset_id"]]
        if placement["source_end_frame"] >= asset["duration_frames"]:
            raise BrollError(f"B-roll placement {index} exceeds source duration.")
        source_duration = (
            placement["source_end_frame"] - placement["source_start_frame"] + 1
        )
        timeline_frames = max(
            1,
            math.floor(source_duration * timeline_rate / asset["frame_rate"] + 0.5),
        )
        timeline_end = placement["position_frames"] + timeline_frames
        if timeline_end > timeline_duration:
            raise BrollError(f"B-roll placement {index} exceeds baseline duration.")
        normalized.append(
            {
                "placement_index": index,
                **placement,
                "timeline_duration_frames": timeline_frames,
                "timeline_end_position_frames": timeline_end,
            }
        )
    for left_index, left in enumerate(normalized):
        for right in normalized[left_index + 1 :]:
            if left["track_index"] == right["track_index"] and _overlap(
                left["position_frames"],
                left["timeline_end_position_frames"],
                right["position_frames"],
                right["timeline_end_position_frames"],
            ):
                raise BrollError("B-roll placements overlap on the same track.")
    return normalized


def _reject_collisions(
    placements: list[dict[str, Any]],
    live: dict[str, Any],
    timeline_start: int,
) -> None:
    for item in live.get("items", []):
        if not isinstance(item, dict) or item.get("track_type") != "video":
            continue
        track_index = item.get("track_index")
        start = item.get("timeline_start_frame")
        end = item.get("timeline_end_frame")
        if (
            not isinstance(track_index, int)
            or isinstance(track_index, bool)
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
        ):
            continue
        relative_start = start - timeline_start
        relative_end = end - timeline_start
        for placement in placements:
            if placement["track_index"] == track_index and _overlap(
                placement["position_frames"],
                placement["timeline_end_position_frames"],
                relative_start,
                relative_end,
            ):
                raise BrollError("A B-roll placement collides with an existing item.")


def _new_receipt(receipt_id: str, preview: dict[str, Any]) -> dict[str, Any]:
    return {
        "broll_apply_version": BROLL_APPLY_VERSION,
        "receipt_id": receipt_id,
        "status": "in_progress",
        "plan": preview,
        "target": None,
        "operations": [
            {"operation": name, "status": "pending", "result": None}
            for name in (
                "duplicate_timeline",
                "ensure_timeline_tracks",
                "insert_clips",
            )
        ],
        "inserted_items": [],
        "readback": None,
    }


def _duplicate_target(
    result: dict[str, Any], source_id: str, expected_name: str
) -> dict[str, str]:
    source = result.get("source_timeline")
    timeline = result.get("timeline")
    if (
        not isinstance(source, dict)
        or source.get("timeline_id") != source_id
        or not isinstance(timeline, dict)
        or not isinstance(timeline.get("timeline_id"), str)
        or not timeline.get("timeline_id")
        or timeline.get("name") != expected_name
    ):
        raise BrollError("Duplicated timeline readback is invalid.")
    return {
        "timeline_id": str(timeline["timeline_id"]),
        "timeline_name": expected_name,
    }


def _provider_placement(placement: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": placement["asset_id"],
        "source_start_frame": placement["source_start_frame"],
        "source_end_frame": placement["source_end_frame"],
        "position_frames": placement["position_frames"],
        "track_type": "video",
        "track_index": placement["track_index"],
    }


def _verify_insert_result(
    timeline_id: str,
    placements: list[dict[str, Any]],
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    items = result.get("items")
    if result.get("timeline_id") != timeline_id or not isinstance(items, list):
        raise BrollError("B-roll insertion result is invalid.")
    if len(items) != len(placements):
        raise BrollError("B-roll insertion did not return every placement.")
    origins: set[int] = set()
    ids: set[str] = set()
    verified: list[dict[str, Any]] = []
    for index, (placement, item) in enumerate(zip(placements, items, strict=True)):
        if not isinstance(item, dict):
            raise BrollError("A B-roll insertion item is invalid.")
        item_id = item.get("timeline_item_id")
        start = item.get("timeline_start_frame")
        end = item.get("timeline_end_frame")
        if (
            item.get("placement_index") != index
            or item.get("asset_id") != placement["asset_id"]
            or item.get("track_type") != "video"
            or item.get("track_index") != placement["track_index"]
            or item.get("source_start_frame") != placement["source_start_frame"]
            or not isinstance(item.get("source_end_frame"), int)
            or not placement["source_start_frame"]
            < item["source_end_frame"]
            <= placement["source_end_frame"]
            or not isinstance(item_id, str)
            or not item_id
            or item_id in ids
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or end <= start
        ):
            raise BrollError(f"B-roll readback failed at placement {index}.")
        ids.add(item_id)
        origins.add(start - placement["position_frames"])
        verified.append(item)
    if len(origins) != 1:
        raise BrollError("B-roll insertions do not share one timeline origin.")
    return verified


def _verify_readback(
    target: dict[str, str],
    inserted: list[dict[str, Any]],
    readback: dict[str, Any],
) -> None:
    items = readback.get("items")
    if (
        readback.get("timeline_id") != target["timeline_id"]
        or readback.get("name") != target["timeline_name"]
        or not isinstance(items, list)
    ):
        raise BrollError("B-roll target timeline readback is invalid.")
    discovered = {
        item.get("timeline_item_id"): item
        for item in items
        if isinstance(item, dict) and isinstance(item.get("timeline_item_id"), str)
    }
    fields = (
        "track_type",
        "track_index",
        "timeline_start_frame",
        "timeline_end_frame",
        "source_start_frame",
        "source_end_frame",
    )
    for item in inserted:
        actual = discovered.get(item["timeline_item_id"])
        if not isinstance(actual, dict) or any(
            actual.get(field) != item.get(field) for field in fields
        ):
            raise BrollError("An inserted B-roll item did not persist exactly.")


def _timeline_name(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 128:
        raise BrollError("target_timeline_name must contain 1 to 128 characters.")
    return value.strip()


def _frame(value: Any, name: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= MAX_FRAME_VALUE
    ):
        raise BrollError(f"{name} must be a bounded non-negative integer.")
    return value


def _positive_number(value: Any, name: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise BrollError(f"{name} is invalid.")
    return float(value)


def _positive_count(value: Any, name: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= 128
    ):
        raise BrollError(f"{name} are invalid.")
    return value


def _timeout(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 < float(value) <= 300
    ):
        raise BrollError(
            "timeout_seconds must be greater than zero and no more than 300."
        )
    return float(value)


def _sha256(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BrollError(f"{name} must be a lowercase SHA-256 ID.")
    return value


def _overlap(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    return left_start < right_end and right_start < left_end


def _canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _step_key(receipt_id: str, step: str) -> str:
    return hashlib.sha256(f"{receipt_id}:{step}".encode()).hexdigest()
