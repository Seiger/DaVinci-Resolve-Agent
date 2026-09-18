"""Strict inputs for a copied-timeline cut inside one synced group."""

from pathlib import Path
from typing import Any

from agent.media import MediaPolicy
from providers.resolve.lua_editing import bounded_text


def validate_ripple(a: dict[str, Any], roots: list[Path]) -> dict[str, Any]:
    """Require explicit geometry and source identities; never accept raw Lua."""
    if set(a) != {"timeline_name", "ripple_cut"}:
        raise ValueError("Invalid ripple fields.")
    name = bounded_text(a["timeline_name"], "Timeline name")
    cut = a["ripple_cut"]
    fields = {
        "name",
        "start_frame",
        "end_frame",
        "expected_timeline_start",
        "expected_timeline_end",
        "expected_group_end",
        "screen_path",
        "camera_path",
        "screen_source_start",
        "camera_source_start",
    }
    if not isinstance(cut, dict):
        raise ValueError("Invalid ripple cut fields.")
    if "group_index" in cut or "expected_group_start" in cut:
        fields |= {"group_index", "expected_group_start"}
    if set(cut) != fields:
        raise ValueError("Invalid ripple cut fields.")
    destination = bounded_text(cut["name"], "Destination timeline")
    if destination == name:
        raise ValueError("Ripple requires a separate destination timeline.")
    for key in fields - {"name", "screen_path", "camera_path"}:
        if type(cut[key]) is not int or not 0 <= cut[key] <= 2_147_483_647:
            raise ValueError("Ripple geometry requires nonnegative integer frames.")
    group_start = cut.get("expected_group_start", cut["expected_timeline_start"])
    if not 1 <= cut.get("group_index", 1) <= 1000:
        raise ValueError("Invalid group index.")
    if not (
        cut["expected_timeline_start"]
        <= group_start
        < cut["start_frame"]
        < cut["end_frame"]
        < cut["expected_group_end"]
        < cut["expected_timeline_end"]
    ):
        raise ValueError("Cut must lie strictly inside the selected group.")
    paths = MediaPolicy(roots).validate_files([cut["screen_path"], cut["camera_path"]])
    return {
        "timeline_name": name,
        "ripple_cut": dict(
            cut,
            name=destination,
            screen_path=Path(paths[0]).as_posix(),
            camera_path=Path(paths[1]).as_posix(),
        ),
    }


def validate_span(a: dict[str, Any], roots: list[Path]) -> dict[str, Any]:
    """Bound a cross-group cut by explicit contiguous source geometry."""
    if set(a) != {"timeline_name", "ripple_span"}:
        raise ValueError("Invalid span fields.")
    name = bounded_text(a["timeline_name"], "Timeline name")
    c = a["ripple_span"]
    if not isinstance(c, dict) or set(c) != {
        "name",
        "start_frame",
        "end_frame",
        "expected_timeline_start",
        "expected_timeline_end",
        "groups",
    }:
        raise ValueError("Invalid span fields.")
    destination = bounded_text(c["name"], "Destination timeline")
    if destination == name:
        raise ValueError("Span requires a new timeline.")
    for key in (
        "start_frame",
        "end_frame",
        "expected_timeline_start",
        "expected_timeline_end",
    ):
        if type(c[key]) is not int or not 0 <= c[key] <= 2147483647:
            raise ValueError("Expected nonnegative integer geometry.")
    groups = c["groups"]
    if not isinstance(groups, list) or not 2 <= len(groups) <= 20:
        raise ValueError("Span requires 2 to 20 groups.")
    normalized: list[dict[str, Any]] = []
    for g in groups:
        if not isinstance(g, dict) or set(g) != {
            "index",
            "start",
            "end",
            "screen_source_start",
            "camera_source_start",
            "screen_path",
            "camera_path",
        }:
            raise ValueError("Invalid group geometry.")
        for k in (
            "index",
            "start",
            "end",
            "screen_source_start",
            "camera_source_start",
        ):
            if type(g[k]) is not int or not 0 <= g[k] <= 2147483647:
                raise ValueError("Invalid group geometry.")
        if not 1 <= g["index"] <= 1000 or g["start"] >= g["end"]:
            raise ValueError("Invalid group range.")
        if normalized and (
            g["index"] != normalized[-1]["index"] + 1
            or g["start"] != normalized[-1]["end"]
        ):
            raise ValueError("Groups must be contiguous.")
        paths = MediaPolicy(roots).validate_files([g["screen_path"], g["camera_path"]])
        normalized.append(
            dict(
                g,
                screen_path=Path(paths[0]).as_posix(),
                camera_path=Path(paths[1]).as_posix(),
            )
        )
    if not (
        c["expected_timeline_start"]
        <= groups[0]["start"]
        < c["start_frame"]
        < groups[0]["end"]
        <= groups[-1]["start"]
        < c["end_frame"]
        < groups[-1]["end"]
        <= c["expected_timeline_end"]
    ):
        raise ValueError("Span must start and end inside its boundary groups.")
    return {
        "timeline_name": name,
        "ripple_span": dict(c, name=destination, groups=normalized),
    }
