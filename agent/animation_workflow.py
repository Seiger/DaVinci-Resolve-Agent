"""Provider-neutral M52 animation-template review and application."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from agent.animation_templates import AnimationTemplateCatalogue
from agent.contracts import validate_contract
from agent.paths import animation_template_runs_directory
from transports.filesystem import atomic_write_json, read_json_object

ANIMATION_PLAN_VERSION = "1.0"
ANIMATION_APPLY_VERSION = "1.0"
REQUIRED_CAPABILITIES = (
    "animation.template.insert",
    "clip.read",
    "timeline.duplicate",
)
TIMECODE_PATTERN = re.compile(r"^[0-9]{2,3}:[0-9]{2}:[0-9]{2}:[0-9]{2}$")


class AnimationWorkflowError(ValueError):
    """Raised when an M52 plan or application is unsafe or inconsistent."""


class BrollInspector(Protocol):
    """Applied M51 receipt boundary required by M52."""

    def status(
        self,
        receipt_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...


class AnimationGateway(Protocol):
    """Documented provider operations used by the M52 workflow."""

    def animation_template_environment(
        self,
        timeline_id: str,
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

    def insert_animation_template(
        self,
        timeline_id: str,
        template_id: str,
        timecode: str,
        *,
        confirm_insert: bool,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...


class AnimationTemplateWorkflow:
    """Preview and insert one packaged animation on a duplicated timeline."""

    def __init__(
        self,
        *,
        gateway: AnimationGateway,
        broll: BrollInspector,
        capabilities: Callable[[], dict[str, Any]],
        catalogue: AnimationTemplateCatalogue | None = None,
        receipts_root: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._broll = broll
        self._capabilities = capabilities
        self._catalogue = catalogue or AnimationTemplateCatalogue()
        self._receipts_root = (
            receipts_root or animation_template_runs_directory()
        )

    def list_templates(self) -> dict[str, Any]:
        """Return the immutable packaged template catalogue."""
        return self._catalogue.list_templates()

    def get_template(self, template_id: str) -> dict[str, Any]:
        """Return one immutable packaged template manifest."""
        return self._catalogue.get_template(template_id)

    def preview(
        self,
        *,
        broll_receipt_id: str,
        target_timeline_name: str,
        template_id: str,
        timecode: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Build one read-only deterministic M52 application plan."""
        receipt_id = _sha256(broll_receipt_id, "broll_receipt_id")
        target_name = _timeline_name(target_timeline_name)
        normalized_timecode = _timecode(timecode)
        timeout = _timeout(timeout_seconds)
        template = self._catalogue.get_template(template_id)
        broll = self._broll.status(receipt_id, timeout_seconds=timeout)
        target = broll.get("target")
        if (
            broll.get("status") != "applied"
            or not isinstance(target, dict)
            or not isinstance(target.get("timeline_id"), str)
            or not isinstance(target.get("timeline_name"), str)
        ):
            raise AnimationWorkflowError("An applied M51 receipt is required.")
        source_id = target["timeline_id"]
        source_name = target["timeline_name"]
        if target_name == source_name:
            raise AnimationWorkflowError(
                "target_timeline_name must differ from the M51 timeline."
            )
        live = self._gateway.timeline_items(source_id, timeout_seconds=timeout)
        source = _source_snapshot(live, source_id, source_name)
        environment = self._gateway.animation_template_environment(
            source_id, timeout_seconds=timeout
        )
        _verify_environment(environment, source_id, template)
        capabilities = self._capabilities()
        unsupported = sorted(
            capability
            for capability in REQUIRED_CAPABILITIES
            if capabilities.get(capability) is not True
        )
        inputs = {
            "broll_receipt_id": receipt_id,
            "target_timeline_name": target_name,
            "template_id": template["template_id"],
            "timecode": normalized_timecode,
        }
        payload = {
            "animation_plan_version": ANIMATION_PLAN_VERSION,
            "status": "preview",
            "apply_supported": not unsupported,
            "inputs": inputs,
            "source": source,
            "template": template,
            "environment": environment,
            "required_capabilities": list(REQUIRED_CAPABILITIES),
            "unsupported_capabilities": unsupported,
        }
        result = {**payload, "plan_id": _canonical_sha256(payload)}
        validate_contract("animation-template-preview", result)
        return result

    def apply(
        self,
        *,
        broll_receipt_id: str,
        target_timeline_name: str,
        template_id: str,
        timecode: str,
        expected_plan_id: str,
        confirm_apply: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Apply one exact reviewed M52 plan to a duplicate timeline."""
        if confirm_apply is not True:
            raise AnimationWorkflowError("confirm_apply must be true.")
        expected_id = _sha256(expected_plan_id, "expected_plan_id")
        timeout = _timeout(timeout_seconds)
        preview = self.preview(
            broll_receipt_id=broll_receipt_id,
            target_timeline_name=target_timeline_name,
            template_id=template_id,
            timecode=timecode,
            timeout_seconds=timeout,
        )
        if preview["plan_id"] != expected_id:
            raise AnimationWorkflowError(
                "expected_plan_id does not match the current preview."
            )
        if preview["apply_supported"] is not True:
            raise AnimationWorkflowError(
                "Required Resolve capabilities are not verified: "
                + ", ".join(preview["unsupported_capabilities"])
            )
        receipt_id = _canonical_sha256(
            {
                "animation_apply_version": ANIMATION_APPLY_VERSION,
                "plan_id": expected_id,
            }
        )
        path = self._receipts_root / f"{receipt_id}.json"
        if path.is_file():
            receipt = read_json_object(path)
            validate_contract("animation-template-result", receipt)
            if (
                receipt.get("receipt_id") != receipt_id
                or receipt.get("plan") != preview
            ):
                raise AnimationWorkflowError(
                    "Stored animation receipt does not match the plan."
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

        inserted = self._step(
            path,
            receipt,
            1,
            lambda: self._gateway.insert_animation_template(
                target["timeline_id"],
                preview["inputs"]["template_id"],
                preview["inputs"]["timecode"],
                confirm_insert=True,
                timeout_seconds=timeout,
                idempotency_key=_step_key(receipt_id, "insert"),
            ),
        )
        inserted_item = _inserted_item(target, preview, inserted)
        readback = self._gateway.timeline_items(
            target["timeline_id"], timeout_seconds=timeout
        )
        _verify_readback(target, inserted_item, readback)
        receipt["inserted_item"] = inserted_item
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
                raise AnimationWorkflowError(
                    "Applied animation operation has no result."
                )
            return result
        result = operation()
        if not isinstance(result, dict):
            raise AnimationWorkflowError(
                "Animation provider operation returned no object."
            )
        step["status"] = "applied"
        step["result"] = result
        self._persist(path, receipt)
        return result

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("animation-template-result", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)


def _source_snapshot(
    live: dict[str, Any], expected_id: str, expected_name: str
) -> dict[str, Any]:
    items = live.get("items")
    if (
        live.get("timeline_id") != expected_id
        or live.get("name") != expected_name
        or not isinstance(items, list)
        or not items
    ):
        raise AnimationWorkflowError("Live M51 timeline identity is invalid.")
    bounded = []
    for item in items:
        if not isinstance(item, dict):
            raise AnimationWorkflowError("Live timeline item is invalid.")
        bounded.append(
            {
                key: item.get(key)
                for key in (
                    "timeline_item_id",
                    "track_type",
                    "track_index",
                    "timeline_start_frame",
                    "timeline_end_frame",
                    "enabled",
                )
            }
        )
    bounded.sort(key=lambda item: str(item["timeline_item_id"]))
    return {
        "timeline_id": expected_id,
        "timeline_name": expected_name,
        "item_count": len(items),
        "snapshot_sha256": _canonical_sha256(bounded),
    }


def _verify_environment(
    environment: dict[str, Any],
    timeline_id: str,
    template: dict[str, Any],
) -> None:
    timeline = environment.get("timeline")
    templates = environment.get("templates")
    methods = environment.get("methods")
    if (
        not isinstance(timeline, dict)
        or timeline.get("timeline_id") != timeline_id
        or not isinstance(templates, list)
        or not isinstance(methods, dict)
        or not all(value is True for value in methods.values())
        or environment.get("ready") is not True
    ):
        raise AnimationWorkflowError(
            "The packaged animation-template environment is not ready."
        )
    matching = [
        item
        for item in templates
        if isinstance(item, dict)
        and item.get("template_id") == template["template_id"]
    ]
    if (
        len(matching) != 1
        or matching[0].get("resolve_name") != template["resolve_name"]
        or matching[0].get("installed") is not True
        or matching[0].get("sha256_matches") is not True
    ):
        raise AnimationWorkflowError(
            "The packaged animation template is missing or modified."
        )


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
        raise AnimationWorkflowError("Duplicate timeline result is invalid.")
    return {
        "timeline_id": timeline["timeline_id"],
        "timeline_name": timeline["name"],
    }


def _inserted_item(
    target: dict[str, str],
    preview: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    item = result.get("item")
    if (
        result.get("timeline_id") != target["timeline_id"]
        or result.get("template_id") != preview["inputs"]["template_id"]
        or result.get("resolve_name") != preview["template"]["resolve_name"]
        or result.get("requested_timecode") != preview["inputs"]["timecode"]
        or not isinstance(result.get("fusion_comp_count"), int)
        or result["fusion_comp_count"] < 1
        or not isinstance(item, dict)
        or not isinstance(item.get("timeline_item_id"), str)
        or item.get("track_type") != "video"
    ):
        raise AnimationWorkflowError(
            "Animation-template insert result is invalid."
        )
    return item


def _verify_readback(
    target: dict[str, str],
    inserted_item: dict[str, Any],
    readback: dict[str, Any],
) -> None:
    items = readback.get("items")
    if (
        readback.get("timeline_id") != target["timeline_id"]
        or readback.get("name") != target["timeline_name"]
        or not isinstance(items, list)
    ):
        raise AnimationWorkflowError("Animation target readback is invalid.")
    matches = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("timeline_item_id")
        == inserted_item["timeline_item_id"]
    ]
    fields = (
        "name",
        "track_type",
        "track_index",
        "timeline_start_frame",
        "timeline_end_frame",
        "duration_frames",
    )
    if len(matches) != 1 or any(
        matches[0].get(field) != inserted_item.get(field) for field in fields
    ):
        raise AnimationWorkflowError(
            "Inserted animation did not persist with exact canonical bounds."
        )


def _new_receipt(receipt_id: str, preview: dict[str, Any]) -> dict[str, Any]:
    return {
        "animation_apply_version": ANIMATION_APPLY_VERSION,
        "receipt_id": receipt_id,
        "status": "in_progress",
        "plan": preview,
        "target": None,
        "operations": [
            {"operation": "duplicate_timeline", "status": "pending", "result": None},
            {
                "operation": "insert_animation_template",
                "status": "pending",
                "result": None,
            },
        ],
        "inserted_item": None,
        "readback": None,
    }


def _timeline_name(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 128:
        raise AnimationWorkflowError(
            "target_timeline_name must contain 1 to 128 characters."
        )
    return value.strip()


def _timecode(value: str) -> str:
    if not isinstance(value, str) or TIMECODE_PATTERN.fullmatch(value) is None:
        raise AnimationWorkflowError("timecode must use HH:MM:SS:FF format.")
    return value


def _sha256(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AnimationWorkflowError(f"{field} must be a lowercase SHA-256 value.")
    return value


def _timeout(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 < value <= 300
    ):
        raise AnimationWorkflowError("timeout_seconds must be between 0 and 300.")
    return float(value)


def _canonical_sha256(value: Any) -> str:
    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _step_key(receipt_id: str, step: str) -> str:
    return hashlib.sha256(f"{receipt_id}:{step}".encode()).hexdigest()
