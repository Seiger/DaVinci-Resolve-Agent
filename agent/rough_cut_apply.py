"""M34 guarded application of approved rough-cut plans."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.contracts import validate_contract
from agent.paths import rough_cut_apply_directory
from agent.rough_cut import RoughCutInspector
from transports.filesystem import atomic_write_json, read_json_object

APPLY_VERSION = "1.0"


class RoughCutApplyError(ValueError):
    """Raised when a rough-cut plan is not safe to apply."""


class RoughCutApplier:
    """Preview and apply only fully supported, approved plans to a copy."""

    def __init__(
        self,
        *,
        inspector: RoughCutInspector | None = None,
        capabilities: Callable[[], dict[str, Any]],
        duplicate_timeline: Callable[[str, str, str, float], dict[str, Any]],
        receipts_root: Path | None = None,
    ) -> None:
        self._inspector = RoughCutInspector() if inspector is None else inspector
        self._capabilities = capabilities
        self._duplicate_timeline = duplicate_timeline
        self._receipts_root = (
            rough_cut_apply_directory()
            if receipts_root is None
            else receipts_root
        )

    def preview(
        self,
        plan_id: str,
        source_timeline_id: str,
        target_timeline_name: str,
    ) -> dict[str, Any]:
        """Return exact planned operations without changing Resolve."""
        plan, approval = self._approved_plan(plan_id)
        self._validate_target(source_timeline_id, target_timeline_name)
        capabilities = self._capabilities()
        required = set(plan["required_capabilities"])
        required.add("timeline.duplicate")
        unsupported = sorted(
            capability
            for capability in required
            if capabilities.get(capability) is not True
        )
        unsupported_operations = sorted(
            {
                str(operation["operation"])
                for operation in plan["proposed_operations"]
            }
        )
        blocked = bool(unsupported or unsupported_operations)
        operations = [
            {
                "operation": "duplicate_timeline",
                "status": "planned" if not blocked else "blocked",
                "result": None,
            },
            *[
                {
                    "operation": str(operation["operation"]),
                    "status": "blocked",
                    "result": None,
                }
                for operation in plan["proposed_operations"]
            ],
        ]
        result = {
            "apply_version": APPLY_VERSION,
            "plan_id": plan_id,
            "plan_sha256": approval["plan_sha256"],
            "source_timeline_id": source_timeline_id,
            "target_timeline_name": target_timeline_name,
            "status": "preview" if not blocked else "blocked",
            "preview": True,
            "unsupported_capabilities": unsupported,
            "unsupported_operations": unsupported_operations,
            "operations": operations,
            "receipt_id": None,
        }
        validate_contract("rough-cut-apply-result", result)
        return result

    def apply(
        self,
        plan_id: str,
        source_timeline_id: str,
        target_timeline_name: str,
        *,
        confirm_apply: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Apply only a fully supported approved plan, with a durable replay receipt."""
        if confirm_apply is not True:
            raise RoughCutApplyError("confirm_apply must be true.")
        preview = self.preview(plan_id, source_timeline_id, target_timeline_name)
        if preview["status"] == "blocked":
            return preview
        receipt_id = _receipt_id(
            plan_id,
            preview["plan_sha256"],
            source_timeline_id,
            target_timeline_name,
        )
        receipt_path = self._receipts_root / f"{receipt_id}.json"
        if receipt_path.is_file():
            existing = read_json_object(receipt_path)
            validate_contract("rough-cut-apply-result", existing)
            return existing

        duplicated = self._duplicate_timeline(
            source_timeline_id,
            target_timeline_name,
            receipt_id,
            timeout_seconds,
        )
        result = {
            **preview,
            "status": "applied",
            "preview": False,
            "receipt_id": receipt_id,
        }
        result["operations"][0] = {
            "operation": "duplicate_timeline",
            "status": "applied",
            "result": duplicated,
        }
        validate_contract("rough-cut-apply-result", result)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(receipt_path, result)
        return result

    def _approved_plan(self, plan_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        detail = self._inspector.get_plan(plan_id)
        approval = detail["approval"]
        if approval is None or approval.get("status") != "approved":
            raise RoughCutApplyError(
                "A current matching rough-cut approval is required."
            )
        if approval.get("plan_sha256") != _canonical_sha256(detail["plan"]):
            raise RoughCutApplyError(
                "Approval SHA-256 does not match the current plan."
            )
        return detail["plan"], approval

    @staticmethod
    def _validate_target(source_timeline_id: str, target_timeline_name: str) -> None:
        if not source_timeline_id or len(source_timeline_id) > 128:
            raise RoughCutApplyError(
                "source_timeline_id must contain 1 to 128 characters."
            )
        if not target_timeline_name.strip() or len(target_timeline_name) > 128:
            raise RoughCutApplyError(
                "target_timeline_name must contain 1 to 128 characters."
            )


def _canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _receipt_id(
    plan_id: str,
    plan_sha256: str,
    source_timeline_id: str,
    target_timeline_name: str,
) -> str:
    return _canonical_sha256(
        {
            "plan_id": plan_id,
            "plan_sha256": plan_sha256,
            "source_timeline_id": source_timeline_id,
            "target_timeline_name": target_timeline_name,
        }
    )
