"""M55.7 structural quality gate for an applied take sequence."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import (
    take_sequence_qc_reports_directory,
    take_sequence_qc_reviews_directory,
)
from transports.filesystem import atomic_write_json, read_json_object

QC_VERSION = "1.0"
REVIEW_VERSION = "1.0"
UNVERIFIED_AREAS = [
    "dialogue_audio_processing",
    "subtitle_content_and_alignment",
    "color_treatment",
    "visual_and_editorial_quality",
]


class TakeSequenceQcError(ValueError):
    """Raised when sequence QC or review cannot be proven safely."""


class TimelineApplyReceiptReader(Protocol):
    def get(
        self,
        receipt_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...


class TakeSequenceQcWorkflow:
    """Verify exact V1/A1 structure and record an immutable human decision."""

    def __init__(
        self,
        applications: TimelineApplyReceiptReader,
        *,
        reports_root: Path | None = None,
        reviews_root: Path | None = None,
    ) -> None:
        self._applications = applications
        self._reports_root = reports_root or take_sequence_qc_reports_directory()
        self._reviews_root = reviews_root or take_sequence_qc_reviews_directory()

    def inspect(
        self,
        timeline_apply_receipt_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Create a deterministic report after fresh M55.6 live readback."""
        receipt_id = _sha256(timeline_apply_receipt_id, "timeline_apply_receipt_id")
        receipt = self._applications.get(
            receipt_id,
            timeout_seconds=_timeout(timeout_seconds),
        )
        report = _build_report(receipt_id, receipt)
        self._reports_root.mkdir(parents=True, exist_ok=True)
        path = self._reports_root / f"{report['report_id']}.json"
        if path.is_file():
            existing = read_json_object(path)
            validate_contract("take-sequence-qc", existing)
            if existing != report:
                raise TakeSequenceQcError(
                    "Stored sequence QC report does not match current evidence."
                )
            return existing
        atomic_write_json(path, report)
        return report

    def get(
        self,
        report_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return a stored report only when fresh live evidence still matches."""
        identifier = _sha256(report_id, "report_id")
        path = self._reports_root / f"{identifier}.json"
        if not path.is_file():
            raise TakeSequenceQcError("The sequence QC report was not found.")
        stored = read_json_object(path)
        validate_contract("take-sequence-qc", stored)
        if stored.get("report_id") != identifier:
            raise TakeSequenceQcError("Stored sequence QC report ID is invalid.")
        current = self.inspect(
            stored["timeline_apply_receipt_id"],
            timeout_seconds=timeout_seconds,
        )
        if current != stored:
            raise TakeSequenceQcError(
                "Sequence QC evidence changed after the report was created."
            )
        return stored

    def review(
        self,
        *,
        report_id: str,
        decision: str,
        note: str = "",
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Persist one immutable approve/reject decision without editing Resolve."""
        report = self.get(report_id, timeout_seconds=timeout_seconds)
        normalized_decision = _decision(decision)
        normalized_note = _note(note)
        payload = {
            "review_version": REVIEW_VERSION,
            "report_id": report["report_id"],
            "report_sha256": _canonical_sha256(report),
            "decision": normalized_decision,
            "note": normalized_note,
            "timeline_modified": False,
        }
        result = {**payload, "review_id": _canonical_sha256(payload)}
        validate_contract("take-sequence-qc-review", result)
        self._reviews_root.mkdir(parents=True, exist_ok=True)
        path = self._reviews_root / f"{report['report_id']}.json"
        if path.is_file():
            existing = read_json_object(path)
            validate_contract("take-sequence-qc-review", existing)
            if existing != result:
                raise TakeSequenceQcError(
                    "This sequence QC report already has a different review."
                )
            return existing
        atomic_write_json(path, result)
        return result

    def get_review(
        self,
        report_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return one review after revalidating its report and live timeline."""
        report = self.get(report_id, timeout_seconds=timeout_seconds)
        path = self._reviews_root / f"{report['report_id']}.json"
        if not path.is_file():
            raise TakeSequenceQcError("The sequence QC report has not been reviewed.")
        review = read_json_object(path)
        validate_contract("take-sequence-qc-review", review)
        payload = dict(review)
        review_id = payload.pop("review_id", None)
        if (
            review.get("report_id") != report["report_id"]
            or review.get("report_sha256") != _canonical_sha256(report)
            or not isinstance(review_id, str)
            or _canonical_sha256(payload) != review_id
        ):
            raise TakeSequenceQcError("Stored sequence QC review is invalid.")
        return review


def _build_report(receipt_id: str, receipt: object) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise TakeSequenceQcError("Timeline application receipt is invalid.")
    validate_contract("take-sequence-timeline-apply-result", receipt)
    if receipt.get("receipt_id") != receipt_id or receipt.get("status") != "applied":
        raise TakeSequenceQcError("A completed M55.6 timeline receipt is required.")
    if receipt.get("source_unchanged") is not True:
        raise TakeSequenceQcError("M55.6 source timeline is not proven unchanged.")
    plan = receipt.get("plan")
    target = receipt.get("target_timeline")
    inserted = receipt.get("inserted_items")
    if (
        not isinstance(plan, dict)
        or not isinstance(target, dict)
        or not isinstance(inserted, list)
    ):
        raise TakeSequenceQcError("Timeline application evidence is incomplete.")
    placements = plan.get("placements")
    if not isinstance(placements, list) or not placements:
        raise TakeSequenceQcError("Timeline application placements are invalid.")

    video = sorted(
        (item for item in inserted if item.get("track_type") == "video"),
        key=lambda item: item.get("timeline_start_frame", -1),
    )
    audio = sorted(
        (item for item in inserted if item.get("track_type") == "audio"),
        key=lambda item: item.get("timeline_start_frame", -1),
    )
    expected_audio = [
        placement for placement in placements if placement.get("has_audio") is True
    ]
    if len(video) != len(placements) or len(audio) != len(expected_audio):
        raise TakeSequenceQcError(
            "Inserted V1/A1 counts do not match the reviewed plan."
        )
    origins: set[int] = set()
    for placement, item in zip(placements, video, strict=True):
        _verify_item(placement, item)
        origins.add(item["timeline_start_frame"] - placement["position_frames"])
    for placement, item in zip(expected_audio, audio, strict=True):
        _verify_item(placement, item)
        origins.add(item["timeline_start_frame"] - placement["position_frames"])
    if len(origins) != 1:
        raise TakeSequenceQcError(
            "Inserted V1/A1 items do not share one timeline origin."
        )
    gaps = sum(
        left["timeline_end_frame"] != right["timeline_start_frame"]
        for left, right in zip(video, video[1:], strict=False)
    )
    if gaps:
        raise TakeSequenceQcError("The reviewed video sequence is not contiguous.")

    checks = [
        {"check": "application_applied", "status": "pass", "evidence": 1},
        {"check": "source_timeline_unchanged", "status": "pass", "evidence": 1},
        {"check": "video_sequence_exact", "status": "pass", "evidence": len(video)},
        {"check": "audio_sequence_exact", "status": "pass", "evidence": len(audio)},
        {"check": "video_sequence_contiguous", "status": "pass", "evidence": gaps},
    ]
    payload = {
        "qc_version": QC_VERSION,
        "timeline_apply_receipt_id": receipt_id,
        "timeline_apply_sha256": _canonical_sha256(receipt),
        "status": "ready_for_review",
        "target_timeline": {
            "timeline_id": _text(target.get("timeline_id"), "timeline ID"),
            "name": _text(target.get("name"), "timeline name"),
        },
        "checks": checks,
        "summary": {
            "placement_count": len(placements),
            "video_item_count": len(video),
            "audio_item_count": len(audio),
            "gap_count": gaps,
        },
        "unverified_areas": UNVERIFIED_AREAS,
        "manual_review_required": True,
        "timeline_modified": False,
        "paths_redacted": True,
    }
    result = {**payload, "report_id": _canonical_sha256(payload)}
    validate_contract("take-sequence-qc", result)
    return result


def _verify_item(placement: dict[str, Any], item: dict[str, Any]) -> None:
    duration = placement.get("timeline_end_position_frames", 0) - placement.get(
        "position_frames", 0
    )
    if (
        duration <= 0
        or item.get("track_index") != 1
        or item.get("timeline_end_frame", 0) - item.get("timeline_start_frame", 0)
        != duration
        or item.get("source_start_frame") != placement.get("source_start_frame")
        or not placement.get("source_start_frame", -1)
        < item.get("source_end_frame", -1)
        <= placement.get("source_end_frame", -1)
    ):
        raise TakeSequenceQcError(
            "Inserted item does not match its reviewed placement."
        )


def _decision(value: object) -> str:
    if value not in {"approve", "reject"}:
        raise TakeSequenceQcError("decision must be approve or reject.")
    return str(value)


def _note(value: object) -> str:
    if not isinstance(value, str) or len(value) > 1000:
        raise TakeSequenceQcError("note must contain no more than 1000 characters.")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise TakeSequenceQcError(f"{name} is invalid.")
    return value


def _timeout(value: object) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or not 0 < float(value) <= 300
    ):
        raise TakeSequenceQcError(
            "timeout_seconds must be greater than zero and no more than 300."
        )
    return float(value)


def _sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TakeSequenceQcError(f"{name} must be a lowercase SHA-256 ID.")
    return value


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
