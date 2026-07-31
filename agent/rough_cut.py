"""Provider-neutral M5 rough-cut draft planning."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.audio_analysis import (
    detect_pauses,
    estimate_sync_offset,
    read_pcm_wav_envelope,
)
from agent.contracts import validate_contract
from agent.paths import plans_directory
from transports.filesystem import atomic_write_json, read_json_object

PLAN_VERSION = "1.0"
APPROVAL_VERSION = "1.0"
PLAN_ID_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class RoughCutPlanningError(ValueError):
    """Raised when a safe rough-cut draft cannot be produced."""


class RoughCutPlanner:
    """Analyze screen/webcam audio and persist a review-only edit plan."""

    def __init__(self, plans_root: Path | None = None) -> None:
        self._plans_root = (
            plans_directory()
            if plans_root is None
            else plans_root
        )

    def create_plan(
        self,
        *,
        screen_file: str,
        webcam_file: str,
        screen_audio_file: str,
        webcam_audio_file: str,
        speech_audio_file: str,
        timeline_name: str,
        max_sync_offset_ms: int = 30_000,
        pause_threshold_dbfs: float = -40.0,
        min_pause_duration_ms: int = 700,
        preserve_context_ms: int = 120,
    ) -> dict[str, Any]:
        """Create and persist a deterministic pending-review plan."""
        if not timeline_name.strip() or len(timeline_name) > 128:
            raise RoughCutPlanningError(
                "timeline_name must contain 1 to 128 characters."
            )
        if preserve_context_ms < 0:
            raise RoughCutPlanningError(
                "preserve_context_ms must be non-negative."
            )

        inputs = {
            "screen_file": str(Path(screen_file).resolve()),
            "webcam_file": str(Path(webcam_file).resolve()),
            "screen_audio_file": str(Path(screen_audio_file).resolve()),
            "webcam_audio_file": str(Path(webcam_audio_file).resolve()),
            "speech_audio_file": str(Path(speech_audio_file).resolve()),
        }
        screen_envelope = read_pcm_wav_envelope(
            Path(inputs["screen_audio_file"])
        )
        webcam_envelope = read_pcm_wav_envelope(
            Path(inputs["webcam_audio_file"])
        )
        speech_envelope = read_pcm_wav_envelope(
            Path(inputs["speech_audio_file"])
        )
        synchronization = estimate_sync_offset(
            screen_envelope,
            webcam_envelope,
            max_offset_ms=max_sync_offset_ms,
        )
        detected_pauses = detect_pauses(
            speech_envelope,
            threshold_dbfs=pause_threshold_dbfs,
            min_duration_ms=min_pause_duration_ms,
        )
        proposed_cuts = _proposed_cuts(
            detected_pauses,
            preserve_context_ms,
        )
        webcam_offset = int(synchronization["webcam_offset_ms"])
        screen_start_ms = max(0, -webcam_offset)
        webcam_start_ms = max(0, webcam_offset)

        plan_basis = {
            "plan_version": PLAN_VERSION,
            "inputs": inputs,
            "timeline_name": timeline_name,
            "synchronization": synchronization,
            "pause_threshold_dbfs": pause_threshold_dbfs,
            "min_pause_duration_ms": min_pause_duration_ms,
            "preserve_context_ms": preserve_context_ms,
            "proposed_cuts": proposed_cuts,
        }
        plan_id = hashlib.sha256(
            json.dumps(
                plan_basis,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        existing_path = self._plans_root / f"{plan_id}.json"
        if existing_path.is_file():
            existing = read_json_object(existing_path)
            validate_contract("rough-cut-plan", existing)
            return existing

        warnings = [
            "Draft only: user review is required before any edit is applied.",
            (
                "M5 does not apply synchronized multi-track placement or "
                "pause-removal operations."
            ),
        ]
        if {
            inputs["screen_file"],
            inputs["webcam_file"],
        } != {
            inputs["screen_audio_file"],
            inputs["webcam_audio_file"],
        }:
            warnings.append(
                "Synchronization used separate PCM WAV analysis tracks."
            )
        if float(synchronization["correlation_score"]) < 0.5:
            warnings.append(
                "Audio correlation confidence is low; verify sync manually."
            )

        plan: dict[str, Any] = {
            "plan_version": PLAN_VERSION,
            "plan_id": plan_id,
            "created_at": _utc_now(),
            "status": "pending_review",
            "inputs": inputs,
            "timeline": {
                "name": timeline_name,
                "layout": [
                    {
                        "role": "screen",
                        "track_type": "video",
                        "track_index": 1,
                        "start_ms": screen_start_ms,
                    },
                    {
                        "role": "webcam",
                        "track_type": "video",
                        "track_index": 2,
                        "start_ms": webcam_start_ms,
                    },
                ],
            },
            "synchronization": synchronization,
            "pause_analysis": {
                "source_role": "speech_audio",
                "threshold_dbfs": pause_threshold_dbfs,
                "min_duration_ms": min_pause_duration_ms,
                "preserve_context_ms": preserve_context_ms,
                "detected_pauses": detected_pauses,
                "proposed_cuts": proposed_cuts,
            },
            "proposed_operations": [
                {
                    "operation": "import_media",
                    "details": {
                        "paths": [
                            inputs["screen_file"],
                            inputs["webcam_file"],
                        ]
                    },
                },
                {
                    "operation": "create_timeline",
                    "details": {"name": timeline_name},
                },
                {
                    "operation": "place_media",
                    "details": {
                        "role": "screen",
                        "track_type": "video",
                        "track_index": 1,
                        "start_ms": screen_start_ms,
                    },
                },
                {
                    "operation": "place_media",
                    "details": {
                        "role": "webcam",
                        "track_type": "video",
                        "track_index": 2,
                        "start_ms": webcam_start_ms,
                    },
                },
                {
                    "operation": "remove_pauses",
                    "details": {"ranges": proposed_cuts},
                },
            ],
            "required_capabilities": [
                "media.import",
                "timeline.create",
                "clip.insert",
                "clip.move",
                "clip.trim",
                "clip.delete",
            ],
            "review": {
                "required": True,
                "approved": False,
                "apply_supported": False,
            },
            "warnings": warnings,
        }
        validate_contract("rough-cut-plan", plan)
        self._plans_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(existing_path, plan)
        return plan


class RoughCutReviewer:
    """Persist explicit review approval without changing the draft plan."""

    def __init__(self, plans_root: Path | None = None) -> None:
        self._plans_root = (
            plans_directory()
            if plans_root is None
            else plans_root
        )

    def approve(
        self,
        plan_id: str,
        *,
        confirm_review: bool,
    ) -> dict[str, Any]:
        """Approve one canonical draft while keeping application unsupported."""
        if not PLAN_ID_PATTERN.fullmatch(plan_id):
            raise RoughCutPlanningError(
                "plan_id must be exactly 64 lowercase hexadecimal characters."
            )
        if confirm_review is not True:
            raise RoughCutPlanningError("confirm_review must be true.")

        plan_path = self._plans_root / f"{plan_id}.json"
        if not plan_path.is_file():
            raise RoughCutPlanningError(
                f"Rough-cut plan was not found: {plan_id}"
            )
        plan = read_json_object(plan_path)
        validate_contract("rough-cut-plan", plan)
        if plan.get("plan_id") != plan_id:
            raise RoughCutPlanningError(
                "Stored rough-cut plan_id does not match its filename."
            )
        plan_sha256 = _canonical_sha256(plan)

        approval_path = self._plans_root / f"{plan_id}.approval.json"
        if approval_path.is_file():
            existing = read_json_object(approval_path)
            validate_contract("rough-cut-approval", existing)
            if (
                existing.get("plan_id") != plan_id
                or existing.get("plan_sha256") != plan_sha256
            ):
                raise RoughCutPlanningError(
                    "Stored approval does not match the current draft plan."
                )
            return existing

        approval: dict[str, Any] = {
            "approval_version": APPROVAL_VERSION,
            "plan_id": plan_id,
            "plan_sha256": plan_sha256,
            "approved_at": _utc_now(),
            "status": "approved",
            "confirm_review": True,
            "apply_supported": False,
        }
        validate_contract("rough-cut-approval", approval)
        self._plans_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(approval_path, approval)
        return approval


def _canonical_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _proposed_cuts(
    pauses: list[dict[str, int | float]],
    preserve_context_ms: int,
) -> list[dict[str, int]]:
    cuts: list[dict[str, int]] = []
    for pause in pauses:
        start_ms = int(pause["start_ms"]) + preserve_context_ms
        end_ms = int(pause["end_ms"]) - preserve_context_ms
        if end_ms <= start_ms:
            continue
        cuts.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": end_ms - start_ms,
            }
        )
    return cuts


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
