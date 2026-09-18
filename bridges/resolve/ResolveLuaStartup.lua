-- Experimental asynchronous startup worker; installed by the local launcher.
-- Never execute this loop synchronously from a startup scriptlib.
local root = "__RUNTIME_ROOT__"
local session = "__SESSION__"
local expected_project = "__EXPECTED_PROJECT__"
local ok, err = pcall(function()
    local fu = assert(fusion or fu, "Fusion context unavailable")
    assert(type(bmd.wait) == "function" and type(bmd.fileexists) == "function",
           "Startup helpers unavailable")
    local key = "Global.ResolveAgent.Startup." .. session
    if fu:GetPrefs(key) then return end
    local owner = tostring({})
    fu:SetPrefs(key, owner)
    bmd.wait(0.3)
    if fu:GetPrefs(key) ~= owner then return end
    -- Never restart a consumed session after application exit or Lua failure:
    -- the old in-memory replay set and render job ownership would be lost.
    local marker = root .. "/startup-consumed.drp"
    if bmd.fileexists(marker) then
        print("Resolve Agent startup refused: session already consumed")
        return
    end
    if _G.ResolveAgentLuaRunning then return end
    print("Resolve Agent startup waiting for the configured project")
    while true do
        local api = resolve or fu:GetResolve()
        local pm = api and api:GetProjectManager()
        local project = pm and pm:GetCurrentProject()
        if project and project:GetUniqueId() == expected_project then
            assert(pm:ExportProject(project:GetName(), marker, false),
                   "Cannot record startup consumption")
            assert(bmd.fileexists(marker), "Startup marker missing")
            resolve = api
            dofile(root .. "/bridge.lua")
            return -- no automatic restart, even after a bridge error
        end
        bmd.wait(0.5)
    end
end)
if not ok then print("Resolve Agent startup failed: " .. tostring(err)) end
