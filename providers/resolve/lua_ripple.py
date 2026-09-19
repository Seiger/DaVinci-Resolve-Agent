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


def validate_batch(a: dict[str, Any], roots: list[Path]) -> dict[str, Any]:
    """Validate disjoint cuts; group-edge removal requires an explicit opt-in."""
    if set(a) != {"timeline_name", "ripple_batch"}:
        raise ValueError("Invalid batch fields.")
    name = bounded_text(a["timeline_name"], "Timeline name")
    c = a["ripple_batch"]
    fields = {
        "name",
        "expected_timeline_start",
        "expected_timeline_end",
        "groups",
    }
    if isinstance(c, dict) and "allow_group_edges" in c:
        fields.add("allow_group_edges")
        if type(c["allow_group_edges"]) is not bool:
            raise ValueError("Group-edge opt-in must be boolean.")
    if not isinstance(c, dict) or set(c) != fields:
        raise ValueError("Invalid batch plan.")
    edges = c.get("allow_group_edges", False)
    destination = bounded_text(c["name"], "Destination timeline")
    if name == destination:
        raise ValueError("Batch requires a new timeline.")
    for k in ("expected_timeline_start", "expected_timeline_end"):
        if type(c[k]) is not int or not 0 <= c[k] <= 2147483647:
            raise ValueError("Invalid timeline bounds.")
    if c["expected_timeline_start"] >= c["expected_timeline_end"]:
        raise ValueError("Invalid timeline bounds.")
    maximum = 256 if edges else 128
    if not isinstance(c["groups"], list) or not 1 <= len(c["groups"]) <= maximum:
        raise ValueError(f"Provide 1 to {maximum} groups.")
    normalized = []
    previous_index = 0
    previous_end = c["expected_timeline_start"]
    cuts = 0
    for g in c["groups"]:
        if not isinstance(g, dict) or set(g) != {
            "index",
            "start",
            "end",
            "screen_source_start",
            "camera_source_start",
            "screen_path",
            "camera_path",
            "intervals",
        }:
            raise ValueError("Invalid group fields.")
        for k in (
            "index",
            "start",
            "end",
            "screen_source_start",
            "camera_source_start",
        ):
            if type(g[k]) is not int or not 0 <= g[k] <= 2147483647:
                raise ValueError("Invalid group geometry.")
        if (
            not previous_index < g["index"] <= 1000
            or not previous_end <= g["start"] < g["end"] <= c["expected_timeline_end"]
        ):
            raise ValueError("Groups must be ordered and separate.")
        previous_index, previous_end = g["index"], g["end"]
        if not isinstance(g["intervals"], list) or not 1 <= len(g["intervals"]) <= 64:
            raise ValueError("Provide 1 to 64 cuts per group.")
        previous = g["start"]
        for position, pair in enumerate(g["intervals"]):
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or any(type(v) is not int for v in pair)
            ):
                raise ValueError("Expected frame pairs.")
            lo, hi = pair
            if not (
                (previous <= lo if edges and position == 0 else previous < lo)
                and lo < hi
                and (hi <= g["end"] if edges else hi < g["end"])
            ):
                raise ValueError(
                    "Cuts must be separated and within the permitted group bounds."
                )
            previous = hi
            cuts += 1
        paths = MediaPolicy(roots).validate_files([g["screen_path"], g["camera_path"]])
        normalized.append(
            dict(
                g,
                screen_path=Path(paths[0]).as_posix(),
                camera_path=Path(paths[1]).as_posix(),
            )
        )
    if cuts > (512 if edges else 128):
        raise ValueError("Too many cuts per batch.")
    removed = sum(hi - lo for g in normalized for lo, hi in g["intervals"])
    if removed >= c["expected_timeline_end"] - c["expected_timeline_start"]:
        raise ValueError("Batch must retain timeline content.")
    return {
        "timeline_name": name,
        "ripple_batch": dict(c, name=destination, groups=normalized),
    }
