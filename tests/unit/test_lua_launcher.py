"""Offline launcher and native-Lua worker contracts; no Resolve is launched."""

import json
import subprocess
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from providers.resolve import lua_launcher as launcher
from providers.resolve.lua_transport import prepare


def staged(tmp_path: Path) -> Path:
    """Create a fixture with a clean preceding session."""
    old = tmp_path / "old"
    prepare(old)
    return launcher.stage(tmp_path / "new", [], "expected", old)


def test_stage_and_install_are_separate(tmp_path: Path) -> None:
    hook = staged(tmp_path)
    assert hook.is_file()
    scripts = tmp_path / "Scripts"
    assert not scripts.exists()
    target = launcher.install_hook(hook, scripts)
    assert "Execute" in target.read_text()
    target.write_text("-- someone else's file")
    with pytest.raises(ValueError, match="unmanaged"):
        launcher.install_hook(hook, scripts)
    assert target.read_text() == "-- someone else's file"


def test_pending_receipt_blocks_rotation(tmp_path: Path) -> None:
    old = tmp_path / "old"
    prepare(old)
    (old / "receipts").mkdir()
    (old / "receipts/test.json").write_text(json.dumps({"status": "pending"}))
    with pytest.raises(ValueError, match="uncertain"):
        launcher.stage(tmp_path / "new", [], "expected", old)
    assert not (tmp_path / "new").exists()


def test_running_resolve_blocks_launch(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(launcher, "resolve_running", lambda: True)
    with pytest.raises(ValueError, match="already running"):
        launcher.launch(
            tmp_path / "base",
            tmp_path / "old",
            [],
            "id",
            tmp_path / "Resolve.exe",
            tmp_path / "Scripts",
        )
    assert not (tmp_path / "Scripts").exists()
    assert not (tmp_path / "base/launcher.lock").exists()


def test_launcher_rotates_tokens_and_retains_previous(
    tmp_path: Path, monkeypatch: Any
) -> None:
    old = tmp_path / "old"
    prepare(old)
    executable = tmp_path / "Resolve.exe"
    executable.touch()
    calls: list[Any] = []
    monkeypatch.setattr(launcher, "resolve_running", lambda: False)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(a))
    base, scripts = tmp_path / "base", tmp_path / "Scripts"
    first = launcher.launch(base, old, [], "expected", executable, scripts)
    second = launcher.launch(base, old, [], "expected", executable, scripts)
    assert len(calls) == 2 and first != second
    tokens = [
        json.loads((p / "session.json").read_text())["session"]
        for p in (old, first, second)
    ]
    assert len(set(tokens)) == 3
    assert json.loads((second / "startup.json").read_text())["previous_runtime"] == str(
        first
    )
    (second / "receipts").mkdir()
    (second / "receipts/pending.json").write_text('{"status":"pending"}')
    with pytest.raises(ValueError, match="uncertain"):
        launcher.launch(base, old, [], "expected", executable, scripts)
    assert len(calls) == 2


@pytest.mark.parametrize("mode", ["normal", "consumed", "owned", "export-failure"])
def test_startup_waits_and_runs_once(tmp_path: Path, mode: str) -> None:
    hook = staged(tmp_path)
    lua = import_module("lupa.lua51").LuaRuntime()
    lua.globals().mode = mode
    lua.execute("""
      waits, runs, exports, messages = 0, 0, 0, {}
      prefs, marker = nil, mode == 'consumed'
      if mode == 'owned' then prefs = 'another-worker' end
      print=function(s) table.insert(messages,s) end
      bmd={
        wait=function() waits=waits+1; assert(waits<10, 'unexpected wait') end,
        fileexists=function() return marker end
      }
      project={
        GetName=function() return 'test' end,
        GetUniqueId=function() return 'expected' end
      }
      pm={
        GetCurrentProject=function() if waits>2 then return project end end,
        ExportProject=function()
          exports=exports+1
          marker=mode~='export-failure'
          return marker
        end
      }
      resolve={GetProjectManager=function() return pm end}
      fusion={
        GetPrefs=function() return prefs end,
        SetPrefs=function(_,key,value) prefs=value end,
        GetResolve=function() return resolve end
      }
      dofile=function() runs=runs+1 end
    """)
    worker = (hook.parent / "startup.lua").read_text(encoding="utf-8")
    lua.execute(worker)
    lua.execute(worker)  # duplicate invocation must not launch another loop
    expected = 1 if mode == "normal" else 0
    assert lua.globals().runs == expected
    if mode == "normal":
        assert lua.globals().waits == 3
        assert lua.globals().exports == 1


def test_scriptlib_dispatches_without_waiting(tmp_path: Path) -> None:
    hook = staged(tmp_path)
    lua = import_module("lupa.lua51").LuaRuntime()
    lua.execute("""
      calls=0
      fusion={Execute=function(_,command)
        calls=calls+1; assert(command:match('dofile')) end}
      bmd={wait=function() error('startup must not block') end}
    """)
    lua.execute(hook.read_text())
    lua.execute(hook.read_text())
    assert lua.globals().calls == 1


@pytest.mark.parametrize(
    "mode",
    [
        "load",
        "already-open",
        "other-open",
        "missing",
        "ambiguous",
        "uuid-mismatch",
        "load-fails",
        "api-unavailable",
        "opened-during-check",
    ],
)
def test_project_selection(tmp_path: Path, mode: str) -> None:
    old = tmp_path / "old"
    prepare(old)
    hook = launcher.stage(
        tmp_path / "new",
        [],
        "expected",
        old,
        project_name="Target",
        ready_timeout_seconds=3,
    )
    lua = import_module("lupa.lua51").LuaRuntime()
    lua.globals().mode = mode
    lua.execute("""
      clock, loads, runs, exports, reads = 0, 0, 0, 0, 0
      messages = {}
      print=function(s) table.insert(messages,s) end
      os.time=function() return clock end
      bmd={wait=function() clock=clock+1 end,
           fileexists=function() return exports>0 end}
      project={GetUniqueId=function() return 'expected' end,
               GetName=function() return 'Target' end}
      other={GetUniqueId=function() return 'other' end}
      if mode=='already-open' then current=project end
      if mode=='other-open' then current=other end
      pm={
        GetCurrentProject=function()
          reads=reads+1
          if mode=='opened-during-check' and reads>1 then return other end
          return current
        end,
        GetProjectListInCurrentFolder=function()
          if mode=='missing' then return {} end
          if mode=='ambiguous' then return {'Target','Target'} end
          return {'Target'}
        end,
        LoadProject=function(_,name)
          assert(name=='Target'); loads=loads+1
          if mode=='load-fails' then return nil end
          current=mode=='uuid-mismatch' and other or project
          return current
        end,
        ExportProject=function() exports=exports+1; return true end
      }
      resolve={GetProjectManager=function()
        if mode=='api-unavailable' then return nil end
        return pm
      end}
      fusion={GetPrefs=function() return nil end,SetPrefs=function(_,k,v)
        fusion.GetPrefs=function() return v end end}
      dofile=function() runs=runs+1 end
    """)
    lua.execute((hook.parent / "startup.lua").read_text())
    succeeds = mode in {"load", "already-open"}
    assert lua.globals().runs == int(succeeds)
    assert lua.globals().exports == int(succeeds)
    assert lua.globals().loads == int(mode in {"load", "uuid-mismatch", "load-fails"})
    if mode == "api-unavailable":
        assert "readiness timed out" in lua.globals().messages[2]
