"""Bounded local privacy blur inputs for the Lua snapshot bridge."""

import math
from pathlib import Path
from typing import Any

from agent.media import MediaPolicy
from providers.resolve.lua_editing import bounded_text


def validate_privacy_batch(a: dict[str, Any], roots: list[Path]) -> dict[str, Any]:
    """Validate every distinct screen selector before publishing a batch."""
    if set(a) != {"timeline_name", "privacy_batch"}:
        raise ValueError("Invalid privacy batch fields.")
    name = bounded_text(a["timeline_name"], "Timeline name")
    batch = a["privacy_batch"]
    if not isinstance(batch, list) or not 1 <= len(batch) <= 100:
        raise ValueError("Privacy batch requires 1-100 distinct screen items.")
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in batch:
        if not isinstance(item, dict) or set(item) != {
            "item_index",
            "expected_media_path",
            "privacy_blur",
        }:
            raise ValueError("Invalid privacy batch item.")
        validated = validate_privacy(dict(item, timeline_name=name), roots)
        if validated["item_index"] in seen:
            raise ValueError("Duplicate screen item in privacy batch.")
        seen.add(validated["item_index"])
        validated.pop("timeline_name")
        result.append(validated)
    return {"timeline_name": name, "privacy_batch": result}


def validate_privacy(a: dict[str, Any], roots: list[Path]) -> dict[str, Any]:
    """Accept one existing screen item and a finite local frame interval."""
    if set(a) != {"timeline_name", "item_index", "expected_media_path", "privacy_blur"}:
        raise ValueError("Invalid privacy blur fields.")
    name = bounded_text(a["timeline_name"], "Timeline name")
    if type(a["item_index"]) is not int or not 1 <= a["item_index"] <= 1000:
        raise ValueError("Invalid screen item selector.")
    p = a["privacy_blur"]
    frames = {"start_frame", "end_frame", "expected_clip_start", "expected_clip_end"}
    geometry = {"center_x", "center_y", "width", "height", "strength"}
    if not isinstance(p, dict) or set(p) not in (
        frames | geometry,
        frames | geometry | {"additional_intervals"},
    ):
        raise ValueError("Invalid privacy geometry.")
    for key in frames:
        if type(p[key]) is not int or not 0 <= p[key] <= 2_147_483_647:
            raise ValueError("Privacy bounds require integer frames.")
    if not (
        p["expected_clip_start"]
        <= p["start_frame"]
        < p["end_frame"]
        <= p["expected_clip_end"]
    ):
        raise ValueError("Privacy interval must stay inside the selected clip.")
    intervals = p.get("additional_intervals", [])
    if not isinstance(intervals, list) or len(intervals) > 63:
        raise ValueError("At most 64 privacy intervals are supported per clip.")
    previous_end = p["end_frame"]
    for interval in intervals:
        if (
            not isinstance(interval, dict)
            or set(interval) != {"start_frame", "end_frame"}
            or any(type(v) is not int for v in interval.values())
            or not previous_end
            < interval["start_frame"]
            < interval["end_frame"]
            <= p["expected_clip_end"]
        ):
            raise ValueError(
                "Additional privacy intervals must be ordered, separated "
                "and inside the clip."
            )
        previous_end = interval["end_frame"]
    for key in geometry:
        low, high = (20, 100) if key == "strength" else (0, 1)
        if (
            type(p[key]) not in (int, float)
            or not math.isfinite(p[key])
            or not low <= p[key] <= high
        ):
            raise ValueError("Invalid bounded privacy value.")
    if p["width"] <= 0 or p["height"] <= 0:
        raise ValueError("Privacy mask must have positive dimensions.")
    for axis, extent in (("center_x", "width"), ("center_y", "height")):
        if p[axis] - p[extent] / 2 < -1e-9 or p[axis] + p[extent] / 2 > 1 + 1e-9:
            raise ValueError("Privacy rectangle must remain within the image.")
    path = MediaPolicy(roots).validate_files([a["expected_media_path"]])[0]
    return dict(
        a,
        timeline_name=name,
        expected_media_path=Path(path).as_posix(),
        privacy_blur=dict(p),
    )
