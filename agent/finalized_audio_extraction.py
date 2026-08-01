"""Guarded M46 extraction of finalized timeline audio as PCM WAV."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import (
    audio_source_directory,
    finalized_audio_extractions_directory,
    pause_compaction_finalizations_directory,
)
from agent.rendering import (
    AUDIO_RENDER_PROFILE,
    validate_render_job_id,
    validate_render_name,
    verify_pcm_wav_render_output,
)
from transports.filesystem import atomic_write_json, read_json_object

EXTRACTION_VERSION = "1.0"
REQUIRED_PREPARE_CAPABILITIES = ("render.configure",)
REQUIRED_START_CAPABILITIES = ("render.discovery", "render.start")


class FinalizedAudioExtractionError(ValueError):
    """Raised when a finalized timeline audio export is unsafe or invalid."""


class FinalizedAudioExtractionGateway(Protocol):
    """Provider-neutral render calls required by the M46 extraction stage."""

    def prepare_render_job(
        self,
        custom_name: str,
        *,
        timeline_id: str,
        profile: str,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

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


class FinalizedAudioExtractor:
    """Prepare, start, and inspect one full-timeline PCM WAV export."""

    def __init__(
        self,
        *,
        gateway: FinalizedAudioExtractionGateway,
        capabilities: Callable[[], dict[str, Any]],
        finalizations_root: Path | None = None,
        receipts_root: Path | None = None,
        expected_output_directory: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._capabilities = capabilities
        self._finalizations_root = (
            pause_compaction_finalizations_directory()
            if finalizations_root is None
            else finalizations_root
        )
        self._receipts_root = (
            finalized_audio_extractions_directory()
            if receipts_root is None
            else receipts_root
        )
        self._expected_output_directory = (
            audio_source_directory()
            if expected_output_directory is None
            else expected_output_directory
        )

    def prepare(
        self,
        *,
        finalization_receipt_id: str,
        custom_name: str,
        confirm_prepare: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Prepare one fixed Audio Only job without starting it."""
        inputs = _validated_prepare_inputs(
            finalization_receipt_id,
            custom_name,
            confirm_prepare,
            timeout_seconds,
        )
        receipt_id = _receipt_id(inputs)
        receipt_path = self._receipts_root / f"{receipt_id}.json"
        if receipt_path.is_file():
            receipt = self._load_extraction(receipt_id)
            if receipt.get("inputs") != inputs:
                raise FinalizedAudioExtractionError(
                    "Stored audio-extraction inputs do not match the request."
                )
            if receipt.get("status") in {"prepared", "started"}:
                return receipt
        else:
            finalization = self._load_finalization(finalization_receipt_id)
            target = finalization.get("target")
            if not isinstance(target, dict):
                raise FinalizedAudioExtractionError(
                    "M43 finalization target is invalid."
                )
            receipt = {
                "audio_extraction_version": EXTRACTION_VERSION,
                "receipt_id": receipt_id,
                "status": "in_progress",
                "inputs": inputs,
                "target": {
                    "timeline_id": target.get("timeline_id"),
                    "timeline_name": target.get("timeline_name"),
                },
                "job": None,
                "operations": [
                    {
                        "operation": "prepare_render_job",
                        "status": "pending",
                        "result": None,
                    },
                    {
                        "operation": "start_render_job",
                        "status": "pending",
                        "result": None,
                    },
                ],
            }
            self._persist(receipt_path, receipt)

        self._require_capabilities(REQUIRED_PREPARE_CAPABILITIES)
        result = self._gateway.prepare_render_job(
            inputs["custom_name"],
            timeline_id=receipt["target"]["timeline_id"],
            profile=AUDIO_RENDER_PROFILE,
            timeout_seconds=float(timeout_seconds),
            idempotency_key=f"{receipt_id}:prepare",
        )
        _verify_prepared_result(receipt, result, self._expected_output_directory)
        receipt["job"] = {
            "job_id": result["job_id"],
            "custom_name": result["custom_name"],
            "profile": result["preset"],
        }
        receipt["operations"][0] = {
            "operation": "prepare_render_job",
            "status": "applied",
            "result": result,
        }
        receipt["status"] = "prepared"
        self._persist(receipt_path, receipt)
        return receipt

    def start(
        self,
        extraction_receipt_id: str,
        *,
        confirm_render: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Start the exact prepared audio job once after live preflight."""
        receipt_id = _validate_sha256(
            extraction_receipt_id, "extraction_receipt_id"
        )
        _validate_timeout(timeout_seconds)
        if confirm_render is not True:
            raise FinalizedAudioExtractionError("confirm_render must be true.")
        receipt = self._load_extraction(receipt_id)
        if receipt.get("status") == "started":
            return receipt
        if receipt.get("status") != "prepared":
            raise FinalizedAudioExtractionError(
                "Audio extraction must be fully prepared before start."
            )
        self._require_capabilities(REQUIRED_START_CAPABILITIES)
        prepared = _prepared_result(receipt)
        live = self._gateway.render_job_status(
            prepared["job_id"], timeout_seconds=float(timeout_seconds)
        )
        _verify_job_binding(receipt, prepared, live)
        output = verify_pcm_wav_render_output(
            live, expected_directory=self._expected_output_directory
        )
        status = live.get("status")
        if (
            live.get("rendering_in_progress") is not False
            or not isinstance(status, dict)
            or status.get("JobStatus") != "Ready"
        ):
            raise FinalizedAudioExtractionError(
                "The exact audio render job must be Ready before start."
            )
        if output["output"]["exists"] is True:
            raise FinalizedAudioExtractionError(
                "The managed audio output already exists."
            )
        result = self._gateway.start_render_job(
            prepared["job_id"],
            timeout_seconds=float(timeout_seconds),
            idempotency_key=f"{receipt_id}:start",
        )
        if (
            result.get("job_id") != prepared["job_id"]
            or result.get("started") is not True
        ):
            raise FinalizedAudioExtractionError(
                "Resolve did not confirm the exact audio render start."
            )
        receipt["operations"][1] = {
            "operation": "start_render_job",
            "status": "applied",
            "result": result,
        }
        receipt["status"] = "started"
        self._persist(
            self._receipts_root / f"{receipt_id}.json",
            receipt,
        )
        return receipt

    def status(
        self,
        extraction_receipt_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return live job status and strict PCM WAV validation read-only."""
        receipt_id = _validate_sha256(
            extraction_receipt_id, "extraction_receipt_id"
        )
        _validate_timeout(timeout_seconds)
        receipt = self._load_extraction(receipt_id)
        if receipt.get("status") != "started":
            raise FinalizedAudioExtractionError(
                "Audio extraction must be started before status inspection."
            )
        self._require_capabilities(("render.discovery",))
        prepared = _prepared_result(receipt)
        live = self._gateway.render_job_status(
            prepared["job_id"], timeout_seconds=float(timeout_seconds)
        )
        _verify_job_binding(receipt, prepared, live)
        return {
            "receipt": receipt,
            "live": live,
            "output": verify_pcm_wav_render_output(
                live, expected_directory=self._expected_output_directory
            ),
        }

    def _load_finalization(self, receipt_id: str) -> dict[str, Any]:
        normalized = _validate_sha256(receipt_id, "finalization_receipt_id")
        path = self._finalizations_root / f"{normalized}.json"
        if not path.is_file():
            raise FinalizedAudioExtractionError(
                "M43 finalization receipt was not found."
            )
        receipt = read_json_object(path)
        validate_contract("pause-compaction-finalization", receipt)
        if receipt.get("receipt_id") != normalized or receipt.get(
            "status"
        ) != "applied":
            raise FinalizedAudioExtractionError(
                "M43 finalization receipt must be canonical and fully applied."
            )
        return receipt

    def _load_extraction(self, receipt_id: str) -> dict[str, Any]:
        path = self._receipts_root / f"{receipt_id}.json"
        if not path.is_file():
            raise FinalizedAudioExtractionError(
                "M46 audio-extraction receipt was not found."
            )
        receipt = read_json_object(path)
        validate_contract("finalized-audio-extraction", receipt)
        if receipt.get("receipt_id") != receipt_id:
            raise FinalizedAudioExtractionError(
                "M46 audio-extraction receipt filename does not match its ID."
            )
        return receipt

    def _require_capabilities(self, names: tuple[str, ...]) -> None:
        capabilities = self._capabilities()
        unsupported = [name for name in names if capabilities.get(name) is not True]
        if unsupported:
            raise FinalizedAudioExtractionError(
                "Required Resolve capabilities are not verified: "
                + ", ".join(unsupported)
            )

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("finalized-audio-extraction", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)


def _validated_prepare_inputs(
    finalization_receipt_id: str,
    custom_name: str,
    confirm_prepare: bool,
    timeout_seconds: float,
) -> dict[str, str]:
    receipt_id = _validate_sha256(
        finalization_receipt_id, "finalization_receipt_id"
    )
    if confirm_prepare is not True:
        raise FinalizedAudioExtractionError("confirm_prepare must be true.")
    _validate_timeout(timeout_seconds)
    return {
        "finalization_receipt_id": receipt_id,
        "custom_name": validate_render_name(custom_name),
        "profile": AUDIO_RENDER_PROFILE,
    }


def _verify_prepared_result(
    receipt: dict[str, Any],
    result: dict[str, Any],
    expected_directory: Path,
) -> None:
    job_id = result.get("job_id")
    try:
        if not isinstance(job_id, str):
            raise ValueError("job_id is not a string")
        validate_render_job_id(job_id)
    except ValueError as error:
        raise FinalizedAudioExtractionError(
            "Resolve returned an invalid audio render job ID."
        ) from error
    target = receipt.get("target")
    format_name = str(result.get("format", "")).casefold()
    if (
        not isinstance(target, dict)
        or result.get("timeline_id") != target.get("timeline_id")
        or result.get("timeline_name") != target.get("timeline_name")
        or result.get("custom_name") != receipt["inputs"]["custom_name"]
        or result.get("preset") != AUDIO_RENDER_PROFILE
        or result.get("resolve_preset") != "Audio Only"
        or format_name not in {"wave", "wav"}
        or result.get("audio_bit_depth") != 16
        or result.get("audio_sample_rate") != 48_000
        or result.get("export_video") is not False
        or result.get("export_audio") is not True
        or Path(str(result.get("target_directory", ""))).resolve()
        != expected_directory.resolve()
        or result.get("started") is not False
    ):
        raise FinalizedAudioExtractionError(
            "Prepared audio job does not match the fixed PCM WAV policy."
        )


def _prepared_result(receipt: dict[str, Any]) -> dict[str, Any]:
    operations = receipt.get("operations")
    operation = operations[0] if isinstance(operations, list) and operations else None
    result = operation.get("result") if isinstance(operation, dict) else None
    if (
        not isinstance(operation, dict)
        or not isinstance(result, dict)
        or operation.get("status") != "applied"
    ):
        raise FinalizedAudioExtractionError(
            "M46 receipt has no applied audio render job result."
        )
    return result


def _verify_job_binding(
    receipt: dict[str, Any],
    prepared: dict[str, Any],
    live: dict[str, Any],
) -> None:
    job = live.get("job")
    target = receipt.get("target")
    valid = (
        isinstance(job, dict)
        and isinstance(target, dict)
        and live.get("job_id") == prepared.get("job_id")
        and job.get("JobId", prepared.get("job_id")) == prepared.get("job_id")
        and job.get("TimelineName") == target.get("timeline_name")
        and job.get("OutputFilename") == f"{prepared.get('custom_name', '')}.wav"
        and Path(str(job.get("TargetDir", ""))).resolve()
        == Path(str(prepared.get("target_directory", ""))).resolve()
        and job.get("PresetName") == "Audio Only"
        and job.get("IsExportVideo") is False
        and job.get("IsExportAudio") is True
        and job.get("AudioBitDepth") == 16
        and job.get("AudioSampleRate") == 48_000
    )
    if not valid:
        raise FinalizedAudioExtractionError(
            "Live audio render job no longer matches the M46 receipt."
        )


def _validate_sha256(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FinalizedAudioExtractionError(
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
        raise FinalizedAudioExtractionError(
            "timeout_seconds must be greater than zero and no more than 300."
        )
    return float(timeout_seconds)


def _receipt_id(inputs: dict[str, str]) -> str:
    payload = json.dumps(
        {"audio_extraction_version": EXTRACTION_VERSION, "inputs": inputs},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
