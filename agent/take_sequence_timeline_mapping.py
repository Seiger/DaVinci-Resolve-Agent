"""M55.3 read-only live timeline frame mapping for an assembly preview."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Protocol

from agent.contracts import validate_contract

MAPPING_VERSION = "1.0"
MAX_FRAME_VALUE = 2_147_483_647


class TakeSequenceTimelineMappingError(ValueError):
    """Raised when a safe live timeline mapping cannot be calculated."""


class TakeSequenceAssemblyReader(Protocol):
    """Read-only M55.2 assembly boundary."""

    def preview(
        self,
        *,
        binding_id: str,
        assembly_name: str,
    ) -> dict[str, Any]: ...


class TimelineMetadataReader(Protocol):
    """Existing documented provider metadata boundary."""

    def editing_metadata(
        self,
        timeline_id: str,
        asset_ids: list[str],
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...


class TakeSequenceTimelineMappingWorkflow:
    """Map approved source seconds to exact frames without modifying Resolve."""

    def __init__(
        self,
        assembly: TakeSequenceAssemblyReader,
        timeline_metadata: TimelineMetadataReader,
    ) -> None:
        self._assembly = assembly
        self._timeline_metadata = timeline_metadata

    def preview(
        self,
        *,
        binding_id: str,
        assembly_name: str,
        timeline_id: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return a deterministic frame plan bound to live timeline settings."""
        identifier = _bounded_text(timeline_id, "timeline_id")
        binding_identifier = _sha256(binding_id, "binding_id")
        assembly = self._assembly.preview(
            binding_id=binding_identifier,
            assembly_name=assembly_name,
        )
        metadata = self._timeline_metadata.editing_metadata(
            identifier,
            [],
            timeout_seconds=timeout_seconds,
        )
        timeline = _timeline(metadata, identifier)
        entries = assembly.get("entries")
        if not isinstance(entries, list) or not entries:
            raise TakeSequenceTimelineMappingError(
                "Take-sequence assembly preview is incomplete."
            )
        assembly_plan_id = _sha256(assembly.get("plan_id"), "assembly plan ID")
        if assembly.get("binding_id") != binding_identifier:
            raise TakeSequenceTimelineMappingError(
                "Assembly preview targets a different source binding."
            )

        placements: list[dict[str, Any]] = []
        cursor = 0
        for entry in entries:
            placement = _placement(entry, timeline["frame_rate"], cursor)
            placements.append(placement)
            cursor = placement["timeline_end_position_frames"]
        if cursor > MAX_FRAME_VALUE:
            raise TakeSequenceTimelineMappingError(
                "Mapped assembly exceeds the supported timeline frame range."
            )

        expected_seconds = _positive_number(
            assembly.get("total_duration_seconds"), "assembly duration"
        )
        mapped_seconds = cursor / timeline["frame_rate"]
        drift_frames = abs(mapped_seconds - expected_seconds) * timeline["frame_rate"]
        warning_values = assembly.get("warnings")
        if (
            not isinstance(warning_values, list)
            or len(warning_values) > 2
            or not all(
                isinstance(warning, str) and warning
                for warning in warning_values
            )
        ):
            raise TakeSequenceTimelineMappingError(
                "Assembly preview warnings are invalid."
            )
        warnings = list(warning_values)
        if drift_frames > 1.0 + 1e-9:
            warnings.append(
                "Frame rounding differs from the seconds preview by more than one "
                "target frame."
            )
        payload = {
            "mapping_version": MAPPING_VERSION,
            "status": "preview",
            "assembly_plan_id": assembly_plan_id,
            "binding_id": binding_identifier,
            "target_timeline": timeline,
            "placements": placements,
            "placement_count": len(placements),
            "output_duration_frames": cursor,
            "output_duration_seconds": round(mapped_seconds, 6),
            "warnings": warnings,
            "live_metadata_verified": True,
            "paths_redacted": True,
            "timeline_modified": False,
            "apply_supported": False,
        }
        result = {"plan_id": _canonical_sha256(payload), **payload}
        validate_contract("take-sequence-timeline-preview", result)
        return result


