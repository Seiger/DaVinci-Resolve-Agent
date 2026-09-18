"""Execute the real loop in Lua with a simulated clock and Resolve API.

These tests cover lifetime and request guards, not live Resolve compatibility.
"""

import json
from importlib import import_module
from pathlib import Path

import pytest

from providers.resolve.lua_transport import prepare


def run_loop(tmp_path: Path, scenario: str) -> None:
    """Run a prepared bridge against deterministic Lua-owned API doubles."""
    root = tmp_path / "session"
    script = prepare(root).read_text(encoding="utf-8")
    lua = import_module("lupa").LuaRuntime()
    lua.execute(
        """
        now, tick, exports, edits, messages = 1000, 1, {}, 0, {}
        project_open, export_ok = true, true
        project = {GetName=function() return 'test' end}
        pm = {
          GetCurrentProject=function() if project_open then return project end end,
          ExportProject=function(_, name, path)
            table.insert(exports, path)
            return export_ok
          end
        }
        resolve = {GetProjectManager=function() return pm end}
        os.time = function() return now end
        print = function(s) table.insert(messages, s) end
        bmd = {wait=function()
          tick = tick + 1
          now = now + 7201
          assert(tick < 12, 'test loop did not terminate')
        end}
        function req(id, action)
          return {session=SESSION, id=string.rep(id,32), action=action,
                  expires=now+30}
        end
        dofile = function(path)
          if path:match('/editing.lua$') then
            return function() return function() edits=edits+1 end end
          end
          return next_request()
        end
        """
    )
    lua.globals().SESSION = json.loads((root / "session.json").read_text())["session"]
    setup, checks = scenario.split("-- CHECKS")
    lua.execute(setup)
    lua.execute(script)
    lua.execute(checks)


@pytest.mark.parametrize(
    "scenario",
    [
        """
        function next_request()
          if tick == 1 then return nil end
          if tick == 2 then return req('a','ping') end
          if tick == 3 then return req('b','stop') end
        end
        -- CHECKS
        assert(now > 1000+14400 and #exports == 2)
        assert(ResolveAgentLuaRunning == nil)
        assert(messages[#messages]:match('reason=acknowledged_stop'))
        """,
        """
        function next_request()
          if tick == 1 then saved=req('a','set_clip_properties'); return saved end
          if tick == 2 then saved.expires=now+30; return saved end
          if tick == 3 then local r=req('b','ping'); r.session='wrong'; return r end
          if tick == 4 then local r=req('c','ping'); r.expires=now-1; return r end
          if tick == 5 then return req('d','eval') end
          return req('e','stop')
        end
        -- CHECKS
        assert(edits == 1 and #exports == 2)
        assert(messages[#messages]:match('reason=acknowledged_stop'))
        """,
        """
        function next_request()
          if tick == 1 then project_open=false; return req('a','ping') end
          project_open=true
          return req('b','stop')
        end
        -- CHECKS
        assert(#exports == 1 and tick == 2)
        assert(ResolveAgentLuaRunning == nil)
        """,
        """
        function next_request()
          export_ok = tick > 1
          return req(tick == 1 and 'a' or 'b','stop')
        end
        -- CHECKS
        assert(#exports == 2 and tick == 2)
        assert(messages[#messages]:match('reason=acknowledged_stop'))
        """,
        """
        function next_request() return req('a','ping') end
        pm.GetCurrentProject=function() error('simulated API failure') end
        -- CHECKS
        assert(ResolveAgentLuaRunning == nil and #exports == 0)
        assert(messages[#messages-1]:match('reason=error; ok=false'))
        """,
        """
        ResolveAgentLuaRunning=true
        function next_request() error('must not run second loop') end
        -- CHECKS
        assert(ResolveAgentLuaRunning == true and #exports == 0)
        assert(messages[1]:match('already running'))
        """,
    ],
    ids=[
        "past-two-hours",
        "request-guards",
        "project-reopened",
        "stop-export-fails",
        "api-error-clears-guard",
        "duplicate-bootstrap",
    ],
)
def test_bridge_lifecycle(tmp_path: Path, scenario: str) -> None:
    run_loop(tmp_path, scenario)
