"""Guarded intervals for temporarily hiding canonical camera circles."""

from pathlib import Path
from typing import Any

from agent.media import MediaPolicy
from providers.resolve.lua_editing import bounded_text


def validate_camera_visibility(a: dict[str, Any], roots: list[Path]) -> dict[str, Any]:
    if set(a) != {"timeline_name", "camera_visibility"}:
        raise ValueError("Invalid camera visibility fields.")
    name = bounded_text(a["timeline_name"], "Timeline name")
    c = a["camera_visibility"]
    if not isinstance(c, dict) or set(c) != {
        "name",
        "expected_start",
        "expected_end",
        "items",
    }:
        raise ValueError("Invalid camera visibility plan.")
    destination = bounded_text(c["name"], "Destination timeline")
    if destination == name:
        raise ValueError("Visibility changes require a new timeline.")
    for key in ("expected_start", "expected_end"):
        if type(c[key]) is not int or not 0 <= c[key] <= 2147483647:
            raise ValueError("Invalid timeline bounds.")
    if c["expected_start"] >= c["expected_end"]:
        raise ValueError("Invalid timeline bounds.")
    if not isinstance(c["items"], list) or not 1 <= len(c["items"]) <= 128:
        raise ValueError("Provide 1 to 128 camera items.")
    items: list[dict[str, Any]] = []
    seen = set()
    for x in c["items"]:
        if not isinstance(x, dict) or set(x) != {
            "index",
            "path",
            "start",
            "end",
            "intervals",
        }:
            raise ValueError("Invalid camera item.")
        for key in ("index", "start", "end"):
            if type(x[key]) is not int or not 0 <= x[key] <= 2147483647:
                raise ValueError("Invalid camera geometry.")
        if not 1 <= x["index"] <= 1000 or x["index"] in seen:
            raise ValueError("Duplicate or invalid camera index.")
        seen.add(x["index"])
        if not c["expected_start"] <= x["start"] < x["end"] <= c["expected_end"]:
            raise ValueError("Camera bounds outside timeline.")
        if not isinstance(x["intervals"], list) or not 1 <= len(x["intervals"]) <= 64:
            raise ValueError("Provide 1 to 64 hide intervals per item.")
        previous = x["start"] - 1
        for pair in x["intervals"]:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or any(type(v) is not int for v in pair)
            ):
                raise ValueError("Expected integer interval pairs.")
            lo, hi = pair
            if not x["start"] <= lo < hi <= x["end"] or lo <= previous:
                raise ValueError("Intervals must be separated and inside the clip.")
            previous = hi
        path = MediaPolicy(roots).validate_files([x["path"]])[0]
        items.append(dict(x, path=Path(path).as_posix()))
    return {
        "timeline_name": name,
        "camera_visibility": dict(c, name=destination, items=items),
    }
