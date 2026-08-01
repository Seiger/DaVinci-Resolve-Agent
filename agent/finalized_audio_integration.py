"""Guarded M46 integration of validated dialogue audio into a timeline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from agent.audio_workflow import LIMITER_PRESET_NAME, AudioReportInspector
from agent.contracts import validate_contract
from agent.paths import (
    finalized_audio_integrations_directory,
    pause_compaction_finalizations_directory,
)
from transports.filesystem import atomic_write_json, read_json_object

INTEGRATION_VERSION = "1.0"


class FinalizedAudioIntegrationError(ValueError):
    """Raised when cleaned finalized audio cannot be integrated safely."""


class FinalizedAudioIntegrationGateway(Protocol):
    """Bounded Resolve operations required by the integration workflow."""

    def import_media(
        self,
        paths: list[str],
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...
    def ensure_timeline_tracks(
        self,
        timeline_id: str,
        video_track_count: int,
        audio_track_count: int,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def insert_clip(
        self,
        timeline_id: str,
        asset_id: str,
        source_start_frame: int,
        source_end_frame: int,
        position_frames: int,
        track_type: str,
        track_index: int,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def set_clip_enabled(
        self,
        timeline_id: str,
        timeline_item_id: str,
        enabled: bool,
        *,
        timeout_seconds: float,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def timeline_items(
        self,
        timeline_id: str,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]: ...


class AudioReportReader(Protocol):
    """Read one validated local audio report."""

    def get_report(self, report_id: str) -> dict[str, Any]: ...


class FinalizedAudioIntegrator:
    """Insert one validated processed WAV and silence only its source items."""

    def __init__(
        self,
        *,
        gateway: FinalizedAudioIntegrationGateway,
        extraction_status: Callable[..., dict[str, Any]],
        report_reader: AudioReportReader | None = None,
        finalizations_root: Path | None = None,
        receipts_root: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._extraction_status = extraction_status
        self._report_reader = (
            AudioReportInspector() if report_reader is None else report_reader
        )
        self._finalizations_root = (
            pause_compaction_finalizations_directory()
            if finalizations_root is None
            else finalizations_root
        )
        self._receipts_root = (
            finalized_audio_integrations_directory()
            if receipts_root is None
            else receipts_root
        )

    def apply(
        self,
        *,
        extraction_receipt_id: str,
        audio_report_id: str,
        confirm_apply: bool,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Apply one extraction/report pair with durable stepwise replay."""
        inputs = _validated_inputs(
            extraction_receipt_id,
            audio_report_id,
            confirm_apply,
            timeout_seconds,
        )
        receipt_id = _receipt_id(inputs)
        receipt_path = self._receipts_root / f"{receipt_id}.json"
        if receipt_path.is_file():
            receipt = self._load_receipt(receipt_id)
            if receipt["inputs"] != inputs:
                raise FinalizedAudioIntegrationError(
                    "Stored integration inputs do not match the request."
                )
            if receipt["status"] == "applied":
                return receipt
        else:
            receipt = self._prepare_receipt(inputs, receipt_id, timeout_seconds)
            self._persist(receipt_path, receipt)

        timeline_id = str(receipt["target"]["timeline_id"])
        timeout = float(timeout_seconds)
        operations = receipt["operations"]

        if operations[0]["status"] == "pending":
            report = self._report_reader.get_report(audio_report_id)
            result = self._gateway.import_media(
                [str(report["derived"]["path"])],
                timeout_seconds=timeout,
                idempotency_key=f"m46:{audio_report_id[:16]}:import",
            )
            items = result.get("items")
            if not isinstance(items, list) or len(items) != 1:
                raise FinalizedAudioIntegrationError(
                    "Resolve did not return exactly one imported audio asset."
                )
            asset_id = items[0].get("asset_id")
            if not isinstance(asset_id, str) or not asset_id:
                raise FinalizedAudioIntegrationError(
                    "Imported audio asset has no canonical asset_id."
                )
            _complete_operation(operations[0], result)
            self._persist(receipt_path, receipt)

        if operations[1]["status"] == "pending":
            result = self._gateway.ensure_timeline_tracks(
                timeline_id,
                int(receipt["target"]["video_track_count"]),
                2,
                timeout_seconds=timeout,
                idempotency_key=f"{receipt_id}:ensure-a2",
            )
            _complete_operation(operations[1], result)
            self._persist(receipt_path, receipt)

        if operations[2]["status"] == "pending":
            import_result = operations[0]["result"]
            asset_id = str(import_result["items"][0]["asset_id"])
            duration_frames = int(receipt["target"]["duration_frames"])
            result = self._gateway.insert_clip(
                timeline_id,
                asset_id,
                0,
                duration_frames,
                0,
                "audio",
                2,
                timeout_seconds=timeout,
                idempotency_key=f"{receipt_id}:insert-a2",
            )
            item = result.get("item")
            if not isinstance(item, dict) or not _insert_matches(
                item,
                int(receipt["target"]["timeline_start_frame"]),
                duration_frames,
            ):
                raise FinalizedAudioIntegrationError(
                    "Inserted audio readback does not match A2 full-timeline placement."
                )
            _complete_operation(operations[2], result)
            self._persist(receipt_path, receipt)

        source_item_ids = receipt["source_audio_item_ids"]
        for index, item_id in enumerate(source_item_ids, start=3):
            if operations[index]["status"] != "pending":
                continue
            result = self._gateway.set_clip_enabled(
                timeline_id,
                str(item_id),
                False,
                timeout_seconds=timeout,
                idempotency_key=f"{receipt_id}:disable:{item_id}",
            )
            if (
                result.get("timeline_item_id") != item_id
                or result.get("enabled") is not False
            ):
                raise FinalizedAudioIntegrationError(
                    "Resolve did not confirm a source A1 item as disabled."
                )
            _complete_operation(operations[index], result)
            self._persist(receipt_path, receipt)

        video_start = 3 + len(source_item_ids)
        source_video_item_ids = receipt["source_video_item_ids"]
        for offset, item_id in enumerate(source_video_item_ids):
            operation = operations[video_start + offset]
            if operation["status"] != "pending":
                continue
            result = self._gateway.set_clip_enabled(
                timeline_id,
                str(item_id),
                True,
                timeout_seconds=timeout,
                idempotency_key=f"{receipt_id}:enable:{item_id}",
            )
            if (
                result.get("timeline_item_id") != item_id
                or result.get("enabled") is not True
            ):
                raise FinalizedAudioIntegrationError(
                    "Resolve did not confirm a linked source video item as enabled."
                )
            _complete_operation(operation, result)
            self._persist(receipt_path, receipt)

        readback = self._gateway.timeline_items(
            timeline_id,
            timeout_seconds=timeout,
        )
        inserted_id = operations[2]["result"]["item"]["timeline_item_id"]
        if not _readback_contains(
            readback,
            inserted_id,
            source_item_ids,
            source_video_item_ids,
        ):
            raise FinalizedAudioIntegrationError(
                "Final timeline readback does not contain the expected audio items."
            )
        receipt["readback"] = readback
        receipt["status"] = "applied"
        self._persist(receipt_path, receipt)
        return receipt

    def _prepare_receipt(
        self,
        inputs: dict[str, Any],
        receipt_id: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        extraction = self._extraction_status(
            inputs["extraction_receipt_id"],
            timeout_seconds=timeout_seconds,
        )
        report = self._report_reader.get_report(inputs["audio_report_id"])
        target = _validated_target(extraction, report)
        finalization_id = extraction["receipt"]["inputs"]["finalization_receipt_id"]
        finalization = read_json_object(
            self._finalizations_root / f"{finalization_id}.json"
        )
        if finalization.get("status") != "applied":
            raise FinalizedAudioIntegrationError(
                "The source finalization receipt is not applied."
            )
        readback_items = finalization.get("readback", {}).get("items")
        if not isinstance(readback_items, list):
            raise FinalizedAudioIntegrationError(
                "The source finalization has no canonical item readback."
            )
        source_audio = [
            item
            for item in readback_items
            if item.get("track_type") == "audio" and item.get("track_index") == 1
        ]
        source_ids = [item.get("timeline_item_id") for item in source_audio]
        if not source_ids or not all(
            isinstance(item_id, str) for item_id in source_ids
        ):
            raise FinalizedAudioIntegrationError(
                "The source finalization has no addressable A1 items."
            )
        link_groups = finalization.get("link_groups")
        if not isinstance(link_groups, list):
            raise FinalizedAudioIntegrationError(
                "The source finalization has no canonical link groups."
            )
        source_id_set = set(source_ids)
        source_video_ids: list[str] = []
        for group in link_groups:
            if not isinstance(group, list) or len(group) != 2:
                continue
            audio_ids = source_id_set.intersection(group)
            if len(audio_ids) != 1:
                continue
            video_ids = [item_id for item_id in group if item_id not in audio_ids]
            if len(video_ids) == 1 and isinstance(video_ids[0], str):
                source_video_ids.append(video_ids[0])
        if len(source_video_ids) != len(source_ids):
            raise FinalizedAudioIntegrationError(
                "The source A1 items do not have exact linked video peers."
            )
        video_track_count = max(
            (
                int(item["track_index"])
                for item in readback_items
                if item.get("track_type") == "video"
            ),
            default=1,
        )
        operations = [
            _pending("import_processed_audio"),
            _pending("ensure_audio_track_2"),
            _pending("insert_processed_audio"),
            *[_pending("disable_source_audio") for _ in source_ids],
            *[_pending("ensure_source_video_enabled") for _ in source_video_ids],
        ]
        return {
            "audio_integration_version": INTEGRATION_VERSION,
            "receipt_id": receipt_id,
            "status": "in_progress",
            "inputs": inputs,
            "target": {**target, "video_track_count": video_track_count},
            "source_audio_item_ids": source_ids,
            "source_video_item_ids": source_video_ids,
            "operations": operations,
            "readback": None,
        }

    def _load_receipt(self, receipt_id: str) -> dict[str, Any]:
        receipt = read_json_object(self._receipts_root / f"{receipt_id}.json")
        validate_contract("finalized-audio-integration", receipt)
        return receipt

    @staticmethod
    def _persist(path: Path, receipt: dict[str, Any]) -> None:
        validate_contract("finalized-audio-integration", receipt)
        atomic_write_json(path, receipt)


def _validated_target(
    extraction: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    validation = extraction.get("output", {}).get("validation", {})
    if validation.get("passed") is not True:
        raise FinalizedAudioIntegrationError(
            "The finalized audio extraction has not passed validation."
        )
    if (
        report.get("status") != "completed"
        or report.get("preset", {}).get("name") != LIMITER_PRESET_NAME
        or report.get("validation", {}).get("target_met") is not True
    ):
        raise FinalizedAudioIntegrationError(
            "The audio report must be a completed validated limiter-v2 report."
        )
    derived_path = Path(str(report["derived"]["path"])).resolve()
    if not derived_path.is_file():
        raise FinalizedAudioIntegrationError(
            "The validated processed WAV no longer exists."
        )
    output = extraction["output"]["output"]
    if (
        Path(str(report["source"]["path"])).resolve()
        != Path(str(output["path"])).resolve()
    ):
        raise FinalizedAudioIntegrationError(
            "The audio report source does not match the extracted WAV."
        )
    live_job = extraction.get("live", {}).get("job", {})
    try:
        mark_in = int(live_job["MarkIn"])
        mark_out = int(live_job["MarkOut"])
        frame_rate = float(live_job["FrameRate"])
    except (KeyError, TypeError, ValueError) as error:
        raise FinalizedAudioIntegrationError(
            "The extraction job has invalid timeline frame metadata."
        ) from error
    duration_frames = mark_out - mark_in + 1
    duration_ms = int(report["before"]["duration_ms"])
    expected_frames = round(duration_ms * frame_rate / 1000)
    if duration_frames < 1 or abs(expected_frames - duration_frames) > 1:
        raise FinalizedAudioIntegrationError(
            "The processed WAV duration does not match the extraction range."
        )
    receipt_target = extraction.get("receipt", {}).get("target", {})
    timeline_id = receipt_target.get("timeline_id")
    timeline_name = receipt_target.get("timeline_name")
    if not isinstance(timeline_id, str) or not isinstance(timeline_name, str):
        raise FinalizedAudioIntegrationError(
            "The extraction receipt has no canonical timeline target."
        )
    return {
        "timeline_id": timeline_id,
        "timeline_name": timeline_name,
        "timeline_start_frame": mark_in,
        "duration_frames": duration_frames,
        "frame_rate": frame_rate,
    }


def _validated_inputs(
    extraction_receipt_id: str,
    audio_report_id: str,
    confirm_apply: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    for field, value in (
        ("extraction_receipt_id", extraction_receipt_id),
        ("audio_report_id", audio_report_id),
    ):
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise FinalizedAudioIntegrationError(
                f"{field} must be exactly 64 lowercase hexadecimal characters."
            )
    if confirm_apply is not True:
        raise FinalizedAudioIntegrationError("confirm_apply must be true.")
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not 0 < timeout_seconds <= 300
    ):
        raise FinalizedAudioIntegrationError(
            "timeout_seconds must be greater than zero and no more than 300."
        )
    return {
        "extraction_receipt_id": extraction_receipt_id,
        "audio_report_id": audio_report_id,
    }


def _receipt_id(inputs: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _pending(operation: str) -> dict[str, Any]:
    return {"operation": operation, "status": "pending", "result": None}


def _complete_operation(operation: dict[str, Any], result: dict[str, Any]) -> None:
    operation["status"] = "applied"
    operation["result"] = result


def _insert_matches(item: dict[str, Any], start: int, duration: int) -> bool:
    return (
        item.get("track_type") == "audio"
        and item.get("track_index") == 2
        and item.get("timeline_start_frame") == start
        and item.get("timeline_end_frame") == start + duration
    )


def _readback_contains(
    readback: dict[str, Any],
    inserted_id: str,
    source_ids: list[str],
    source_video_ids: list[str],
) -> bool:
    items = readback.get("items")
    if not isinstance(items, list):
        return False
    indexed = {item.get("timeline_item_id"): item for item in items}
    inserted = indexed.get(inserted_id)
    return (
        isinstance(inserted, dict)
        and inserted.get("track_type") == "audio"
        and inserted.get("track_index") == 2
        and all(item_id in indexed for item_id in source_ids)
        and all(item_id in indexed for item_id in source_video_ids)
    )
