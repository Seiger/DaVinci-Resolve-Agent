"""Native batch geometry and strict inputs for multiple disjoint pauses."""

from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from providers.resolve.lua_ripple import validate_batch


@pytest.mark.parametrize("mode", ["ok", "locked", "wrong_source", "missing_group"])
def test_native_disjoint_batch(tmp_path: Path, mode: str) -> None:
    lua = import_module("lupa.lua51").LuaRuntime()
    lua.globals().MODE = mode
    lua.execute(
        (Path(__file__).parent / "fixtures/ripple_timeline.lua").read_text(
            encoding="utf8"
        )
    )
    lua.execute("""
    a.ripple_batch={name='copy',expected_timeline_start=0,expected_timeline_end=400,groups={}}
    for _,i in ipairs({1,4}) do
      a.ripple_batch.groups[#a.ripple_batch.groups+1]={index=i,start=(i-1)*100,['end']=i*100,
        screen_source_start=(i-1)*200,camera_source_start=(i-1)*200,
        screen_path='screen',camera_path='cam',intervals={{(i-1)*100+30,(i-1)*100+50}}}
    end
    if MODE=='wrong_source' then a.ripple_batch.groups[1].screen_path='wrong' end
    if MODE=='missing_group' then a.ripple_batch.groups[2].index=5 end
    a.ripple_span=nil
    """)
    entry = lua.execute(
        Path("bridges/resolve/ResolveLuaRippleBatch.lua").read_text(encoding="utf8")
    )(lua.globals().h, str(tmp_path), "a" * 32)
    if mode != "ok":
        with pytest.raises(import_module("lupa.lua51").LuaError):
            entry(lua.globals().project, lua.globals().a)
        assert lua.globals().target is None
    else:
        entry(lua.globals().project, lua.globals().a)()
        lua.execute("""
        assert(source:GetEndFrame()==400 and target:GetEndFrame()==360)
        assert(#target.tracks[1]==6 and #target.tracks[2]==6 and #target.tracks[3]==6)
        assert(target.tracks[1][2].head==50 and target.tracks[1][2].s==30)
        assert(target.tracks[1][6].head==650 and target.tracks[1][6].s==310)
        """)


def test_batch_validation(tmp_path: Path) -> None:
    p = tmp_path / "clip.mkv"
    p.touch()
    g = dict(
        index=2,
        start=100,
        end=300,
        screen_source_start=400,
        camera_source_start=399,
        screen_path=str(p),
        camera_path=str(p),
        intervals=[[120, 140], [220, 250]],
    )
    a: dict[str, Any] = dict(
        timeline_name="source",
        ripple_batch=dict(
            name="copy",
            expected_timeline_start=0,
            expected_timeline_end=300,
            groups=[g],
        ),
    )
    assert (
        validate_batch(a, [tmp_path])["ripple_batch"]["groups"][0]["intervals"]
        == g["intervals"]
    )
    for bad in (
        [[100, 140]],
        [[120, 140], [130, 150]],
        [[True, 140]],
        [[120, 300]],
        [[120.5, 140]],
    ):
        with pytest.raises(ValueError):
            validate_batch(
                dict(
                    a,
                    ripple_batch=dict(
                        a["ripple_batch"], groups=[dict(g, intervals=bad)]
                    ),
                ),
                [tmp_path],
            )


@pytest.mark.parametrize("mode", ["ok", "changed_head", "changed_properties"])
def test_existing_single_cut_audit(tmp_path: Path, mode: str) -> None:
    lua = import_module("lupa.lua51").LuaRuntime()
    lua.globals().MODE = "ok"
    lua.execute(
        (Path(__file__).parent / "fixtures/ripple_timeline.lua").read_text(
            encoding="utf8"
        )
    )
    lua.execute("""
    a={timeline_name='source',ripple_cut={name='copy',start_frame=30,end_frame=50,
      expected_timeline_start=0,expected_timeline_end=400,expected_group_start=0,
      expected_group_end=100,group_index=1,screen_path='screen',camera_path='cam',
      screen_source_start=0,camera_source_start=0}}
    """)
    entry = lua.execute(
        Path("bridges/resolve/ResolveLuaRipple.lua").read_text(encoding="utf8")
    )
    entry(lua.globals().h, str(tmp_path), "a" * 32)(
        lua.globals().project, lua.globals().a
    )()
    lua.execute("h.timelines=function(_,n) return n=='source' and source or target end")
    if mode == "changed_head":
        lua.execute("a.ripple_cut.camera_source_start=1")
    elif mode == "changed_properties":
        lua.execute("target.tracks[1][1].props.ZoomX=2")
    audit = entry(lua.globals().h, str(tmp_path), "b" * 32, True)
    if mode == "ok":
        assert audit(lua.globals().project, lua.globals().a) == "ripple_verified"
    else:
        with pytest.raises(import_module("lupa.lua51").LuaError):
            audit(lua.globals().project, lua.globals().a)
