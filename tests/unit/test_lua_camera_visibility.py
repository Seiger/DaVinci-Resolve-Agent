"""Bounded camera hiding and Lua expression/readback guard tests."""

from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from providers.resolve.lua_camera_visibility import validate_camera_visibility


def args(root: Path) -> dict[str, Any]:
    p = root / "cam.mkv"
    p.touch()
    return dict(
        timeline_name="source",
        camera_visibility=dict(
            name="copy",
            expected_start=100,
            expected_end=1000,
            items=[
                dict(
                    index=3,
                    path=str(p),
                    start=200,
                    end=800,
                    intervals=[[250, 300], [500, 700]],
                )
            ],
        ),
    )


@pytest.mark.parametrize(
    "mode", ["same_name", "outside", "overlap", "bool", "duplicate", "extra"]
)
def test_invalid_visibility_plan(tmp_path: Path, mode: str) -> None:
    a = args(tmp_path)
    p = a["camera_visibility"]
    x = p["items"][0]
    if mode == "same_name":
        p["name"] = "source"
    elif mode == "outside":
        x["intervals"] = [[199, 300]]
    elif mode == "overlap":
        x["intervals"] = [[250, 400], [350, 500]]
    elif mode == "bool":
        x["index"] = True
    elif mode == "duplicate":
        p["items"].append(dict(x))
    else:
        x["lua"] = "arbitrary()"
    with pytest.raises(ValueError):
        validate_camera_visibility(a, [tmp_path])


def test_visibility_paths_and_valid_plan(tmp_path: Path) -> None:
    a = args(tmp_path)
    assert validate_camera_visibility(a, [tmp_path])["camera_visibility"]["items"][0][
        "intervals"
    ] == [[250, 300], [500, 700]]
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    with pytest.raises(ValueError):
        validate_camera_visibility(a, [allowed])


def inspection_runtime(mode: str) -> Any:
    lua = import_module("lupa.lua51").LuaRuntime()
    lua.globals().MODE = mode
    lua.execute("""
    function tool(name)
      return {GetAttrs=function() return {TOOLS_Name=name} end}
    end
    input=tool('MediaIn1');out=tool('MediaOut1');merge=tool('Merge1')
    mask=tool('Ellipse1');bg=tool('Background1')
    function pin(target)
      return {GetConnectedOutput=function()
        return {GetTool=function() return target end} end}
    end
    out.Input=pin(merge);merge.Foreground=pin(input);merge.Background=pin(bg);merge.EffectMask=pin(mask)
    bg.GetInput=function() return MODE=='opaque' and 1 or 0 end
    mask.GetInput=function(_,key) return key=='Center' and {0.5,0.5} or 0.43 end
    expression='iif((time >= 10 and time < 20) or (time >= 40 and time < 50), 0, 1)'
    if MODE=='bad_expression' then expression=expression..' + 1' end
    merge.Blend={GetExpression=function() return expression end}
    merge.GetInput=function(_,key,time)
      if MODE=='bad_sample' then return 1 end
      if time>=10 and time<20 or time>=40 and time<50 then return 0 else return 1 end
    end
    tools={MediaIn1=input,MediaOut1=out,Merge1=merge,Ellipse1=mask,Background1=bg}
    comp={FindTool=function(_,n) return tools[n] end,
      GetToolList=function() return tools end}
    item={GetFusionCompCount=function() return 1 end,
      GetFusionCompByIndex=function() return comp end,
      GetStart=function() return 1000 end,GetEnd=function() return 1100 end}
    h={check=function(v,e) if not v then error(e,0) end end}
    """)
    return lua


@pytest.mark.parametrize("mode", ["ok", "bad_expression", "bad_sample", "opaque"])
def test_lua_visibility_inspection(mode: str) -> None:
    lua = inspection_runtime(mode)
    module = lua.execute(
        Path("bridges/resolve/ResolveLuaCameraVisibility.lua").read_text(
            encoding="utf8"
        )
    )(lua.globals().h)
    if mode == "ok":
        assert module.inspect(lua.globals().item).startswith("visibility_2_")
    else:
        with pytest.raises(import_module("lupa.lua51").LuaError):
            module.inspect(lua.globals().item)


@pytest.mark.parametrize(
    "offset,length,expected",
    [(0, 15, [[10, 15]]), (15, 30, [[0, 5], [25, 30]]), (50, 20, [])],
)
def test_visibility_transfer_rebases_and_removes_empty_expression(
    offset: int, length: int, expected: list[list[int]]
) -> None:
    lua = inspection_runtime("ok")
    lua.execute("""
    merge.Blend.SetExpression=function(_,v) expression=v end
    merge.Blend.GetConnectedOutput=function() return nil end
    merge.SetInput=function(_,key,value) constant=value end
    merge.GetInput=function(_,key,time)
      if not expression then return constant or 1 end
      for lo,hi in expression:gmatch('time >= (%d+) and time < (%d+)') do
        if time>=tonumber(lo) and time<tonumber(hi) then return 0 end
      end
      return 1
    end
    """)
    module = lua.execute(
        Path("bridges/resolve/ResolveLuaCameraVisibility.lua").read_text(
            encoding="utf8"
        )
    )(lua.globals().h)
    ranges = module.capture(lua.globals().item)
    lua.globals().LENGTH = length
    lua.execute("item.GetEnd=function() return 1000+LENGTH end")
    result = module.transfer(lua.globals().item, ranges, offset, length)
    assert [[pair[1], pair[2]] for pair in result.values()] == expected
    assert (lua.globals().expression is None) == (not expected)
