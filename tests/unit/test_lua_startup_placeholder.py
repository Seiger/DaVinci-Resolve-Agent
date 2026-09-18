"""Lua 5.1 checks for the narrowly observed cold-start placeholder exception."""

import json
from importlib import import_module
from pathlib import Path

import pytest

from providers.resolve.lua_launcher import stage
from providers.resolve.lua_transport import prepare


@pytest.mark.parametrize(
    "mode",
    [
        "observed",
        "manual",
        "saved",
        "media",
        "folders",
        "timelines",
        "edit",
        "other-name",
        "other-folder",
        "missing-media-api",
        "ambiguous",
        "race-id",
        "race-page",
        "race-media",
        "missing-target",
        "uuid-mismatch",
        "literal-nil-page",
        "nil-clips",
        "clips-error",
        "shape-metadata",
        "shape-bounded",
    ],
)
def test_placeholder_is_not_a_general_untitled_bypass(
    tmp_path: Path, mode: str
) -> None:
    old = tmp_path / "old"
    prepare(old)
    hook = stage(tmp_path / "new", [], "expected", old, project_name="Target")
    lua = import_module("lupa.lua51").LuaRuntime()
    lua.globals().mode = mode
    if mode != "manual":
        lua.globals().ResolveAgentStartupContext = json.loads(
            (hook.parent / "session.json").read_text()
        )["session"]
    lua.execute("""
      reads, pages, loads, runs, exports = 0, 0, 0, 0, 0
      io=nil
      messages={}
      print=function(s) table.insert(messages,s) end
      bmd={wait=function() end, fileexists=function() return exports>0 end}
      root={
        GetClipList=function()
          if mode=='shape-metadata' then return {__flags=42} end
          if mode=='shape-bounded' then
            local list={}; for i=1,12 do list[i]=string.rep('x',200) end; return list
          end
          if mode=='nil-clips' then return nil end
          if mode=='clips-error' then error('fixture clip API error') end
          if mode=='media' or (mode=='race-media' and reads>1) then return {'clip'} end
          return {}
        end,
        GetSubFolderList=function()
          if mode=='shape-metadata' then return {__flags=42} end
          return mode=='folders' and {'folder'} or {}
        end
      }
      placeholder={
        GetName=function()
          return mode=='other-name' and 'User Project' or 'Untitled Project' end,
        GetUniqueId=function()
          return mode=='race-id' and reads>1 and 'changed' or 'initial' end,
        GetTimelineCount=function() return mode=='timelines' and 1 or 0 end,
        GetMediaPool=function()
          if mode=='missing-media-api' then return nil end
          return {GetRootFolder=function() return root end}
        end
      }
      target={GetName=function() return 'Target' end,
              GetUniqueId=function()
                return mode=='uuid-mismatch' and 'wrong' or 'expected' end}
      current=placeholder
      pm={
        GetCurrentProject=function() reads=reads+1; return current end,
        GetCurrentFolder=function() return mode=='other-folder' and 'Folder' or '' end,
        GetProjectListInCurrentFolder=function()
          if mode=='saved' then return {'Untitled Project','Target'} end
          if mode=='ambiguous' then return {'Target','Target'} end
          if mode=='missing-target' then return {} end
          return {'Target'}
        end,
        LoadProject=function(_,name) assert(name=='Target'); loads=loads+1
          current=target; return target end,
        ExportProject=function() exports=exports+1; return true end
      }
      resolve={GetProjectManager=function() return pm end,
        GetCurrentPage=function()
          pages=pages+1
          if mode=='literal-nil-page' then return 'nil' end
          if mode=='edit' or (mode=='race-page' and pages>1) then return 'edit' end
          return nil
        end}
      fusion={GetPrefs=function() return nil end,SetPrefs=function(_,k,v)
        fusion.GetPrefs=function() return v end end}
      dofile=function() runs=runs+1 end
    """)
    lua.execute((hook.parent / "startup.lua").read_text())
    assert lua.globals().loads == int(mode in {"observed", "uuid-mismatch"})
    assert lua.globals().runs == int(mode == "observed")
    assert lua.globals().exports == int(mode == "observed")
    assert lua.globals().ResolveAgentStartupContext is None
    reasons = {
        "manual": "CONTEXT_MISSING",
        "saved": "CURRENT_NAME_NOT_ABSENT",
        "media": "CLIPS_NOT_EMPTY_TABLE",
        "folders": "SUBFOLDERS_NOT_EMPTY_TABLE",
        "timelines": "TIMELINES_NOT_ZERO",
        "edit": "PAGE_NOT_NIL",
        "other-name": "NAME_NOT_PLACEHOLDER",
        "other-folder": "FOLDER_NOT_ROOT",
        "missing-media-api": "READ_ERROR_media_root",
        "ambiguous": "TARGET_NOT_UNIQUE",
        "race-id": "IDENTITY_CHANGED",
        "race-page": "PAGE_NOT_NIL",
        "race-media": "CLIPS_NOT_EMPTY_TABLE",
        "missing-target": "TARGET_NOT_UNIQUE",
        "literal-nil-page": "PAGE_NOT_NIL",
        "nil-clips": "CLIPS_NOT_EMPTY_TABLE",
        "clips-error": "READ_ERROR_clips",
        "shape-metadata": "CLIPS_NOT_EMPTY_TABLE",
        "shape-bounded": "CLIPS_NOT_EMPTY_TABLE",
    }
    if mode in reasons:
        output = "\n".join(lua.globals().messages.values())
        assert reasons[mode] in output
        assert "startup_context=" in output and "subfolders=" in output
        if mode == "literal-nil-page":
            assert 'page="nil"(string,true)' in output
        if mode.startswith("race-"):
            assert "phase=before_load" in output
        if mode == "shape-metadata":
            entry = 'key="__flags",key_type=string,value_type=number,value="42"'
            assert f"clips_shape=[{entry}]" in output
            assert f"subfolders_shape=[{entry}]" in output
        if mode == "shape-bounded":
            assert "truncated=true" in output
            assert "x" * 101 not in output
            assert output.count("key_type=number") == 8
