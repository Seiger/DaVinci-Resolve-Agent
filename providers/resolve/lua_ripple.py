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
