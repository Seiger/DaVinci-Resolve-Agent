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
    lua.execute(r"""
    serial=0
    function copy(x)
      if type(x)~='table' then return x end
      local y={};for k,v in pairs(x) do y[k]=copy(v) end;return y
    end
    function item(k,s,e,head)
      serial=serial+1
      local x={id=tostring(serial),s=s,e=e,head=head,props={ZoomX=1},linked={}}
      x.GetUniqueId=function(self) return self.id end
      x.GetStart=function(self) return self.s end
      x.GetEnd=function(self) return self.e end
      x.GetSourceStartTime=function(self) return self.head/60 end
      x.GetSourceEndTime=function(self) return (self.head+self.e-self.s)/60 end
      x.GetMediaPoolItem=function() return assets[k] end
      x.GetProperty=function(self) return copy(self.props) end
      x.SetProperty=function(self,p) self.props=copy(p);return true end
      x.GetFusionCompCount=function() return 0 end
      x.GetLinkedItems=function(self) return self.linked end
      x.GetClipEnabled=function() return true end
      x.GetMarkers=function() return {} end
      x.GetTakesCount=function() if k~=3 then return 0 end end
      return x
    end
    assets={}
    for k=1,3 do
      local path=k==2 and 'cam' or 'screen'
      assets[k]={GetUniqueId=function() return path end,
        GetClipProperty=function(_,key) return key=='FPS' and '60' or path end}
    end
    function timeline(name)
      local t={name=name,tracks={{},{},{}}}
      t.GetUniqueId=function(self) return self.name end
      t.GetStartFrame=function() return 0 end
      t.GetEndFrame=function(self) return self.tracks[1][#self.tracks[1]].e end
      t.GetTrackCount=function(_,k) return k=='video' and 2 or k=='audio' and 1 or 0 end
      t.GetSetting=function() return '60' end
      t.GetMarkers=function() return {} end
      t.GetIsTrackLocked=function() return MODE=='locked' end
      t.GetIsTrackEnabled=function() return true end
      t.GetItemListInTrack=function(self,kind,index)
        local list=self.tracks[kind=='audio' and 3 or index]
        table.sort(list,function(a,b) return a.s<b.s end);return list
      end
      t.SetClipsLinked=function(_,items)
        for _,x in ipairs(items) do
          x.linked={}
          for _,y in ipairs(items) do
            if x~=y then table.insert(x.linked,y) end
          end
        end
        return true
      end
      t.DuplicateTimeline=function(self,n)
        target=timeline(n)
        for i=1,#self.tracks[1] do
          local triple={}
          for k=1,3 do local x=self.tracks[k][i];local y=item(k,x.s,x.e,x.head)
            table.insert(target.tracks[k],y);triple[k]=y end
          target:SetClipsLinked(triple)
        end
        return target
      end
      t.DeleteClips=function(self,items,ripple)
        local ids={};local intervals={}
        for _,x in ipairs(items) do ids[x.id]=true;intervals[x.s]=x.e end
        for k=1,3 do
          local keep={}
          for _,x in ipairs(self.tracks[k]) do
            if not ids[x.id] then
              local shift=0
              if ripple then
                for lo,hi in pairs(intervals) do
                  if hi<=x.s then shift=shift+hi-lo end
                end
              end
              x.s=x.s-shift;x.e=x.e-shift;keep[#keep+1]=x
            end
          end
          self.tracks[k]=keep
        end
        return true
      end
      return t
    end
    source=timeline('source');current=source
    for i=1,4 do
      local triple={}
      for k=1,3 do local x=item(k,(i-1)*100,i*100,(i-1)*200);
        source.tracks[k][i]=x;triple[k]=x end
      source:SetClipsLinked(triple)
    end
    pool={AppendToTimeline=function(_,requests)
      local r=requests[1];local k=r.mediaType==2 and 3 or r.trackIndex
      local x=item(k,r.recordFrame,r.recordFrame+r.endFrame-r.startFrame,r.startFrame)
      table.insert(current.tracks[k],x);return {x}
    end}
    project={GetCurrentTimeline=function() return current end,
      SetCurrentTimeline=function(_,t) current=t;return true end,
      GetMediaPool=function() return pool end}
    h={check=function(x,e) if not x then error(e,0) end end,
      timelines=function(_,name) if name=='source' then return source end end,
      allowed=function() return true end,normalized=function(x) return x end}
    dofile=function() return function() return {} end end
    a={timeline_name='source',ripple_span={name='copy',start_frame=40,end_frame=260,
      expected_timeline_start=0,expected_timeline_end=400,groups={}}}
    for i=1,3 do a.ripple_span.groups[i]={index=i,start=(i-1)*100,['end']=i*100,
      screen_source_start=(i-1)*200,camera_source_start=(i-1)*200,
      screen_path='screen',camera_path='cam'} end
    if MODE=='wrong_source' then a.ripple_span.groups[2].screen_path='wrong' end
    if MODE=='wrong_bounds' then a.ripple_span.groups[2].start=101 end
    """)
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
