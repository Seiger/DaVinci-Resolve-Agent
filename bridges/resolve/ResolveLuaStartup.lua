-- Experimental asynchronous startup worker; installed by the local launcher.
-- Never execute this loop synchronously from a startup scriptlib.
local root = "__RUNTIME_ROOT__"
local session = "__SESSION__"
local expected_project = "__EXPECTED_PROJECT__"
local project_name = "__PROJECT_NAME__"
local ready_timeout = __READY_TIMEOUT__
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
    local deadline = os.time() + ready_timeout
    while os.time() < deadline do
        local available, api, pm, project = pcall(function()
            local r = resolve or fu:GetResolve()
            local manager = r and r:GetProjectManager()
            return r, manager, manager and manager:GetCurrentProject()
        end)
        if not available then api, pm, project = nil, nil, nil end
        if project then
            assert(project:GetUniqueId() == expected_project,
                   "Another project is open; automatic switching refused")
        elseif pm and project_name ~= "" then
            local names = assert(pm:GetProjectListInCurrentFolder(),
                                 "Cannot enumerate the current project folder")
            local matches = 0
            for _, name in pairs(names) do
                if name == project_name then matches = matches + 1 end
            end
            assert(matches == 1, "Target project name missing or ambiguous in current folder")
            -- Recheck immediately before loading: never replace an open project.
            assert(not pm:GetCurrentProject(), "A project opened during startup")
            project = assert(pm:LoadProject(project_name), "LoadProject failed")
            local current = assert(pm:GetCurrentProject(), "Loaded project not current")
            assert(project:GetUniqueId() == expected_project
                   and current:GetUniqueId() == expected_project,
                   "Loaded project UUID mismatch; bridge not started")
        end
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
    error("Startup readiness timed out; no automatic retry")
end)
if not ok then print("Resolve Agent startup failed: " .. tostring(err)) end
