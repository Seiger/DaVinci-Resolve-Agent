"""M55.2 read-only assembly preview for bound approved take sequences."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Protocol

import av

from agent.contracts import validate_contract

ASSEMBLY_VERSION = "1.0"
SOURCE_DURATION_TOLERANCE_SECONDS = 0.05


class TakeSequenceAssemblyError(ValueError):
    """Raised when a safe assembly preview cannot be calculated."""


class TakeSequenceBindingReader(Protocol):
    """Read-only public and private M55.1 binding boundary."""

    def get(self, binding_id: str) -> dict[str, Any]: ...

    def resolve_sources(self, binding_id: str) -> list[dict[str, Any]]: ...


class MediaMetadataReader(Protocol):
    """Read local media metadata without decoding or changing the source."""

    def inspect(self, path: Path) -> dict[str, int | float]: ...


class PyAvMediaMetadataReader:
    """Read bounded video metadata using the existing local PyAV dependency."""

    def inspect(self, path: Path) -> dict[str, int | float]:
        try:
            with av.open(str(path)) as container:
                stream = next(iter(container.streams.video), None)
                if stream is None:
                    raise TakeSequenceAssemblyError(
                        f"Bound source has no video stream: {path.name}"
                    )
                duration = _duration_seconds(container, stream)
                frame_rate = (
                    float(stream.average_rate)
                    if stream.average_rate is not None
                    else 0.0
                )
                width = int(stream.width)
                height = int(stream.height)
        except (av.error.FFmpegError, OSError, ValueError) as error:
            raise TakeSequenceAssemblyError(
                f"Could not inspect bound source {path.name}: {error}"
            ) from error
        if (
            not math.isfinite(frame_rate)
            or frame_rate <= 0
            or width <= 0
            or height <= 0
        ):
            raise TakeSequenceAssemblyError(
                f"Bound source video metadata is incomplete: {path.name}"
            )
        return {
            "duration_seconds": round(duration, 6),
            "frame_rate": round(frame_rate, 6),
            "width": width,
            "height": height,
        }


class TakeSequenceAssemblyWorkflow:
    """Calculate a deterministic path-redacted assembly without Resolve."""

    def __init__(
        self,
        bindings: TakeSequenceBindingReader,
        metadata: MediaMetadataReader | None = None,
    ) -> None:
        self._bindings = bindings
        self._metadata = metadata or PyAvMediaMetadataReader()

    def preview(
        self,
        *,
        binding_id: str,
        assembly_name: str,
    ) -> dict[str, Any]:
        """Return sequential source/output ranges after local file revalidation."""
        name = _assembly_name(assembly_name)
        binding = self._bindings.get(binding_id)
        sources = self._bindings.resolve_sources(binding_id)
        public_sources = binding.get("sources")
        if (
            binding.get("binding_id") != binding_id
            or not isinstance(public_sources, list)
            or len(public_sources) != len(sources)
            or not sources
        ):
            raise TakeSequenceAssemblyError("Take-sequence binding is incomplete.")

        entries: list[dict[str, Any]] = []
        cursor = 0.0
        for public, source in zip(public_sources, sources, strict=True):
            if not isinstance(public, dict) or not isinstance(source, dict):
                raise TakeSequenceAssemblyError("Bound source entry is invalid.")
            if any(
                public.get(field) != source.get(field)
                for field in (
                    "order",
                    "selected_candidate_id",
                    "display_name",
                    "fingerprint",
                    "size_bytes",
                    "source_range",
                )
            ):
                raise TakeSequenceAssemblyError(
                    "Private source does not match its redacted binding receipt."
                )
            path_value = source.get("path")
            if not isinstance(path_value, str):
                raise TakeSequenceAssemblyError("Bound source path is invalid.")
            media = self._metadata.inspect(Path(path_value))
            source_range = _source_range(source.get("source_range"), media)
            item_duration = source_range["end_seconds"] - source_range["start_seconds"]
            output_start = cursor
            output_end = output_start + item_duration
            entries.append(
                {
                    "order": source["order"],
                    "selected_candidate_id": source["selected_candidate_id"],
                    "display_name": source["display_name"],
                    "fingerprint": source["fingerprint"],
                    "source_range": source_range,
                    "output_range": {
                        "start_seconds": round(output_start, 6),
                        "end_seconds": round(output_end, 6),
                    },
                    "video": {
                        "frame_rate": media["frame_rate"],
                        "width": media["width"],
                        "height": media["height"],
                    },
                }
            )
            cursor = output_end

        frame_rates = {entry["video"]["frame_rate"] for entry in entries}
        resolutions = {
            (entry["video"]["width"], entry["video"]["height"])
            for entry in entries
        }
        warnings: list[str] = []
        if len(frame_rates) > 1:
            warnings.append(
                "Source frame rates differ; target timeline frame mapping is "
                "unresolved."
            )
        if len(resolutions) > 1:
            warnings.append(
                "Source resolutions differ; target timeline scaling is unresolved."
            )
        payload = {
            "assembly_version": ASSEMBLY_VERSION,
            "status": "preview",
            "assembly_name": name,
            "binding_id": binding_id,
            "binding_sha256": _canonical_sha256(binding),
            "entries": entries,
            "entry_count": len(entries),
            "total_duration_seconds": round(cursor, 6),
            "uniform_frame_rate": len(frame_rates) == 1,
            "uniform_resolution": len(resolutions) == 1,
            "warnings": warnings,
            "paths_redacted": True,
            "timeline_modified": False,
            "apply_supported": False,
        }
        result = {"plan_id": _canonical_sha256(payload), **payload}
        validate_contract("take-sequence-assembly-preview", result)
        return result


def _duration_seconds(container: Any, stream: Any) -> float:
    if stream.duration is not None:
        duration = float(stream.duration * stream.time_base)
        if math.isfinite(duration) and duration > 0:
            return duration
    if container.duration is not None:
        duration = float(container.duration / av.time_base)
        if math.isfinite(duration) and duration > 0:
            return duration
    raise TakeSequenceAssemblyError("Bound source duration is unavailable.")


def _source_range(
    value: object,
    media: dict[str, int | float],
) -> dict[str, float]:
    duration = float(media["duration_seconds"])
    if value is None:
        return {"start_seconds": 0.0, "end_seconds": round(duration, 6)}
    if not isinstance(value, dict):
        raise TakeSequenceAssemblyError("Bound source range is invalid.")
    start = value.get("start_seconds")
    end = value.get("end_seconds")
    if (
        not isinstance(start, (int, float))
        or isinstance(start, bool)
        or not isinstance(end, (int, float))
        or isinstance(end, bool)
        or not math.isfinite(float(start))
        or not math.isfinite(float(end))
        or float(start) < 0
        or float(end) <= float(start)
        or float(end) > duration + SOURCE_DURATION_TOLERANCE_SECONDS
    ):
        raise TakeSequenceAssemblyError(
            "Bound source range exceeds the inspected media duration."
        )
    return {
        "start_seconds": round(float(start), 6),
        "end_seconds": round(min(float(end), duration), 6),
    }


def _assembly_name(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 128:
        raise TakeSequenceAssemblyError(
            "assembly_name must contain 1 to 128 characters."
        )
    return value.strip()


def _canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
