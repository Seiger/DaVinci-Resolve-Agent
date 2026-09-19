"""Native batch geometry and strict inputs for multiple disjoint pauses."""

from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from providers.resolve.lua_editing import WriteReceipt
from providers.resolve.lua_ripple import validate_batch
from providers.resolve.lua_transport import LuaSnapshotClient, prepare


def test_long_batch_wait_is_bounded_and_keeps_idempotency(tmp_path: Path) -> None:
    """A completed receipt replays under the longer wait without another write."""
    media = tmp_path / "clip.mkv"
    media.touch()
    root = tmp_path / "session"
    prepare(root, [tmp_path])
    args = validate_batch(
        dict(
            timeline_name="source",
            ripple_batch=dict(
                name="copy",
                expected_timeline_start=0,
                expected_timeline_end=100,
                groups=[
                    dict(
                        index=1,
                        start=0,
                        end=100,
                        screen_source_start=0,
                        camera_source_start=0,
                        screen_path=str(media),
                        camera_path=str(media),
                        intervals=[[20, 40]],
                    )
                ],
            ),
        ),
        [tmp_path],
    )
    receipt = WriteReceipt(root, "same-cut", "set_clip_properties", "project", args)
    receipt.begin("a" * 32)
    receipt.complete({"status": "completed"})
    client = LuaSnapshotClient(root)
    kw: dict[str, Any] = dict(
        arguments=args,
        expected_project_id="project",
        idempotency_key="same-cut",
        confirm=True,
    )
    result = client.request("set_clip_properties", 600, **kw)
    assert result["replayed"] is True
    assert (root / "request.lua").read_text() == "return nil\n"
    with pytest.raises(ValueError, match="600"):
        client.request("set_clip_properties", 601, **kw)
    with pytest.raises(ValueError, match="120"):
        client.request("ping", 121)


@pytest.mark.parametrize("corrupt", [None, "source", "properties", "links"])
def test_group_edges_and_independent_audit(tmp_path: Path, corrupt: str | None) -> None:
    """Delete head, whole middle group, internal gap and tail without zero clips."""
    lua = import_module("lupa.lua51").LuaRuntime()
    lua.globals().MODE = "ok"
    lua.execute((Path(__file__).parent / "fixtures/ripple_timeline.lua").read_text())
    lua.execute("""
    a={timeline_name='source',ripple_batch={name='copy',allow_group_edges=true,
        expected_timeline_start=0,expected_timeline_end=400,groups={}}}
    local ranges={{{0,20}},{{100,200}},{{220,240}},{{370,400}}}
    for i=1,4 do
      a.ripple_batch.groups[i]={index=i,start=(i-1)*100,['end']=i*100,
        screen_source_start=(i-1)*200,camera_source_start=(i-1)*200,
        screen_path='screen',camera_path='cam',intervals=ranges[i]}
    end
    """)
    entry = lua.execute(Path("bridges/resolve/ResolveLuaRippleBatch.lua").read_text())
    entry(lua.globals().h, str(tmp_path), "a" * 32)(
        lua.globals().project, lua.globals().a
    )()
    lua.execute("""
    assert(source:GetEndFrame()==400 and target:GetEndFrame()==230)
    assert(#target.tracks[1]==4 and #target.tracks[2]==4 and #target.tracks[3]==4)
    assert(target.tracks[1][1].head==20 and target.tracks[1][1].s==0)
    assert(target.tracks[1][2].head==400 and target.tracks[1][2].s==80)
    assert(target.tracks[1][3].head==440 and target.tracks[1][3].s==100)
    assert(target.tracks[1][4].head==600 and target.tracks[1][4].s==160)
    h.timelines=function(_,n) return n=='source' and source or target end
    -- Audit must never duplicate, select, or edit anything.
    source.DuplicateTimeline=function() error('AUDIT_MUTATED') end
    source.GetIsTrackLocked=function() return nil end
    source.GetIsTrackEnabled=function() return nil end
    project.SetCurrentTimeline=function() error('AUDIT_MUTATED') end
    target.DeleteClips=function() error('AUDIT_MUTATED') end
    """)
    if corrupt == "source":
        lua.execute("target.tracks[2][3].head=441")
    elif corrupt == "properties":
        lua.execute("target.tracks[1][2].props.ZoomX=2")
    elif corrupt == "links":
        lua.execute("target.tracks[1][2].linked={}")
    audit = entry(lua.globals().h, str(tmp_path), "b" * 32, True)
    if corrupt:
        with pytest.raises(import_module("lupa.lua51").LuaError):
            audit(lua.globals().project, lua.globals().a)
    else:
        assert audit(lua.globals().project, lua.globals().a) == "ripple_verified"


def test_group_edges_require_opt_in_and_retain_content(tmp_path: Path) -> None:
    p = tmp_path / "clip.mkv"
    p.touch()
    group = dict(
        index=1,
        start=0,
        end=100,
        screen_source_start=0,
        camera_source_start=0,
        screen_path=str(p),
        camera_path=str(p),
        intervals=[[0, 100]],
    )
    plan: dict[str, Any] = dict(
        name="copy",
        expected_timeline_start=0,
        expected_timeline_end=200,
        groups=[group],
    )
    args = dict(timeline_name="source", ripple_batch=plan)
    with pytest.raises(ValueError):
        validate_batch(args, [tmp_path])
    plan["allow_group_edges"] = True
    assert validate_batch(args, [tmp_path])["ripple_batch"]["groups"][0][
        "intervals"
    ] == [[0, 100]]
    plan["allow_group_edges"] = 1
    with pytest.raises(ValueError):
        validate_batch(args, [tmp_path])
    plan["allow_group_edges"] = True
    plan["expected_timeline_end"] = 100
    with pytest.raises(ValueError, match="retain"):
        validate_batch(args, [tmp_path])


@pytest.mark.parametrize(
    "mode", ["ok", "locked", "wrong_source", "missing_group", "retimed"]
)
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
    if MODE=='retimed' then
      source.tracks[2][1].GetSourceEndTime=function() return 200/60 end
    end
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
