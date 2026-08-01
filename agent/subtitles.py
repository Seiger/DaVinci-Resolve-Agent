"""Provider-neutral transcript validation and deterministic SRT rendering."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from agent.contracts import validate_contract
from agent.paths import subtitle_output_directory, subtitle_receipts_directory


class SubtitleArtifactError(ValueError):
    """Raised when transcript data cannot form a safe subtitle artifact."""


class SubtitleTranscriber(Protocol):
    def transcribe(self, source_path: Path) -> dict[str, Any]:
        """Return bounded normalized transcript segments."""


class SubtitleGateway(Protocol):
    def subtitle_environment(
        self, timeline_id: str, *, timeout_seconds: float = 30
    ) -> dict[str, Any]: ...

    def import_media(
        self,
        paths: list[str],
        *,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...

    def append_subtitle_file(
        self,
        timeline_id: str,
        asset_id: str,
        subtitle_path: str,
        import_idempotency_key: str,
        *,
        confirm_apply: bool,
        timeout_seconds: float = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...


class SubtitleMediaPolicy(Protocol):
    def validate_files(self, paths: list[str]) -> list[str]: ...

    def prepare_import(self, paths: list[str]) -> list[str]: ...


class SubtitleGenerator:
    """Transcribe locally, emit SRT and apply it through safe provider calls."""

    def __init__(
        self,
        transcriber: SubtitleTranscriber,
        gateway: SubtitleGateway,
        media_policy: SubtitleMediaPolicy,
        output_root: Path | None = None,
        receipt_root: Path | None = None,
    ) -> None:
        self._transcriber = transcriber
        self._gateway = gateway
        self._media_policy = media_policy
        self._output_root = (
            subtitle_output_directory() if output_root is None else output_root
        )
        self._receipt_root = (
            subtitle_receipts_directory() if receipt_root is None else receipt_root
        )

    def generate(
        self,
        source_file: str,
        timeline_id: str,
        *,
        confirm_apply: bool,
        timeout_seconds: float = 300,
    ) -> dict[str, Any]:
        """Generate and apply one deterministic local SRT subtitle artifact."""
        if confirm_apply is not True:
            raise ValueError("confirm_apply must be true.")
        if not timeline_id or len(timeline_id) > 128:
            raise ValueError("timeline_id must contain 1 to 128 characters.")
        normalized = self._media_policy.validate_files([source_file])
        source_path = Path(normalized[0])
        receipt_id = _receipt_id(source_path, timeline_id)
        receipt_path = self._receipt_root / f"{receipt_id}.json"
        existing = _read_applied_receipt(receipt_path)
        if existing is not None:
            return existing

        before = self._gateway.subtitle_environment(
            timeline_id,
            timeout_seconds=timeout_seconds,
        )
        before_ids = _subtitle_item_ids(before)
        transcript = self._transcriber.transcribe(source_path)
        output_path = write_srt(
            self._output_root / f"{receipt_id}.srt",
            transcript,
        )
        import_paths = self._media_policy.prepare_import([str(output_path)])
        import_idempotency_key = f"{receipt_id}:import"
        imported = self._gateway.import_media(
            import_paths,
            timeout_seconds=timeout_seconds,
            idempotency_key=import_idempotency_key,
        )
        items = imported.get("items")
        if not isinstance(items, list) or len(items) != 1:
            raise SubtitleArtifactError("Subtitle import returned invalid items.")
        asset_id = items[0].get("asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            raise SubtitleArtifactError("Subtitle import returned no asset ID.")
        appended = self._gateway.append_subtitle_file(
            timeline_id,
            asset_id,
            str(output_path),
            import_idempotency_key,
            confirm_apply=True,
            timeout_seconds=timeout_seconds,
            idempotency_key=f"{receipt_id}:subtitle-append",
        )
        appended_items = appended.get("items")
        if not isinstance(appended_items, list) or not appended_items:
            raise SubtitleArtifactError("Subtitle append returned no items.")
        appended_ids: set[str] = set()
        for item in appended_items:
            item_id = item.get("timeline_item_id") if isinstance(item, dict) else None
            if not isinstance(item_id, str) or not item_id:
                raise SubtitleArtifactError(
                    "Subtitle append returned an invalid timeline item ID."
                )
            appended_ids.add(item_id)
        after = self._gateway.subtitle_environment(
            timeline_id,
            timeout_seconds=timeout_seconds,
        )
        discovered_ids = _subtitle_item_ids(after)
        if not appended_ids or not appended_ids.issubset(discovered_ids):
            raise SubtitleArtifactError(
                "Resolve subtitle readback does not contain appended items."
            )
        new_item_ids = discovered_ids - before_ids
        if len(appended_ids) != len(transcript["segments"]):
            raise SubtitleArtifactError(
                "Resolve subtitle readback count does not match the transcript."
            )
        if new_item_ids and new_item_ids != appended_ids:
            raise SubtitleArtifactError(
                "Resolve subtitle readback does not match the append receipt."
            )
        timeline_start_frame = appended.get("timeline_start_frame")
        append_frame = appended.get("append_frame")
        timeline_frame_rate = appended.get("timeline_frame_rate")
        applied_items = [
            item
            for track in after["tracks"]
            for item in track["items"]
            if item["timeline_item_id"] in appended_ids
        ]
        if (
            not isinstance(timeline_start_frame, int)
            or isinstance(timeline_start_frame, bool)
            or isinstance(timeline_frame_rate, bool)
            or not isinstance(timeline_frame_rate, (int, float))
        ):
            raise SubtitleArtifactError("Subtitle placement metadata is invalid.")
        first_offset_frames = round(
            transcript["segments"][0]["start_ms"]
            * float(timeline_frame_rate)
            / 1000
        )
        actual_first_frame = min(
            item["timeline_start_frame"] for item in applied_items
        )
        append_frame_source = "bridge"
        if not isinstance(append_frame, int) or isinstance(append_frame, bool):
            if not appended_ids.issubset(before_ids):
                raise SubtitleArtifactError(
                    "Subtitle append returned no placement anchor."
                )
            append_frame = actual_first_frame - first_offset_frames
            append_frame_source = "recovered_provider_receipt"
        expected_first_frame = append_frame + first_offset_frames
        if actual_first_frame != expected_first_frame:
            raise SubtitleArtifactError(
                "Resolve placed subtitles away from the reported append frame."
            )
        receipt = {
            "receipt_id": receipt_id,
            "status": "applied",
            "timeline_id": timeline_id,
            "source_file": str(source_path),
            "subtitle_file": str(output_path),
            "backend": transcript.get("backend"),
            "model": transcript.get("model"),
            "language": transcript.get("language"),
            "segment_count": len(transcript["segments"]),
            "previous_subtitle_item_count": before.get("subtitle_item_count"),
            "subtitle_item_count": after.get("subtitle_item_count"),
            "timeline_item_ids": sorted(appended_ids),
            "placement": {
                "timeline_start_frame": timeline_start_frame,
                "append_frame": append_frame,
                "append_frame_source": append_frame_source,
                "timeline_frame_rate": timeline_frame_rate,
                "expected_first_frame": expected_first_frame,
                "actual_first_frame": actual_first_frame,
            },
            "import_result": imported,
            "append_result": appended,
        }
        validate_contract("subtitle-generation", receipt)
        _atomic_write_json(receipt_path, receipt)
        return receipt


def render_srt(transcript: dict[str, Any]) -> str:
    """Render bounded ordered transcript segments as UTF-8 SRT text."""
    segments = transcript.get("segments")
    if not isinstance(segments, list) or not 1 <= len(segments) <= 10_000:
        raise SubtitleArtifactError(
            "Transcript must contain between 1 and 10000 segments."
        )
    blocks: list[str] = []
    previous_end = 0
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            raise SubtitleArtifactError("Every transcript segment must be an object.")
        start_ms = segment.get("start_ms")
        end_ms = segment.get("end_ms")
        text = segment.get("text")
        if (
            not isinstance(start_ms, int)
            or isinstance(start_ms, bool)
            or not isinstance(end_ms, int)
            or isinstance(end_ms, bool)
            or start_ms < previous_end
            or end_ms <= start_ms
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > 4_000
        ):
            raise SubtitleArtifactError("Transcript segments are invalid or overlap.")
        clean_text = " ".join(text.split())
        blocks.append(
            f"{index}\n{_srt_timestamp(start_ms)} --> {_srt_timestamp(end_ms)}"
            f"\n{clean_text}\n"
        )
        previous_end = end_ms
    return "\n".join(blocks)


def write_srt(path: Path, transcript: dict[str, Any]) -> Path:
    """Atomically write one deterministic managed subtitle artifact."""
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f"{resolved.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        output.write(render_srt(transcript))
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(resolved)
    return resolved


def _srt_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def _receipt_id(source_path: Path, timeline_id: str) -> str:
    stat = source_path.stat()
    payload = {
        "source": str(source_path),
        "size": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
        "timeline_id": timeline_id,
        "policy": "faster-whisper-small-uk-srt-v1",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _subtitle_item_ids(environment: dict[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    tracks = environment.get("tracks")
    if not isinstance(tracks, list):
        raise SubtitleArtifactError("Subtitle environment tracks are invalid.")
    for track in tracks:
        items = track.get("items") if isinstance(track, dict) else None
        if not isinstance(items, list):
            raise SubtitleArtifactError("Subtitle environment items are invalid.")
        for item in items:
            item_id = item.get("timeline_item_id") if isinstance(item, dict) else None
            if not isinstance(item_id, str) or not item_id:
                raise SubtitleArtifactError("Subtitle readback item ID is invalid.")
            identifiers.add(item_id)
    return identifiers


def _read_applied_receipt(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as source:
        loaded: object = json.load(source)
    if isinstance(loaded, dict) and loaded.get("status") == "applied":
        validate_contract("subtitle-generation", loaded)
        return loaded
    return None


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