def _timeline(metadata: object, timeline_id: str) -> dict[str, Any]:
    value = metadata.get("timeline") if isinstance(metadata, dict) else None
    if not isinstance(value, dict) or value.get("timeline_id") != timeline_id:
        raise TakeSequenceTimelineMappingError(
            "Live target timeline metadata is invalid."
        )
    name = value.get("name")
    frame_rate = _positive_number(value.get("frame_rate"), "timeline frame rate")
    width = _positive_integer(value.get("resolution_width"), "timeline width")
    height = _positive_integer(value.get("resolution_height"), "timeline height")
    video_tracks = _non_negative_integer(
        value.get("video_track_count"), "video track count"
    )
    audio_tracks = _non_negative_integer(
        value.get("audio_track_count"), "audio track count"
    )
    if not isinstance(name, str) or not 1 <= len(name) <= 128:
        raise TakeSequenceTimelineMappingError("Timeline name is invalid.")
    assets = metadata.get("assets") if isinstance(metadata, dict) else None
    if assets != []:
        raise TakeSequenceTimelineMappingError(
            "Timeline-only metadata unexpectedly returned media assets."
        )
    return {
        "timeline_id": timeline_id,
        "name": name,
        "frame_rate": frame_rate,
        "resolution_width": width,
        "resolution_height": height,
        "video_track_count": video_tracks,
        "audio_track_count": audio_tracks,
    }


def _placement(
    entry: object,
    timeline_rate: float,
    position_frames: int,
) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise TakeSequenceTimelineMappingError("Assembly entry is invalid.")
    source_range = entry.get("source_range")
    video = entry.get("video")
    if not isinstance(source_range, dict) or not isinstance(video, dict):
        raise TakeSequenceTimelineMappingError(
            "Assembly source range or video metadata is invalid."
        )
    start_seconds = _non_negative_number(
        source_range.get("start_seconds"), "source start"
    )
    end_seconds = _positive_number(source_range.get("end_seconds"), "source end")
    source_rate = _positive_number(video.get("frame_rate"), "source frame rate")
    if end_seconds <= start_seconds:
        raise TakeSequenceTimelineMappingError("Assembly source range is empty.")
    source_start = _seconds_to_frames(start_seconds, source_rate)
    source_end_exclusive = _seconds_to_frames(end_seconds, source_rate)
    if source_end_exclusive <= source_start:
        raise TakeSequenceTimelineMappingError(
            "Assembly source range contains less than one source frame."
        )
    source_duration = source_end_exclusive - source_start
    timeline_duration = max(
        1,
        _round_half_up(source_duration * timeline_rate / source_rate),
    )
    timeline_end = position_frames + timeline_duration
    if source_end_exclusive - 1 > MAX_FRAME_VALUE or timeline_end > MAX_FRAME_VALUE:
        raise TakeSequenceTimelineMappingError(
            "Mapped placement exceeds the supported frame range."
        )
    return {
        "order": entry["order"],
        "selected_candidate_id": entry["selected_candidate_id"],
        "display_name": entry["display_name"],
        "fingerprint": entry["fingerprint"],
        "source_frame_rate": source_rate,
        "source_start_frame": source_start,
        "source_end_frame": source_end_exclusive - 1,
        "source_duration_frames": source_duration,
        "position_frames": position_frames,
        "timeline_duration_frames": timeline_duration,
        "timeline_end_position_frames": timeline_end,
    }


def _seconds_to_frames(seconds: float, frame_rate: float) -> int:
    return _round_half_up(seconds * frame_rate)


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def _positive_number(value: object, name: str) -> float:
    number = _non_negative_number(value, name)
    if number <= 0:
        raise TakeSequenceTimelineMappingError(f"{name} must be positive.")
    return number


def _non_negative_number(value: object, name: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise TakeSequenceTimelineMappingError(f"{name} is invalid.")
    return float(value)


def _positive_integer(value: object, name: str) -> int:
    number = _non_negative_integer(value, name)
    if number <= 0:
        raise TakeSequenceTimelineMappingError(f"{name} must be positive.")
    return number


def _non_negative_integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TakeSequenceTimelineMappingError(f"{name} is invalid.")
    return value


def _bounded_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise TakeSequenceTimelineMappingError(
            f"{name} must contain 1 to 128 characters."
        )
    return value


def _sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TakeSequenceTimelineMappingError(
            f"{name} must be a lowercase SHA-256 ID."
        )
    return value


def _canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
