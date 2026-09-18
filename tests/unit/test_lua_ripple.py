"""Fail-closed geometry, file ownership and replay for a copied opening cut."""

from pathlib import Path
from typing import Any

import pytest

from providers.resolve.lua_finishing import validate_finishing


def arguments(root: Path) -> dict[str, Any]:
    for name in ("screen.mkv", "blur.mp4"):
        (root / name).touch()
    return {
        "timeline_name": "Story v2",
        "ripple_cut": {
            "name": "Story v3",
            "start_frame": 216702,
            "end_frame": 216996,
            "expected_timeline_start": 216000,
            "expected_timeline_end": 1689869,
            "expected_group_end": 219240,
            "screen_path": str(root / "screen.mkv"),
            "camera_path": str(root / "blur.mp4"),
            "screen_source_start": 444,
            "camera_source_start": 0,
        },
    }


@pytest.mark.parametrize(
    "change",
    [
        {"name": "Story v2"},
        {"start_frame": True},
        {"end_frame": 216702},
        {"start_frame": 216000},
        {"end_frame": 219240},
        {"expected_timeline_end": 219239},
        {"camera_source_start": -1},
        {"start_frame": 216702.5},
        {"lua": "arbitrary()"},
    ],
)
def test_invalid_opening_cut_is_rejected(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    a = arguments(tmp_path)
    a["ripple_cut"].update(change)
    with pytest.raises(ValueError):
        validate_finishing("set_clip_properties", a, [tmp_path])


def test_derived_camera_keeps_independent_source_origin(tmp_path: Path) -> None:
    a = arguments(tmp_path)
    checked = validate_finishing("set_clip_properties", a, [tmp_path])
    assert checked["ripple_cut"]["camera_source_start"] == 0
    assert checked["ripple_cut"]["screen_source_start"] == 444
    assert (
        checked["ripple_cut"]["end_frame"] - checked["ripple_cut"]["start_frame"] == 294
    )
    with pytest.raises(ValueError):
        validate_finishing("set_clip_properties", dict(a, command="unsafe"), [tmp_path])


def test_opening_cut_cannot_reference_media_outside_roots(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    a = arguments(root)
    outside = tmp_path / "other.mp4"
    outside.touch()
    a["ripple_cut"]["camera_path"] = str(outside)
    with pytest.raises(ValueError):
        validate_finishing("set_clip_properties", a, [root])


def test_selected_group_requires_explicit_matching_geometry(tmp_path: Path) -> None:
    a = arguments(tmp_path)
    a["ripple_cut"].update(group_index=5, expected_group_start=216500)
    checked = validate_finishing("set_clip_properties", a, [tmp_path])
    assert checked["ripple_cut"]["group_index"] == 5
    assert checked["ripple_cut"]["expected_group_start"] == 216500
    for change in (
        {"group_index": 0},
        {"group_index": True},
        {"group_index": 1001},
        {"expected_group_start": 216800},
        {"expected_group_start": 215999},
    ):
        bad = dict(a, ripple_cut=dict(a["ripple_cut"], **change))
        with pytest.raises(ValueError):
            validate_finishing("set_clip_properties", bad, [tmp_path])
    del a["ripple_cut"]["expected_group_start"]
    with pytest.raises(ValueError):
        validate_finishing("set_clip_properties", a, [tmp_path])
