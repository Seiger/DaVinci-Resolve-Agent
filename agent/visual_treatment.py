"""Provider-neutral M49 title, static zoom, and reframing workflow."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import visual_treatments_directory
from transports.filesystem import atomic_write_json, read_json_object

VISUAL_TREATMENT_VERSION = "1.0"
_TIMECODE = re.compile(r"^\d{2,3}:\d{2}:\d{2}:\d{2}$")


class VisualTreatmentError(ValueError):
    """Raised when a visual treatment cannot be previewed or applied safely."""


class VisualTreatmentGateway(Protocol):
    """Provider-neutral writes needed by the bounded M49 workflow."""

    def set_clip_transforms(
        self,
        timeline_id: str,
        items: list[dict[str, Any]],
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def insert_title(
        self,
        timeline_id: str,
        title_name: str,
        timecode: str,
        *,
        confirm_insert: bool,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...


class VisualTreatmentWorkflow:
    """Preview and durably apply explicit static visual operations."""

    def __init__(
        self,
        *,
        gateway: VisualTreatmentGateway,
        capabilities: Callable[[], dict[str, Any]],
        receipts_root: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._capabilities = capabilities
        self._receipts_root = (
            visual_treatments_directory()
            if receipts_root is None
            else receipts_root
        )

    def preview(
        self,
        timeline_id: str,
        transforms: list[dict[str, Any]],
        titles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Normalize a visual plan and report live capability gates."""
        inputs = _validated_inputs(timeline_id, transforms, titles)
        required = []
        if inputs["transforms"]:
            required.append("clip.transform")
        if inputs["titles"]:
            required.append("title.insert")
        capabilities = self._capabilities()
        missing = [name for name in required if capabilities.get(name) is not True]
        return {
            "visual_treatment_version": VISUAL_TREATMENT_VERSION,
            "receipt_id": _receipt_id(inputs),
            "inputs": inputs,
            "required_capabilities": required,
            "missing_capabilities": missing,
            "ready": not missing,
            "limitations": [
                "Reframing is static and uses documented clip properties only.",
                "Titles insert an installed standard title by name; M49 does "
                "not mutate title text or Fusion controls.",
            ],
        }

    def apply(
        self,
        timeline_id: str,
        transforms: list[dict[str, Any]],
        titles: list[dict[str, Any]],
        *,
        confirm_apply: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Apply an exact preview with per-operation durable replay."""
        if confirm_apply is not True:
            raise VisualTreatmentError("confirm_apply must be true.")
        if not _finite_number(timeout_seconds) or not 0 < float(timeout_seconds) <= 300:
            raise VisualTreatmentError(
                "timeout_seconds must be greater than zero and no more than 300."
            )
        preview = self.preview(timeline_id, transforms, titles)
        if preview["missing_capabilities"]:
            raise VisualTreatmentError(
                "Required Resolve capabilities are not verified: "
                + ", ".join(preview["missing_capabilities"])
            )
        receipt_id = str(preview["receipt_id"])
        path = self._receipts_root / f"{receipt_id}.json"
        if path.is_file():
            receipt = read_json_object(path)
            validate_contract("visual-treatment-result", receipt)
            if (
                receipt["receipt_id"] != receipt_id
                or receipt["inputs"] != preview["inputs"]
            ):
                raise VisualTreatmentError(
                    "Stored visual treatment does not match the request."
                )
            if receipt["status"] == "applied":
                return receipt
        else:
            operations: list[dict[str, Any]] = []
            if preview["inputs"]["transforms"]:
                operations.append(
                    {"kind": "set_clip_transforms", "status": "pending", "result": None}
                )
            operations.extend(
                {
                    "kind": "insert_title",
                    "status": "pending",
                    "title_index": index,
                    "result": None,
                }
                for index, _ in enumerate(preview["inputs"]["titles"])
            )
            receipt = {
                "visual_treatment_version": VISUAL_TREATMENT_VERSION,
                "receipt_id": receipt_id,
                "status": "in_progress",
                "inputs": preview["inputs"],
                "operations": operations,
            }
            self._persist(path, receipt)

        operation_index = 0
        if preview["inputs"]["transforms"]:
            operation = receipt["operations"][operation_index]
            if operation["status"] != "applied":
                operation["result"] = self._gateway.set_clip_transforms(
                    timeline_id,
                    preview["inputs"]["transforms"],
                    timeout_seconds=float(timeout_seconds),
                    idempotency_key=f"{receipt_id}:transforms",
                )
                operation["status"] = "applied"
                self._persist(path, receipt)
            operation_index += 1

        for title_index, title in enumerate(preview["inputs"]["titles"]):
            operation = receipt["operations"][operation_index]
            if operation["status"] != "applied":
                operation["result"] = self._gateway.insert_title(
                    timeline_id,
                    title["title_name"],
                    title["timecode"],
                    confirm_insert=True,
                    timeout_seconds=float(timeout_seconds),
                    idempotency_key=f"{receipt_id}:title:{title_index}",
                )
                operation["status"] = "applied"
                self._persist(path, receipt)
            operation_index += 1
        receipt["status"] = "applied"
        self._persist(path, receipt)
        return receipt

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("visual-treatment-result", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)


def _validated_inputs(
    timeline_id: str,
    transforms: list[dict[str, Any]],
    titles: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(timeline_id, str) or not 1 <= len(timeline_id) <= 128:
        raise VisualTreatmentError("timeline_id must contain 1 to 128 characters.")
    if not isinstance(transforms, list) or len(transforms) > 1001:
        raise VisualTreatmentError("transforms must contain at most 1001 items.")
    if not isinstance(titles, list) or len(titles) > 100:
        raise VisualTreatmentError("titles must contain at most 100 items.")
    if not transforms and not titles:
        raise VisualTreatmentError("At least one transform or title is required.")
    normalized_transforms = [_validated_transform(item) for item in transforms]
    ids = [item["timeline_item_id"] for item in normalized_transforms]
    if len(ids) != len(set(ids)):
        raise VisualTreatmentError("Transform timeline_item_id values must be unique.")
    normalized_titles = [_validated_title(item) for item in titles]
    return {
        "timeline_id": timeline_id,
        "transforms": normalized_transforms,
        "titles": normalized_titles,
    }


def _validated_transform(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise VisualTreatmentError("Every transform must be an object.")
    allowed = {
        "timeline_item_id",
        "position_x",
        "position_y",
        "zoom",
        "rotation_degrees",
        "opacity_percent",
    }
    if not set(item).issubset(allowed) or "timeline_item_id" not in item:
        raise VisualTreatmentError("Transform fields do not match the fixed allowlist.")
    item_id = item["timeline_item_id"]
    if not isinstance(item_id, str) or not 1 <= len(item_id) <= 128:
        raise VisualTreatmentError("timeline_item_id must contain 1 to 128 characters.")
    ranges = {
        "position_x": (-32768.0, 32768.0),
        "position_y": (-32768.0, 32768.0),
        "zoom": (0.0, 100.0),
        "rotation_degrees": (-360.0, 360.0),
        "opacity_percent": (0.0, 100.0),
    }
    if not set(item).intersection(ranges):
        raise VisualTreatmentError("Every transform needs an allowlisted value.")
    normalized: dict[str, Any] = {"timeline_item_id": item_id}
    for name, (minimum, maximum) in ranges.items():
        if name not in item:
            continue
        value = item[name]
        if not _finite_number(value) or not minimum <= float(value) <= maximum:
            raise VisualTreatmentError(
                f"{name} must be a finite number from {minimum} to {maximum}."
            )
        normalized[name] = float(value)
    return normalized


def _validated_title(item: dict[str, Any]) -> dict[str, str]:
    if not isinstance(item, dict) or set(item) != {"title_name", "timecode"}:
        raise VisualTreatmentError("Every title requires title_name and timecode only.")
    title_name = item["title_name"]
    timecode = item["timecode"]
    if not isinstance(title_name, str) or not 1 <= len(title_name) <= 128:
        raise VisualTreatmentError("title_name must contain 1 to 128 characters.")
    if not isinstance(timecode, str) or _TIMECODE.fullmatch(timecode) is None:
        raise VisualTreatmentError("timecode must use HH:MM:SS:FF format.")
    return {"title_name": title_name, "timecode": timecode}


def _finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _receipt_id(inputs: dict[str, Any]) -> str:
    payload = json.dumps(
        {"visual_treatment_version": VISUAL_TREATMENT_VERSION, "inputs": inputs},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
