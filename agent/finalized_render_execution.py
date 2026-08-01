"""Provider-neutral M45 execution and inspection of a finalized render."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import (
    finalized_render_executions_directory,
    finalized_render_preparations_directory,
)
from agent.rendering import verify_render_output
from transports.filesystem import atomic_write_json, read_json_object

RENDER_EXECUTION_VERSION = "1.0"
REQUIRED_CAPABILITIES = ("render.discovery", "render.start")


class FinalizedRenderExecutionError(ValueError):
    """Raised when a finalized render cannot be started or inspected safely."""


class FinalizedRenderExecutionGateway(Protocol):
    """Provider-neutral render calls required by M45."""

    def render_job_status(
        self,
        job_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]: ...

    def start_render_job(
        self,
        job_id: str,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...


class FinalizedRenderExecutor:
    """Start one M44 job once and inspect its managed output read-only."""

    def __init__(
        self,
        *,
        gateway: FinalizedRenderExecutionGateway,
        capabilities: Callable[[], dict[str, Any]],
        preparations_root: Path | None = None,
        receipts_root: Path | None = None,
        expected_output_directory: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._capabilities = capabilities
        self._preparations_root = (
            finalized_render_preparations_directory()
            if preparations_root is None
            else preparations_root
        )
        self._receipts_root = (
            finalized_render_executions_directory()
            if receipts_root is None
            else receipts_root
        )
        self._expected_output_directory = expected_output_directory

    def start(
        self,
        *,
        preparation_receipt_id: str,
        confirm_render: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Start exactly one applied M44 job after a read-only preflight."""
        normalized_id = _validate_sha256(
            preparation_receipt_id,
            "preparation_receipt_id",
        )
        _validate_timeout(timeout_seconds)
        if confirm_render is not True:
            raise FinalizedRenderExecutionError("confirm_render must be true.")
        inputs = {"preparation_receipt_id": normalized_id}
        receipt_id = _receipt_id(inputs)
        receipt_path = self._receipts_root / f"{receipt_id}.json"
        if receipt_path.is_file():
            receipt = self._load_execution(receipt_id)
            if receipt.get("inputs") != inputs:
                raise FinalizedRenderExecutionError(
                    "Stored render-execution inputs do not match the request."
                )
            if receipt.get("status") == "started":
                return receipt
        else:
            self._require_capabilities()
            preparation = self._load_preparation(normalized_id)
            prepared_result = _prepared_result(preparation)
            live = self._gateway.render_job_status(
                prepared_result["job_id"],
                timeout_seconds=float(timeout_seconds),
            )
            output = self._verified_live_state(preparation, live)
            status = live.get("status")
            if (
                live.get("rendering_in_progress") is not False
                or not isinstance(status, dict)
                or status.get("JobStatus") != "Ready"
            ):
                raise FinalizedRenderExecutionError(
                    "The exact M44 render job must be Ready before start."
                )
            if output["output"]["exists"] is True:
                raise FinalizedRenderExecutionError(
                    "The managed render output already exists."
                )
            receipt = {
                "render_execution_version": RENDER_EXECUTION_VERSION,
                "receipt_id": receipt_id,
                "status": "in_progress",
                "inputs": inputs,
                "target": preparation["target"],
                "job": {
                    "job_id": prepared_result["job_id"],
                    "custom_name": prepared_result["custom_name"],
                    "profile": prepared_result["preset"],
                },
                "operation": {
                    "operation": "start_render_job",
                    "status": "pending",
                    "result": None,
                },
            }
            self._persist(receipt_path, receipt)

        self._require_capabilities()
        operation = receipt["operation"]
        result = self._gateway.start_render_job(
            receipt["job"]["job_id"],
            timeout_seconds=float(timeout_seconds),
            idempotency_key=f"{receipt_id}:start",
        )
        if (
            result.get("job_id") != receipt["job"]["job_id"]
            or result.get("started") is not True
        ):
            raise FinalizedRenderExecutionError(
                "Resolve did not confirm the exact M44 render start."
            )
        operation["status"] = "applied"
        operation["result"] = result
        receipt["status"] = "started"
        self._persist(receipt_path, receipt)
        return receipt

    def status(
        self,
        execution_receipt_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return live status and managed output validation without a write."""
        normalized_id = _validate_sha256(
            execution_receipt_id,
            "execution_receipt_id",
        )
        _validate_timeout(timeout_seconds)
        receipt = self._load_execution(normalized_id)
        if receipt.get("status") != "started":
            raise FinalizedRenderExecutionError(
                "Render execution receipt has not confirmed a start."
            )
        preparation = self._load_preparation(
            receipt["inputs"]["preparation_receipt_id"]
        )
        live = self._gateway.render_job_status(
            receipt["job"]["job_id"],
            timeout_seconds=float(timeout_seconds),
        )
        output = self._verified_live_state(preparation, live)
        return {
            "execution_receipt_id": normalized_id,
            "target": receipt["target"],
            "job": receipt["job"],
            "live": live,
            "output": output,
        }

    def _require_capabilities(self) -> None:
        capabilities = self._capabilities()
        unsupported = [
            name
            for name in REQUIRED_CAPABILITIES
            if capabilities.get(name) is not True
        ]
        if unsupported:
            raise FinalizedRenderExecutionError(
                "Required Resolve capabilities are not verified: "
                + ", ".join(unsupported)
            )

    def _load_preparation(self, receipt_id: str) -> dict[str, Any]:
        path = self._preparations_root / f"{receipt_id}.json"
        if not path.is_file():
            raise FinalizedRenderExecutionError(
                "M44 render-preparation receipt was not found."
            )
        receipt = read_json_object(path)
        validate_contract("finalized-render-preparation", receipt)
        if receipt.get("receipt_id") != receipt_id or receipt.get(
            "status"
        ) != "applied":
            raise FinalizedRenderExecutionError(
                "M44 render-preparation receipt must be canonical and applied."
            )
        return receipt

    def _load_execution(self, receipt_id: str) -> dict[str, Any]:
        path = self._receipts_root / f"{receipt_id}.json"
        if not path.is_file():
            raise FinalizedRenderExecutionError(
                "M45 render-execution receipt was not found."
            )
        receipt = read_json_object(path)
        validate_contract("finalized-render-execution", receipt)
        if receipt.get("receipt_id") != receipt_id:
            raise FinalizedRenderExecutionError(
                "M45 render-execution receipt filename does not match its ID."
            )
        return receipt

    def _verified_live_state(
        self,
        preparation: dict[str, Any],
        live: dict[str, Any],
    ) -> dict[str, Any]:
        prepared = _prepared_result(preparation)
        _verify_job_binding(preparation, prepared, live)
        return verify_render_output(
            live,
            expected_directory=self._expected_output_directory,
        )

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("finalized-render-execution", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)


def _prepared_result(preparation: dict[str, Any]) -> dict[str, Any]:
    operation = preparation.get("operation")
    result = operation.get("result") if isinstance(operation, dict) else None
    if not isinstance(result, dict):
        raise FinalizedRenderExecutionError(
            "M44 receipt has no applied render job result."
        )
    return result


def _verify_job_binding(
    preparation: dict[str, Any],
    prepared: dict[str, Any],
    live: dict[str, Any],
) -> None:
    job = live.get("job")
    target = preparation.get("target")
    expected_filename = f"{prepared.get('custom_name', '')}.mp4"
    valid = (
        isinstance(job, dict)
        and isinstance(target, dict)
        and live.get("job_id") == prepared.get("job_id")
        and job.get("JobId", prepared.get("job_id")) == prepared.get("job_id")
        and job.get("TimelineName") == target.get("timeline_name")
        and job.get("OutputFilename") == expected_filename
        and Path(str(job.get("TargetDir", ""))).resolve()
        == Path(str(prepared.get("target_directory", ""))).resolve()
        and job.get("PresetName") == prepared.get("resolve_preset")
        and job.get("FormatWidth") == prepared.get("width")
        and job.get("FormatHeight") == prepared.get("height")
        and job.get("VideoFormat") == "MP4"
        and job.get("VideoCodec") in {"H.264", "H264"}
    )
    if not valid:
        raise FinalizedRenderExecutionError(
            "Live render job no longer matches the applied M44 receipt."
        )


def _validate_sha256(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FinalizedRenderExecutionError(
            f"{name} must be a lowercase SHA-256 ID."
        )
    return value


def _validate_timeout(timeout_seconds: float) -> float:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= 300
    ):
        raise FinalizedRenderExecutionError(
            "timeout_seconds must be greater than zero and no more than 300."
        )
    return float(timeout_seconds)


def _receipt_id(inputs: dict[str, str]) -> str:
    payload = json.dumps(
        {"render_execution_version": RENDER_EXECUTION_VERSION, "inputs": inputs},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
