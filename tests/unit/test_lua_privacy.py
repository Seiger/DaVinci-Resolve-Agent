"""Reject unbounded intervals and invalid privacy rectangles before dispatch."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from mcp_server.lua_experimental import create_server
from providers.resolve.lua_finishing import validate_finishing
from providers.resolve.lua_transport import LuaSnapshotClient, prepare


def args(root: Path) -> dict[str, Any]:
    p = root / "screen.mkv"
    p.touch()
    return {
        "timeline_name": "Private review",
        "item_index": 7,
        "expected_media_path": str(p),
        "privacy_blur": {
            "expected_clip_start": 1000,
            "expected_clip_end": 4000,
            "start_frame": 1500,
            "end_frame": 1750,
            "center_x": 0.15,
            "center_y": 0.5,
            "width": 0.3,
            "height": 1,
            "strength": 60,
        },
    }


@pytest.mark.parametrize(
    "change",
    [
        {"start_frame": True},
        {"end_frame": 1500},
        {"start_frame": 999},
        {"end_frame": 4001},
        {"width": 0},
        {"width": 0.5},
        {"center_y": float("nan")},
        {"strength": float("inf")},
        {"strength": 1},
        {"strength": 101},
        {"expression": "arbitrary Lua"},
    ],
)
def test_privacy_rejects_invalid_boundaries(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    a = args(tmp_path)
    a["privacy_blur"].update(change)
    with pytest.raises(ValueError):
        validate_finishing("set_clip_properties", a, [tmp_path])


def test_privacy_accepts_local_rectangle_and_refuses_extra_fields(
    tmp_path: Path,
) -> None:
    a = args(tmp_path)
    result = validate_finishing("set_clip_properties", a, [tmp_path])
    assert result["privacy_blur"]["start_frame"] == 1500
    assert result["expected_media_path"] == (tmp_path / "screen.mkv").as_posix()
    for change in ({"track_index": 2}, {"item_index": True}, {"item_index": 0}):
        with pytest.raises(ValueError):
            validate_finishing("set_clip_properties", dict(a, **change), [tmp_path])


def test_privacy_inspection_is_only_for_screen_v1(tmp_path: Path) -> None:
    a = args(tmp_path)
    a.pop("privacy_blur")
    a.update(track_type="video", track_index=1, inspect_privacy=True)
    assert validate_finishing("get_timeline_summary", a, [tmp_path])["inspect_privacy"]
    for change in ({"track_index": 2}, {"inspect_circle": True}):
        with pytest.raises(ValueError):
            validate_finishing("get_timeline_summary", dict(a, **change), [tmp_path])


def test_separated_privacy_intervals_preserve_visible_gaps(tmp_path: Path) -> None:
    a = args(tmp_path)
    a["privacy_blur"]["additional_intervals"] = [
        {"start_frame": 1800, "end_frame": 1900},
        {"start_frame": 3500, "end_frame": 4000},
    ]
    result = validate_finishing("set_clip_properties", a, [tmp_path])
    assert (
        result["privacy_blur"]["additional_intervals"]
        == a["privacy_blur"]["additional_intervals"]
    )


@pytest.mark.parametrize(
    "intervals",
    [
        None,
        {},
        [{"start_frame": 1700, "end_frame": 1800}],
        [{"start_frame": 1750, "end_frame": 1800}],
        [{"start_frame": True, "end_frame": 1800}],
        [{"start_frame": 1800, "end_frame": 4001}],
        [{"start_frame": 1800, "end_frame": 1900, "expression": "unsafe"}],
        [
            {"start_frame": 2000, "end_frame": 2100},
            {"start_frame": 1800, "end_frame": 1900},
        ],
        [{"start_frame": 1800, "end_frame": 1900}] * 64,
    ],
)
def test_invalid_additional_intervals_are_rejected(
    tmp_path: Path, intervals: Any
) -> None:
    a = args(tmp_path)
    a["privacy_blur"]["additional_intervals"] = intervals
    with pytest.raises(ValueError):
        validate_finishing("set_clip_properties", a, [tmp_path])


def test_privacy_batch_rejects_duplicate_or_invalid_targets(tmp_path: Path) -> None:
    item = args(tmp_path)
    name = item.pop("timeline_name")
    a = dict(timeline_name=name, privacy_batch=[item, dict(item, item_index=8)])
    result = validate_finishing("set_clip_properties", a, [tmp_path])
    assert len(result["privacy_batch"]) == 2
    for batch in (
        [],
        [item, item],
        [dict(item, item_index=False)],
        [item] * 101,
        [dict(item, expected_media_path=str(tmp_path / "missing.mkv"))],
        [dict(item, expression="unsafe")],
    ):
        with pytest.raises(ValueError):
            validate_finishing(
                "set_clip_properties", dict(a, privacy_batch=batch), [tmp_path]
            )


def test_mcp_privacy_batch_default_timeout_fits_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "session"
    prepare(root, [tmp_path])
    item = args(tmp_path)
    name = item.pop("timeline_name")
    observed: list[float] = []

    def request(
        self: LuaSnapshotClient, action: str, timeout_seconds: float, **kwargs: Any
    ) -> dict[str, Any]:
        assert 0 < timeout_seconds <= 120
        assert action == "set_clip_properties" and kwargs["confirm"] is True
        validate_finishing(action, kwargs["arguments"], [tmp_path])
        observed.append(timeout_seconds)
        return {"status": "completed"}

    monkeypatch.setattr(LuaSnapshotClient, "request", request)

    async def exercise() -> None:
        async with Client(create_server(root)) as client:
            result = await client.call_tool(
                "resolve_lua_privacy_blur_batch",
                {
                    "timeline_name": name,
                    "privacy_batch": [item],
                    "expected_project_id": "test-project",
                    "idempotency_key": "batch",
                    "confirm": True,
                },
            )
            assert not result.is_error

    asyncio.run(exercise())
    assert observed == [120]
