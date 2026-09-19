"""Native Lua mock integration for cross-group ripple and source preservation."""

from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from providers.resolve.lua_ripple import validate_span


def test_span_validation(tmp_path: Path) -> None:
    p = tmp_path / "video.mkv"
    p.touch()
    groups = [
        dict(
            index=i + 1,
            start=i * 100,
            end=(i + 1) * 100,
            screen_source_start=i * 200,
            camera_source_start=i * 200,
            screen_path=str(p),
            camera_path=str(p),
        )
        for i in range(2)
    ]
    a: dict[str, Any] = dict(
        timeline_name="source",
        ripple_span=dict(
            name="copy",
            start_frame=40,
            end_frame=160,
            expected_timeline_start=0,
            expected_timeline_end=300,
            groups=groups,
        ),
    )
    assert validate_span(a, [tmp_path])["ripple_span"]["groups"][1]["index"] == 2
    for changes in (
        {"end_frame": 100},
        {"start_frame": True},
        {"name": "source"},
        {"groups": groups[::-1]},
        {"groups": groups[:1]},
    ):
        with pytest.raises(ValueError):
            validate_span(
                dict(a, ripple_span=dict(a["ripple_span"], **changes)), [tmp_path]
            )


@pytest.mark.parametrize("mode", ["ok", "wrong_source", "locked", "wrong_bounds"])
def test_native_span_plain_groups(tmp_path: Path, mode: str) -> None:
    lua = import_module("lupa.lua51").LuaRuntime()
    lua.globals().MODE = mode
    lua.execute(
        (Path(__file__).parent / "fixtures/ripple_timeline.lua").read_text(
            encoding="utf8"
        )
    )
    entry = lua.execute(
        Path("bridges/resolve/ResolveLuaRippleSpan.lua").read_text(encoding="utf8")
    )
    preflight = entry(lua.globals().h, str(tmp_path), "a" * 32)
    if mode != "ok":
        with pytest.raises(import_module("lupa.lua51").LuaError):
            preflight(lua.globals().project, lua.globals().a)
        assert lua.globals().target is None
    else:
        preflight(lua.globals().project, lua.globals().a)()
        lua.execute("""
        assert(source:GetEndFrame()==400 and target:GetEndFrame()==180)
        assert(#source.tracks[1]==4 and #target.tracks[1]==3)
        assert(target.tracks[1][1].s==0 and target.tracks[1][1].e==40)
        assert(target.tracks[1][2].s==40 and target.tracks[1][2].head==460)
        assert(target.tracks[1][3].s==80 and target.tracks[1][3].head==600)
        """)


def test_privacy_intervals_clip_to_retained_source_without_mutating_original() -> None:
    lua = import_module("lupa.lua51").LuaRuntime()
    lua.execute("h={};dofile=function() return function() return {} end end")
    entry = lua.execute(
        Path("bridges/resolve/ResolveLuaRippleSpan.lua").read_text(encoding="utf8")
    )
    lua.globals().preflight = entry(lua.globals().h, "test", "a" * 32)
    lua.execute("""
    for i=1,100 do
      local name,value=debug.getupvalue(preflight,i)
      if name=="preflight" then preflight=value;break end
    end
    for i=1,100 do
      local name,value=debug.getupvalue(preflight,i)
      if not name then break end
      if name=='clipped' then clipped=value end
    end
    assert(clipped)
    local original={ranges={{10,20},{30,50},{70,90}}}
    local result=clipped(original,15,60)
    assert(#result==3 and result[1][1]==0 and result[1][2]==5)
    assert(result[2][1]==15 and result[2][2]==35)
    assert(result[3][1]==55 and result[3][2]==60)
    assert(#clipped(original,50,20)==0)
    assert(original.ranges[1][1]==10 and original.ranges[3][2]==90)
    """)
