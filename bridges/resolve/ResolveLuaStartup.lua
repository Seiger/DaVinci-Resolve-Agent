-- Experimental asynchronous startup worker; installed by the local launcher.
-- Never execute this loop synchronously from a startup scriptlib.
local root = "__RUNTIME_ROOT__"
local session = "__SESSION__"
local expected_project = "__EXPECTED_PROJECT__"
local project_name = "__PROJECT_NAME__"
local ready_timeout = __READY_TIMEOUT__
local startup_context = _G.ResolveAgentStartupContext == session
_G.ResolveAgentStartupContext = nil
local function startup_placeholder(api, pm, project)
    local ok, safe = pcall(function()
        if not startup_context or project_name == "" or api:GetCurrentPage() ~= nil
            or project:GetName() ~= "Untitled Project" or project:GetTimelineCount() ~= 0
            or type(project:GetUniqueId()) ~= "string" or project:GetUniqueId() == ""
            or pm:GetCurrentFolder() ~= "" then return false end
        local target_matches = 0
        for _, name in pairs(pm:GetProjectListInCurrentFolder()) do
            if name == project:GetName() then return false end
            if name == project_name then target_matches = target_matches + 1 end
        end
        if target_matches ~= 1 then return false end
        local folder = project:GetMediaPool():GetRootFolder()
        local clips, folders = folder:GetClipList(), folder:GetSubFolderList()
        return type(clips) == "table" and next(clips) == nil
            and type(folders) == "table" and next(folders) == nil
    end)
    return ok and safe == true
end
local function describe_conflict(api, pm, project)
    -- Capture the state at refusal, not the state after a later manual load.
    -- Diagnostic failures must never weaken the no-switch guard.
    local function read(fn)
        local ok, value = pcall(fn)
        return ok and tostring(value) or "unavailable"
    end
    local function matches(name)
        local count = 0
        for _, value in pairs(pm:GetProjectListInCurrentFolder()) do
            if value == name then count = count + 1 end
        end
        return count
    end
    local report = "STARTUP_PROJECT_CONFLICT"
        .. " time=" .. tostring(os.time())
        .. " name=" .. string.format("%q", read(function() return project:GetName() end))
        .. " uuid=" .. string.format("%q", read(function() return project:GetUniqueId() end))
        .. " uuid_type=" .. read(function() return type(project:GetUniqueId()) end)
        .. " page=" .. string.format("%q", read(function() return api:GetCurrentPage() end))
        .. " folder=" .. string.format("%q", read(function() return pm:GetCurrentFolder() end))
        .. " timelines=" .. read(function() return project:GetTimelineCount() end)
        .. " current_name_matches=" .. read(function() return matches(project:GetName()) end)
        .. " target_name_matches=" .. read(function() return matches(project_name) end)
    print(report)
    local saved = false
    if io and type(io.open) == "function" then
        local ok, result = pcall(function()
            local file = assert(io.open(root .. "/startup-conflict.txt", "w"))
            local wrote = file:write(report .. "\n")
            local closed = file:close()
            return wrote ~= nil and closed ~= nil
        end)
        saved = ok and result == true
    end
    print("STARTUP_CONFLICT_FILE_SAVED=" .. tostring(saved))
end
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
        local placeholder_id = nil
        if project and project:GetUniqueId() ~= expected_project then
            if startup_placeholder(api, pm, project) then
                placeholder_id = project:GetUniqueId()
            else
                pcall(describe_conflict, api, pm, project)
                error("Another project is open; automatic switching refused")
            end
        end
        if pm and project_name ~= "" and (not project or placeholder_id) then
            local names = assert(pm:GetProjectListInCurrentFolder(),
                                 "Cannot enumerate the current project folder")
            local matches = 0
            for _, name in pairs(names) do
                if name == project_name then matches = matches + 1 end
            end
            assert(matches == 1, "Target project name missing or ambiguous in current folder")
            -- Recheck identity and the full empty startup signature immediately
            -- before LoadProject. Never close/save/delete the placeholder.
            local before_load = pm:GetCurrentProject()
            if placeholder_id then
                assert(before_load and before_load:GetUniqueId() == placeholder_id
                       and startup_placeholder(api, pm, before_load),
                       "Startup placeholder changed; automatic switching refused")
            else
                assert(not before_load, "A project opened during startup")
            end
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
