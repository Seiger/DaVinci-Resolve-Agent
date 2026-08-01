"""Provider-neutral M44 preparation of a finalized timeline render job."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import (
    finalized_render_preparations_directory,
    pause_compaction_finalizations_directory,
)
from agent.rendering import (
    validate_render_job_id,
    validate_render_name,
    validate_render_profile,
)
from transports.filesystem import atomic_write_json, read_json_object

RENDER_PREPARATION_VERSION = "1.0"


class FinalizedRenderPreparationError(ValueError):
    """Raised when a finalized timeline cannot be prepared for rendering."""


class FinalizedRenderGateway(Protocol):
    """Provider-neutral render preparation required by M44."""

    def prepare_render_job(
        self,
        custom_name: str,
        *,
        timeline_id: str,
        profile: str,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...


class FinalizedRenderPreparer:
    """Prepare one fixed render job bound to an applied M43 timeline."""

    def __init__(
        self,
        *,
        gateway: FinalizedRenderGateway,
        capabilities: Callable[[], dict[str, Any]],
        finalizations_root: Path | None = None,
        receipts_root: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._capabilities = capabilities
        self._finalizations_root = (
            pause_compaction_finalizations_directory()
            if finalizations_root is None
            else finalizations_root
        )
        self._receipts_root = (
            finalized_render_preparations_directory()
            if receipts_root is None
            else receipts_root
        )

    def prepare(
        self,
        *,
        finalization_receipt_id: str,
        custom_name: str,
        profile: str,
        confirm_prepare: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Prepare, verify, and persist one finalized-timeline render job."""
        inputs = _validated_inputs(
            finalization_receipt_id,
            custom_name,
            profile,
            confirm_prepare,
            timeout_seconds,
        )
        receipt_id = _receipt_id(inputs)
        receipt_path = self._receipts_root / f"{receipt_id}.json"
        if receipt_path.is_file():
            receipt = read_json_object(receipt_path)
            validate_contract("finalized-render-preparation", receipt)
            if receipt.get("receipt_id") != receipt_id or receipt.get(
                "inputs"
            ) != inputs:
                raise FinalizedRenderPreparationError(
                    "Stored render-preparation inputs do not match the request."
                )
            if receipt.get("status") == "applied":
                return receipt
        else:
            finalization = self._load_finalization(finalization_receipt_id)
            target = finalization.get("target")
            if not isinstance(target, dict):
                raise FinalizedRenderPreparationError(
                    "M43 finalization target is invalid."
                )
            receipt = {
                "render_preparation_version": RENDER_PREPARATION_VERSION,
                "receipt_id": receipt_id,
                "status": "in_progress",
                "inputs": inputs,
                "target": {
                    "timeline_id": target.get("timeline_id"),
                    "timeline_name": target.get("timeline_name"),
                },
                "operation": {
                    "operation": "prepare_render_job",
                    "status": "pending",
                    "result": None,
                },
            }
            self._persist(receipt_path, receipt)

        if self._capabilities().get("render.configure") is not True:
            raise FinalizedRenderPreparationError(
                "Required Resolve capability is not verified: render.configure"
            )
        operation = receipt["operation"]
        if operation["status"] != "applied":
            result = self._gateway.prepare_render_job(
                inputs["custom_name"],
                timeline_id=receipt["target"]["timeline_id"],
                profile=inputs["profile"],
                timeout_seconds=float(timeout_seconds),
                idempotency_key=f"{receipt_id}:prepare",
            )
            _verify_result(receipt, result)
            operation["status"] = "applied"
            operation["result"] = result
            receipt["status"] = "applied"
            self._persist(receipt_path, receipt)
        return receipt

    def _load_finalization(self, receipt_id: str) -> dict[str, Any]:
        path = self._finalizations_root / f"{receipt_id}.json"
        if not path.is_file():
            raise FinalizedRenderPreparationError(
                "M43 finalization receipt was not found."
            )
        receipt = read_json_object(path)
        validate_contract("pause-compaction-finalization", receipt)
        if receipt.get("receipt_id") != receipt_id or receipt.get(
            "status"
        ) != "applied":
            raise FinalizedRenderPreparationError(
                "M43 finalization receipt must be canonical and fully applied."
            )
        return receipt

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("finalized-render-preparation", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)


def _validated_inputs(
    finalization_receipt_id: str,
    custom_name: str,
    profile: str,
    confirm_prepare: bool,
    timeout_seconds: float,
) -> dict[str, str]:
    if (
        not isinstance(finalization_receipt_id, str)
        or len(finalization_receipt_id) != 64
        or any(
            character not in "0123456789abcdef"
            for character in finalization_receipt_id
        )
    ):
        raise FinalizedRenderPreparationError(
            "finalization_receipt_id must be a lowercase SHA-256 ID."
        )
    if confirm_prepare is not True:
        raise FinalizedRenderPreparationError("confirm_prepare must be true.")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= 300
    ):
        raise FinalizedRenderPreparationError(
            "timeout_seconds must be greater than zero and no more than 300."
        )
    return {
        "finalization_receipt_id": finalization_receipt_id,
        "custom_name": validate_render_name(custom_name),
        "profile": validate_render_profile(profile).name,
    }


def _verify_result(receipt: dict[str, Any], result: dict[str, Any]) -> None:
    profile = validate_render_profile(receipt["inputs"]["profile"])
    job_id = result.get("job_id")
    try:
        if not isinstance(job_id, str):
            raise ValueError("job_id is not a string")
        validate_render_job_id(job_id)
    except ValueError as error:
        raise FinalizedRenderPreparationError(
            "Resolve returned an invalid render job ID."
        ) from error
    if (
        result.get("timeline_id") != receipt["target"]["timeline_id"]
        or result.get("timeline_name") != receipt["target"]["timeline_name"]
        or result.get("custom_name") != receipt["inputs"]["custom_name"]
        or result.get("preset") != profile.name
        or result.get("width") != profile.width
        or result.get("height") != profile.height
        or result.get("format") != "MP4"
        or result.get("codec") != "H264"
        or result.get("started") is not False
    ):
        raise FinalizedRenderPreparationError(
            "Prepared render job does not match the finalized timeline policy."
        )


def _receipt_id(inputs: dict[str, str]) -> str:
    payload = json.dumps(
        {
            "render_preparation_version": RENDER_PREPARATION_VERSION,
            "inputs": inputs,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
