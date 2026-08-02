"""Provider-neutral M53 color discovery, preview and application workflow."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from agent.color_presets import ColorPresetCatalogue
from agent.contracts import validate_contract
from agent.paths import (
    animation_template_runs_directory,
    color_treatment_runs_directory,
)
from transports.filesystem import atomic_write_json, read_json_object

COLOR_PLAN_VERSION = "1.0"
COLOR_APPLY_VERSION = "1.0"
REQUIRED_CAPABILITIES = ("clip.read", "timeline.duplicate")


class ColorWorkflowError(ValueError):
    """Raised when an M53 preview is unsafe or inconsistent."""


class ColorGateway(Protocol):
    """Documented provider operations used by M53 discovery."""

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]: ...

    def color_environment(
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

    def apply_color_preset(
        self,
        timeline_id: str,
        timeline_item_ids: list[str],
        preset_id: str,
        *,
        confirm_apply: bool,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...


class ColorTreatmentWorkflow:
    """List CDL presets and build one read-only M52-bound color plan."""

    def __init__(
        self,
        *,
        gateway: ColorGateway,
        capabilities: Callable[[], dict[str, Any]],
        catalogue: ColorPresetCatalogue | None = None,
        animation_receipts_root: Path | None = None,
        receipts_root: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._capabilities = capabilities
        self._catalogue = catalogue or ColorPresetCatalogue()
        self._animation_receipts_root = (
            animation_receipts_root or animation_template_runs_directory()
        )
        self._receipts_root = receipts_root or color_treatment_runs_directory()

    def list_presets(self) -> dict[str, Any]:
        """Return immutable packaged CDL presets."""
        return self._catalogue.list_presets()

    def get_preset(self, preset_id: str) -> dict[str, Any]:
        """Return one immutable packaged CDL preset."""
        return self._catalogue.get_preset(preset_id)

    def preview(
        self,
        *,
        animation_receipt_id: str,
        target_timeline_name: str,
        preset_id: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Build one deterministic, read-only M53 color plan."""
        receipt_id = _sha256(animation_receipt_id, "animation_receipt_id")
        target_name = _timeline_name(target_timeline_name)
        timeout = _timeout(timeout_seconds)
        preset = self._catalogue.get_preset(preset_id)
        receipt = self._load_animation_receipt(receipt_id)
        target = receipt.get("target")
        if (
            receipt.get("status") != "applied"
            or not isinstance(target, dict)
            or not isinstance(target.get("timeline_id"), str)
            or not isinstance(target.get("timeline_name"), str)
        ):
            raise ColorWorkflowError("An applied M52 receipt is required.")
        source_id = target["timeline_id"]
        source_name = target["timeline_name"]
        if target_name == source_name:
            raise ColorWorkflowError(
                "target_timeline_name must differ from the M52 timeline."
            )
        live = self._gateway.timeline_items(source_id, timeout_seconds=timeout)
        _verify_live_receipt(receipt, live, source_id, source_name)
        environment = self._gateway.color_environment(
            source_id, timeout_seconds=timeout
        )
        targets = _verify_environment(environment, live, source_id)
        capabilities = self._capabilities()
        unsupported = sorted(
            capability
            for capability in REQUIRED_CAPABILITIES
            if capabilities.get(capability) is not True
        )
        apply_supported = (
            not unsupported
            and environment.get("ready") is True
            and environment.get("apply_candidate") is True
        )
        inputs = {
            "animation_receipt_id": receipt_id,
            "target_timeline_name": target_name,
            "preset_id": preset["preset_id"],
        }
        payload = {
            "color_plan_version": COLOR_PLAN_VERSION,
            "status": "preview",
            "apply_supported": apply_supported,
            "inputs": inputs,
            "source": {
                "timeline_id": source_id,
                "timeline_name": source_name,
                "snapshot_sha256": _items_sha256(live["items"]),
            },
            "preset": preset,
            "targets": targets,
            "environment": environment,
            "required_capabilities": list(REQUIRED_CAPABILITIES),
            "unsupported_capabilities": unsupported,
        }
        result = {**payload, "plan_id": _canonical_sha256(payload)}
        validate_contract("color-treatment-preview", result)
        return result

    def apply(
        self,
        *,
        animation_receipt_id: str,
        target_timeline_name: str,
        preset_id: str,
        expected_plan_id: str,
        confirm_apply: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Apply one exact reviewed M53 plan to a duplicate timeline."""
        if confirm_apply is not True:
            raise ColorWorkflowError("confirm_apply must be true.")
        expected_id = _sha256(expected_plan_id, "expected_plan_id")
        timeout = _timeout(timeout_seconds)
        preview = self.preview(
            animation_receipt_id=animation_receipt_id,
            target_timeline_name=target_timeline_name,
            preset_id=preset_id,
            timeout_seconds=timeout,
        )
        if preview["plan_id"] != expected_id:
            raise ColorWorkflowError(
                "expected_plan_id does not match the current preview."
            )
        if preview["apply_supported"] is not True:
            raise ColorWorkflowError("The reviewed color plan is not applicable.")
        receipt_id = _canonical_sha256(
            {"color_apply_version": COLOR_APPLY_VERSION, "plan_id": expected_id}
        )
        path = self._receipts_root / f"{receipt_id}.json"
        if path.is_file():
            receipt = read_json_object(path)
            validate_contract("color-treatment-result", receipt)
            if (
                receipt.get("receipt_id") != receipt_id
                or receipt.get("plan") != preview
            ):
                raise ColorWorkflowError(
                    "Stored color-treatment receipt does not match the plan."
                )
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

        target_live = self._gateway.timeline_items(
            target["timeline_id"], timeout_seconds=timeout
        )
        target_ids = _map_duplicate_target_ids(preview, target, target_live)
        applied = self._step(
            path,
            receipt,
            1,
            lambda: self._gateway.apply_color_preset(
                target["timeline_id"],
                target_ids,
                preview["inputs"]["preset_id"],
                confirm_apply=True,
                timeout_seconds=timeout,
                idempotency_key=_step_key(receipt_id, "color"),
            ),
        )
        _verify_apply_result(target, preview, target_ids, applied)
        readback = self._gateway.color_environment(
            target["timeline_id"], timeout_seconds=timeout
        )
        _verify_applied_readback(target, target_ids, readback)
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
                raise ColorWorkflowError("Applied color operation has no result.")
            return result
        result = operation()
        if not isinstance(result, dict):
            raise ColorWorkflowError("Color provider operation returned no object.")
        step["status"] = "applied"
        step["result"] = result
        self._persist(path, receipt)
        return result

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("color-treatment-result", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)

    def _load_animation_receipt(self, receipt_id: str) -> dict[str, Any]:
        path = self._animation_receipts_root / f"{receipt_id}.json"
        if not path.is_file():
            raise ColorWorkflowError("The M52 animation receipt was not found.")
        receipt = read_json_object(path)
        validate_contract("animation-template-result", receipt)
        if receipt.get("receipt_id") != receipt_id:
            raise ColorWorkflowError("The M52 animation receipt ID is invalid.")
        return receipt


def _verify_live_receipt(
    receipt: dict[str, Any],
    live: dict[str, Any],
    timeline_id: str,
    timeline_name: str,
) -> None:
    readback = receipt.get("readback")
    if (
        not isinstance(readback, dict)
        or live.get("timeline_id") != timeline_id
        or live.get("name") != timeline_name
        or readback.get("timeline_id") != timeline_id
        or readback.get("name") != timeline_name
        or not isinstance(live.get("items"), list)
        or not isinstance(readback.get("items"), list)
        or _items_sha256(live["items"]) != _items_sha256(readback["items"])
    ):
        raise ColorWorkflowError("The live M52 timeline changed after acceptance.")


def _verify_environment(
    environment: dict[str, Any],
    live: dict[str, Any],
    timeline_id: str,
) -> list[dict[str, Any]]:
    timeline = environment.get("timeline")
    color_items = environment.get("items")
    if (
        not isinstance(timeline, dict)
        or timeline.get("timeline_id") != timeline_id
        or not isinstance(color_items, list)
        or not color_items
    ):
        raise ColorWorkflowError("The Resolve color environment is invalid.")
    live_ids = {
        item.get("timeline_item_id")
        for item in live["items"]
        if isinstance(item, dict)
        and item.get("track_type") == "video"
        and item.get("source_type") == "media"
    }
    targets: list[dict[str, Any]] = []
    for item in color_items:
        if (
            not isinstance(item, dict)
            or item.get("timeline_item_id") not in live_ids
            or not isinstance(item.get("node_count"), int)
            or item["node_count"] < 1
            or not isinstance(item.get("nodes"), list)
        ):
            raise ColorWorkflowError("A Resolve color item is invalid.")
        targets.append(
            {
                key: item[key]
                for key in (
                    "timeline_item_id",
                    "name",
                    "track_index",
                    "timeline_start_frame",
                    "timeline_end_frame",
                    "current_version",
                    "node_count",
                    "nodes",
                )
            }
        )
    targets.sort(key=lambda item: str(item["timeline_item_id"]))
    if {item["timeline_item_id"] for item in targets} != live_ids:
        raise ColorWorkflowError(
            "Color discovery did not cover every media video item."
        )
    return targets


def _duplicate_target(
    result: dict[str, Any], source_id: str, expected_name: str
) -> dict[str, str]:
    timeline = result.get("timeline")
    source = result.get("source_timeline")
    if (
        not isinstance(timeline, dict)
        or not isinstance(source, dict)
        or source.get("timeline_id") != source_id
        or timeline.get("name") != expected_name
        or not isinstance(timeline.get("timeline_id"), str)
        or timeline.get("timeline_id") == source_id
    ):
        raise ColorWorkflowError("Duplicate color timeline result is invalid.")
    return {
        "timeline_id": timeline["timeline_id"],
        "timeline_name": timeline["name"],
    }


def _verify_apply_result(
    target: dict[str, str],
    preview: dict[str, Any],
    target_ids: list[str],
    result: dict[str, Any],
) -> None:
    items = result.get("items")
    expected_ids = set(target_ids)
    if (
        result.get("timeline_id") != target["timeline_id"]
        or result.get("preset_id") != preview["inputs"]["preset_id"]
        or result.get("version_name") != "DaVinci Agent Tutorial Clean v1"
        or not isinstance(items, list)
        or {item.get("timeline_item_id") for item in items if isinstance(item, dict)}
        != expected_ids
        or any(
            not isinstance(item, dict)
            or item.get("version_name") != result["version_name"]
            or item.get("version_type") != 0
            or item.get("node_index") != 1
            for item in items
        )
    ):
        raise ColorWorkflowError("Color preset apply result is invalid.")


def _verify_applied_readback(
    target: dict[str, str], target_ids: list[str], readback: dict[str, Any]
) -> None:
    timeline = readback.get("timeline")
    items = readback.get("items")
    expected_ids = set(target_ids)
    actual_ids = {
        item.get("timeline_item_id")
        for item in items
        if isinstance(item, dict)
    } if isinstance(items, list) else set()
    if (
        not isinstance(timeline, dict)
        or timeline.get("timeline_id") != target["timeline_id"]
        or timeline.get("name") != target["timeline_name"]
        or actual_ids != expected_ids
        or any(
            not isinstance(item, dict)
            or item.get("current_version")
            != {
                "versionName": "DaVinci Agent Tutorial Clean v1",
                "versionType": 0,
            }
            or not isinstance(item.get("node_count"), int)
            or item["node_count"] < 1
            for item in items or []
        )
    ):
        raise ColorWorkflowError("Applied color version readback is invalid.")


def _map_duplicate_target_ids(
    preview: dict[str, Any],
    target: dict[str, str],
    target_live: dict[str, Any],
) -> list[str]:
    """Map source color targets to duplicate IDs using exact bounded identity."""
    items = target_live.get("items")
    source_items = preview.get("environment", {}).get("items")
    if (
        target_live.get("timeline_id") != target["timeline_id"]
        or target_live.get("name") != target["timeline_name"]
        or not isinstance(items, list)
        or not isinstance(source_items, list)
    ):
        raise ColorWorkflowError("Duplicate color timeline readback is invalid.")
    target_by_identity: dict[tuple[Any, ...], list[str]] = {}
    for item in items:
        if (
            not isinstance(item, dict)
            or item.get("track_type") != "video"
            or item.get("source_type") != "media"
        ):
            continue
        item_id = item.get("timeline_item_id")
        if not isinstance(item_id, str):
            raise ColorWorkflowError("Duplicate color item ID is invalid.")
        target_by_identity.setdefault(_duplicate_identity(item), []).append(item_id)
    mapped: list[str] = []
    for source in source_items:
        if not isinstance(source, dict):
            raise ColorWorkflowError("Source color item is invalid.")
        matches = target_by_identity.get(_duplicate_identity(source), [])
        if len(matches) != 1:
            raise ColorWorkflowError(
                "A source color item does not map uniquely to the duplicate."
            )
        mapped.append(matches[0])
    if len(mapped) != len(preview["targets"]) or len(set(mapped)) != len(mapped):
        raise ColorWorkflowError("Duplicate color target mapping is incomplete.")
    return sorted(mapped)


def _duplicate_identity(item: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        item.get(key)
        for key in (
            "name",
            "track_type",
            "track_index",
            "timeline_start_frame",
            "timeline_end_frame",
            "source_start_frame",
            "source_end_frame",
        )
    )


def _new_receipt(receipt_id: str, preview: dict[str, Any]) -> dict[str, Any]:
    return {
        "color_apply_version": COLOR_APPLY_VERSION,
        "receipt_id": receipt_id,
        "status": "in_progress",
        "plan": preview,
        "target": None,
        "operations": [
            {"operation": "duplicate_timeline", "status": "pending", "result": None},
            {"operation": "apply_color_preset", "status": "pending", "result": None},
        ],
        "readback": None,
    }


def _step_key(receipt_id: str, step: str) -> str:
    return hashlib.sha256(f"{receipt_id}:{step}".encode()).hexdigest()


def _items_sha256(items: list[Any]) -> str:
    bounded = []
    for item in items:
        if not isinstance(item, dict):
            raise ColorWorkflowError("Timeline readback contains an invalid item.")
        bounded.append(
            {
                key: item.get(key)
                for key in (
                    "timeline_item_id",
                    "name",
                    "track_type",
                    "track_index",
                    "source_type",
                    "timeline_start_frame",
                    "timeline_end_frame",
                    "source_start_frame",
                    "source_end_frame",
                )
            }
        )
    bounded.sort(key=lambda item: str(item["timeline_item_id"]))
    return _canonical_sha256(bounded)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ColorWorkflowError(f"{field} must be a lowercase SHA-256 value.")
    return value


def _timeline_name(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 128:
        raise ColorWorkflowError(
            "target_timeline_name must contain 1 to 128 characters."
        )
    return value.strip()


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ColorWorkflowError("timeout_seconds must be numeric.")
    timeout = float(value)
    if not 0 < timeout <= 300:
        raise ColorWorkflowError("timeout_seconds must be between 0 and 300.")
    return timeout
