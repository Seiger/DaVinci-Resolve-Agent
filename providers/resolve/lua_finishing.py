"""Bounded finishing inputs and verification of managed render outputs."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from agent.media import MediaPolicy
from providers.resolve.lua_editing import bounded_text

FINISH_ACTIONS = frozenset(
    {"set_clip_properties", "add_subtitles", "prepare_render", "start_render"}
)
PROPERTY_LIMITS = {
    "ZoomX": (0.1, 4),
    "ZoomY": (0.1, 4),
    "Pan": (-3840, 3840),
    "Tilt": (-2160, 2160),
    "Opacity": (0, 100),
    "AudioVolume": (-60, 12),
}


def validate_finishing(
    action: str, a: dict[str, Any], roots: list[Path]
) -> dict[str, Any]:
    if action in {"start_render", "get_render_status"}:
        if (
            set(a) != {"job_id"}
            or not isinstance(a["job_id"], str)
            or not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", a["job_id"])
        ):
            raise ValueError("Expected one safe render job ID.")
        return dict(a)
    name = bounded_text(a.get("timeline_name"), "Timeline name")
    if action == "prepare_render" and set(a) == {"timeline_name"}:
        return {"timeline_name": name}
    if action == "set_clip_properties" and set(a) == {
        "timeline_name",
        "track_type",
        "track_index",
        "item_index",
        "expected_media_path",
        "properties",
    }:
        kind = a["track_type"]
        if kind not in {"video", "audio"} or any(
            type(a[k]) is not int or not 1 <= a[k] <= 1000
            for k in ("track_index", "item_index")
        ):
            raise ValueError("Invalid timeline item selector.")
        media_path = MediaPolicy(roots).validate_files([a["expected_media_path"]])[0]
        props = a["properties"]
        if not isinstance(props, dict) or not props:
            raise ValueError("At least one allowlisted property is required.")
        for key, value in props.items():
            if key not in PROPERTY_LIMITS or (kind == "audio") != (
                key == "AudioVolume"
            ):
                raise ValueError("Unsupported property for this track type.")
            low, high = PROPERTY_LIMITS[key]
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ValueError("Property value outside allowed range.")
        return dict(
            a, timeline_name=name, expected_media_path=Path(media_path).as_posix()
        )
    if action == "add_subtitles" and set(a) == {"timeline_name", "subtitle_path"}:
        path = Path(MediaPolicy(roots).validate_files([a["subtitle_path"]])[0])
        if path.suffix.lower() != ".srt" or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Expected a bounded UTF-8 SRT file.")
        text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()
        cues = []

        def seconds(value: str) -> float:
            h, m, s, ms = map(int, re.split("[:,]", value))
            if m >= 60 or s >= 60:
                raise ValueError("Invalid SRT timestamp.")
            return h * 3600 + m * 60 + s + ms / 1000

        previous_end = 0.0
        for block in re.split(r"\n\s*\n", text):
            lines = block.splitlines()
            if len(lines) < 3 or not lines[0].isdigit():
                raise ValueError("Malformed SRT cue.")
            match = re.fullmatch(
                r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})", lines[1]
            )
            if not match:
                raise ValueError("Malformed SRT timing.")
            start, end = seconds(match[1]), seconds(match[2])
            if start < previous_end or end <= start or end > 12 * 3600:
                raise ValueError("Overlapping, reversed or excessive subtitle range.")
            previous_end = end
            cues.append({"start": start, "end": end})
        if not 1 <= len(cues) <= 2000:
            raise ValueError("Expected 1–2000 subtitle cues.")
        return {
            "timeline_name": name,
            "subtitle_path": path.as_posix(),
            "cue_count": len(cues),
            "first_start": cues[0]["start"],
            "last_end": cues[-1]["end"],
        }
    raise ValueError("Unknown finishing action or unexpected fields.")


def verify_video(path: Path) -> dict[str, Any]:
    import av

    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Completed render has no non-empty output file.")
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError("Render contains no video stream.")
        video = container.streams.video[0]
        frame = next(container.decode(video), None)
        if frame is None:
            raise ValueError("Rendered video cannot be decoded.")
        return {
            "path": str(path),
            "bytes": path.stat().st_size,
            "width": video.width,
            "height": video.height,
            "audio_streams": len(container.streams.audio),
            "duration_seconds": container.duration / 1_000_000
            if container.duration
            else None,
            "video_decode_verified": True,
        }
