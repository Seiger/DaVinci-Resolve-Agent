"""M55.8 approved take-sequence render orchestration."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import render_output_directory, take_sequence_renders_directory
from agent.rendering import (
    validate_render_job_id,
    validate_render_name,
    validate_render_profile,
    verify_render_output,
)
from transports.filesystem import atomic_write_json, read_json_object

PLAN_VERSION = "1.0"
RENDER_VERSION = "1.0"
REQUIRED_CAPABILITIES = (
    "render.configure",
    "render.discovery",
    "render.start",
)


class TakeSequenceRenderError(ValueError):
    """Raised when an approved sequence cannot be rendered safely."""


class SequenceQcReader(Protocol):
    def get(
        self,
        report_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...

    def get_review(
        self,
        report_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...


class SequenceRenderGateway(Protocol):
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


class TakeSequenceRenderWorkflow:
    """Preview, start and verify one render accepted through M55.7."""

    def __init__(
        self,
        *,
        qc: SequenceQcReader,
        gateway: SequenceRenderGateway,
        capabilities: Callable[[], dict[str, Any]],
        receipts_root: Path | None = None,
        output_root: Path | None = None,
    ) -> None:
        self._qc = qc
        self._gateway = gateway
        self._capabilities = capabilities
        self._receipts_root = receipts_root or take_sequence_renders_directory()
        self._output_root = output_root or render_output_directory()

    def preview(
        self,
        *,
        qc_report_id: str,
        custom_name: str,
        profile: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Build a deterministic render plan without changing Resolve."""
        report_id = _sha256(qc_report_id, "qc_report_id")
        timeout = _timeout(timeout_seconds)
        report, review = self._approved_evidence(report_id, timeout)
        selected_profile = validate_render_profile(profile)
        base_name = validate_render_name(custom_name)
        render_name = _render_name(base_name, review["review_id"])
        capabilities = self._capabilities()
        if not isinstance(capabilities, dict):
            raise TakeSequenceRenderError("Resolve capability snapshot is invalid.")
        unsupported = [
            name for name in REQUIRED_CAPABILITIES if capabilities.get(name) is not True
        ]
        output_available = not (self._output_root / f"{render_name}.mp4").is_file()
        blockers = [] if output_available else ["managed_output_already_exists"]
        payload = {
            "render_plan_version": PLAN_VERSION,
            "status": "preview",
            "inputs": {
                "qc_report_id": report_id,
                "custom_name": base_name,
                "profile": selected_profile.name,
            },
            "qc_report_sha256": _canonical_sha256(report),
            "qc_review_sha256": _canonical_sha256(review),
            "target_timeline": report["target_timeline"],
            "render": {
                "custom_name": render_name,
                "profile": selected_profile.name,
                "width": selected_profile.width,
                "height": selected_profile.height,
                "format": "MP4",
                "codec": "H264",
                "output_filename": f"{render_name}.mp4",
            },
            "required_capabilities": list(REQUIRED_CAPABILITIES),
            "unsupported_capabilities": unsupported,
            "blockers": blockers,
            "output_root_configured": True,
            "paths_redacted": True,
            "timeline_modified": False,
            "apply_supported": not unsupported and not blockers,
        }
        result = {"plan_id": _canonical_sha256(payload), **payload}
        validate_contract("take-sequence-render-preview", result)
        return result

    def start(
        self,
        *,
        qc_report_id: str,
        custom_name: str,
        profile: str,
        expected_plan_id: str,
        confirm_render: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Prepare and start one exact reviewed render with durable replay."""
        if confirm_render is not True:
            raise TakeSequenceRenderError("confirm_render must be true.")
        timeout = _timeout(timeout_seconds)
        report_id = _sha256(qc_report_id, "qc_report_id")
        expected_id = _sha256(expected_plan_id, "expected_plan_id")
        normalized_name = validate_render_name(custom_name)
        normalized_profile = validate_render_profile(profile).name
        inputs = {
            "qc_report_id": report_id,
            "expected_plan_id": expected_id,
        }
        receipt_id = _canonical_sha256(
            {"render_version": RENDER_VERSION, "inputs": inputs}
        )
        path = self._receipts_root / f"{receipt_id}.json"
        existing: dict[str, Any] | None = None
        if path.is_file():
            existing = self._load(receipt_id)
            if existing.get("inputs") != inputs:
                raise TakeSequenceRenderError(
                    "Stored sequence-render receipt does not match current inputs."
                )
            stored_inputs = existing.get("plan", {}).get("inputs", {})
            if (
                stored_inputs.get("custom_name") != normalized_name
                or stored_inputs.get("profile") != normalized_profile
            ):
                raise TakeSequenceRenderError(
                    "Stored sequence-render plan does not match render arguments."
                )
            if existing.get("status") == "started":
                report, review = self._approved_evidence(report_id, timeout)
                plan = existing["plan"]
                if (
                    _canonical_sha256(report) != plan["qc_report_sha256"]
                    or _canonical_sha256(review) != plan["qc_review_sha256"]
                ):
                    raise TakeSequenceRenderError(
                        "Sequence QC evidence changed after render start."
                    )
                return existing
        plan = self.preview(
            qc_report_id=report_id,
            custom_name=normalized_name,
            profile=normalized_profile,
            timeout_seconds=timeout,
        )
        if plan["plan_id"] != expected_id:
            raise TakeSequenceRenderError(
                "expected_plan_id does not match the current render preview."
            )
        if plan["apply_supported"] is not True:
            reasons = plan["blockers"] + plan["unsupported_capabilities"]
            raise TakeSequenceRenderError(
                "Sequence render is blocked: " + ", ".join(reasons)
            )
        if existing is not None:
            receipt = existing
            if receipt.get("plan") != plan:
                raise TakeSequenceRenderError(
                    "Stored sequence-render receipt does not match current inputs."
                )
        else:
            receipt = {
                "render_version": RENDER_VERSION,
                "receipt_id": receipt_id,
                "status": "in_progress",
                "inputs": inputs,
                "plan": plan,
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
                "paths_redacted": True,
            }
            self._persist(path, receipt)

        prepare_operation = receipt["operations"][0]
        if prepare_operation["status"] != "applied":
            raw = self._gateway.prepare_render_job(
                plan["render"]["custom_name"],
                timeline_id=plan["target_timeline"]["timeline_id"],
                profile=plan["render"]["profile"],
                timeout_seconds=timeout,
                idempotency_key=f"{receipt_id}:prepare",
            )
            prepared_job = self._verify_prepared(plan, raw)
            prepare_operation["status"] = "applied"
            prepare_operation["result"] = {"job_id": prepared_job["job_id"]}
            receipt["job"] = prepared_job
            self._persist(path, receipt)
        job = receipt.get("job")
        if not isinstance(job, dict):
            raise TakeSequenceRenderError("Prepared render job evidence is missing.")

        start_operation = receipt["operations"][1]
        if start_operation["status"] == "pending":
            live = self._gateway.render_job_status(
                job["job_id"], timeout_seconds=timeout
            )
            output = self._verify_live_job(plan, job, live)
            status = live.get("status")
            if (
                live.get("rendering_in_progress") is not False
                or not isinstance(status, dict)
                or status.get("JobStatus") != "Ready"
            ):
                raise TakeSequenceRenderError(
                    "The exact sequence render job must be Ready before start."
                )
            if output["output"]["exists"] is True:
                raise TakeSequenceRenderError(
                    "The managed sequence render output already exists."
                )
            start_operation["status"] = "ready"
            self._persist(path, receipt)
        if start_operation["status"] != "applied":
            result = self._gateway.start_render_job(
                job["job_id"],
                timeout_seconds=timeout,
                idempotency_key=f"{receipt_id}:start",
            )
            if (
                result.get("job_id") != job["job_id"]
                or result.get("started") is not True
            ):
                raise TakeSequenceRenderError(
                    "Resolve did not confirm the exact sequence render start."
                )
            start_operation["status"] = "applied"
            start_operation["result"] = {
                "job_id": job["job_id"],
                "started": True,
            }
            receipt["status"] = "started"
            self._persist(path, receipt)
        return receipt

    def status(
        self,
        receipt_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Revalidate acceptance and verify the exact managed MP4 output."""
        identifier = _sha256(receipt_id, "receipt_id")
        timeout = _timeout(timeout_seconds)
        receipt = self._load(identifier)
        if receipt.get("status") != "started":
            raise TakeSequenceRenderError("Sequence render has not confirmed a start.")
        plan = receipt["plan"]
        report, review = self._approved_evidence(
            plan["inputs"]["qc_report_id"], timeout
        )
        if (
            _canonical_sha256(report) != plan["qc_report_sha256"]
            or _canonical_sha256(review) != plan["qc_review_sha256"]
        ):
            raise TakeSequenceRenderError(
                "Sequence QC evidence changed after render start."
            )
        job = receipt.get("job")
        if not isinstance(job, dict):
            raise TakeSequenceRenderError("Sequence render receipt has no job.")
        live = self._gateway.render_job_status(job["job_id"], timeout_seconds=timeout)
        output = self._verify_live_job(plan, job, live)
        live_status = live.get("status")
        complete = (
            isinstance(live_status, dict)
            and live_status.get("JobStatus") == "Complete"
            and output["validation"]["passed"] is True
        )
        result = {
            "receipt_id": identifier,
            "status": "complete" if complete else "in_progress",
            "target_timeline": plan["target_timeline"],
            "job": job,
            "live": live,
            "output": output,
        }
        validate_contract("take-sequence-render-status", result)
        return result

    def _approved_evidence(
        self, report_id: str, timeout: float
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        report = self._qc.get(report_id, timeout_seconds=timeout)
        review = self._qc.get_review(report_id, timeout_seconds=timeout)
        validate_contract("take-sequence-qc", report)
        validate_contract("take-sequence-qc-review", review)
        if review.get("decision") != "approve":
            raise TakeSequenceRenderError(
                "Sequence QC must have an explicit approve decision."
            )
        if review.get("report_sha256") != _canonical_sha256(report):
            raise TakeSequenceRenderError("Sequence QC review binding is invalid.")
        return report, review

    def _verify_prepared(self, plan: dict[str, Any], result: object) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise TakeSequenceRenderError("Render preparation returned no object.")
        profile = validate_render_profile(plan["render"]["profile"])
        job_id = result.get("job_id")
        try:
            if not isinstance(job_id, str):
                raise ValueError("job ID is not a string")
            validate_render_job_id(job_id)
        except ValueError as error:
            raise TakeSequenceRenderError(
                "Resolve returned an invalid render job ID."
            ) from error
        if (
            result.get("timeline_id") != plan["target_timeline"]["timeline_id"]
            or result.get("timeline_name") != plan["target_timeline"]["name"]
            or result.get("custom_name") != plan["render"]["custom_name"]
            or result.get("preset") != profile.name
            or result.get("width") != profile.width
            or result.get("height") != profile.height
            or result.get("format") != "MP4"
            or result.get("codec") != "H264"
            or result.get("started") is not False
            or Path(str(result.get("target_directory", ""))).resolve()
            != self._output_root.resolve()
        ):
            raise TakeSequenceRenderError(
                "Prepared render job does not match the accepted sequence policy."
            )
        resolve_preset = result.get("resolve_preset")
        if not isinstance(resolve_preset, str) or not resolve_preset:
            raise TakeSequenceRenderError("Prepared render preset identity is missing.")
        return {
            "job_id": job_id,
            "custom_name": plan["render"]["custom_name"],
            "profile": profile.name,
            "resolve_preset": resolve_preset,
            "output_filename": plan["render"]["output_filename"],
            "width": profile.width,
            "height": profile.height,
        }

    def _verify_live_job(
        self,
        plan: dict[str, Any],
        job: dict[str, Any],
        live: dict[str, Any],
    ) -> dict[str, Any]:
        discovered = live.get("job")
        valid = (
            isinstance(discovered, dict)
            and live.get("job_id") == job["job_id"]
            and discovered.get("JobId", job["job_id"]) == job["job_id"]
            and discovered.get("TimelineName") == plan["target_timeline"]["name"]
            and discovered.get("OutputFilename") == job["output_filename"]
            and Path(str(discovered.get("TargetDir", ""))).resolve()
            == self._output_root.resolve()
            and discovered.get("PresetName") == job["resolve_preset"]
            and discovered.get("FormatWidth") == job["width"]
            and discovered.get("FormatHeight") == job["height"]
            and discovered.get("VideoFormat") == "MP4"
            and discovered.get("VideoCodec") in {"H.264", "H264"}
        )
        if not valid:
            raise TakeSequenceRenderError(
                "Live render job no longer matches the accepted sequence plan."
            )
        return verify_render_output(live, expected_directory=self._output_root)

    def _load(self, receipt_id: str) -> dict[str, Any]:
        path = self._receipts_root / f"{receipt_id}.json"
        if not path.is_file():
            raise TakeSequenceRenderError("The sequence render receipt was not found.")
        receipt = read_json_object(path)
        validate_contract("take-sequence-render-result", receipt)
        if receipt.get("receipt_id") != receipt_id:
            raise TakeSequenceRenderError("Stored sequence render ID is invalid.")
        return receipt

    def _persist(self, path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("take-sequence-render-result", receipt)
        self._receipts_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, receipt)


def _render_name(custom_name: str, review_id: str) -> str:
    suffix = f"-{review_id[:12]}"
    return validate_render_name(f"{custom_name[: 128 - len(suffix)].rstrip()}{suffix}")


def _timeout(value: object) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or not 0 < float(value) <= 300
    ):
        raise TakeSequenceRenderError(
            "timeout_seconds must be greater than zero and no more than 300."
        )
    return float(value)


def _sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TakeSequenceRenderError(f"{name} must be a lowercase SHA-256 ID.")
    return value


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
