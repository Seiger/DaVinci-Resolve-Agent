-- Experimental asynchronous startup worker; installed by the local launcher.
-- Never execute this loop synchronously from a startup scriptlib.
local root = "__RUNTIME_ROOT__"
local session = "__SESSION__"
local expected_project = "__EXPECTED_PROJECT__"
local project_name = "__PROJECT_NAME__"
local ready_timeout = __READY_TIMEOUT__
local startup_context = _G.ResolveAgentStartupContext == session
_G.ResolveAgentStartupContext = nil
local last_guard_snapshot = nil
local function empty_media_list(value)
    if type(value) ~= "table" then return false end
    for key, item in pairs(value) do
        -- Observed in both empty native lists on Resolve Free 21.1/Windows.
        -- Ignore only this exact typed metadata entry, not arbitrary keys or
        -- array slots (including sparse/zero-indexed real items).
        if key ~= "__flags" or type(item) ~= "number" or item ~= 4194304 then
            return false
        end
    end
    return true
end
local function startup_placeholder(api, pm, project)
    -- Read every operand, even when an earlier predicate fails. Keep the exact
    -- values used for the decision rather than re-querying after refusal.
    local fields, failed = {}, {}
    local function read(key, fn)
        local ok, value = pcall(fn)
        local kind = type(value)
        local text = tostring(value)
        if kind == "table" then
            local count = 0
            for _ in pairs(value) do count = count + 1 end
            text = "count:" .. count
        elseif kind == "userdata" then text = "object" end
        text = text:gsub("[%c]", " "):sub(1, 256)
        if kind == "string" then text = string.format("%q", text) end
        fields[#fields + 1] = key .. "=" .. text .. "(" .. kind .. "," .. tostring(ok) .. ")"
        if not ok then failed[#failed + 1] = "READ_ERROR_" .. key; return nil end
        return value
    end
    local function check(code, passed)
        if not passed then failed[#failed + 1] = code end
    end
    local context = read("startup_context", function() return startup_context end)
    local configured = read("target_configured", function() return project_name ~= "" end)
    local page = read("page", function() return api:GetCurrentPage() end)
    local name = read("name", function() return project:GetName() end)
    local id = read("uuid", function() return project:GetUniqueId() end)
    local timelines = read("timelines", function() return project:GetTimelineCount() end)
    local folder = read("folder", function() return pm:GetCurrentFolder() end)
    local names = read("names", function() return pm:GetProjectListInCurrentFolder() end)
    local current_matches, target_matches = nil, nil
    if type(names) == "table" then
        current_matches, target_matches = 0, 0
        for _, value in pairs(names) do
            if value == name then current_matches = current_matches + 1 end
            if value == project_name then target_matches = target_matches + 1 end
        end
    end
    read("current_name_matches", function() return current_matches end)
    read("target_name_matches", function() return target_matches end)
    local pool = read("media_pool", function() return project:GetMediaPool() end)
    local media_root = read("media_root", function() return pool:GetRootFolder() end)
    local clips = read("clips", function() return media_root:GetClipList() end)
    local folders = read("subfolders", function() return media_root:GetSubFolderList() end)
    local function shape(label, value)
        if type(value) ~= "table" then return end
        local entries, count = {}, 0
        for key, item in pairs(value) do
            count = count + 1
            if count > 8 then entries[#entries + 1] = "truncated=true"; break end
            local key_type, item_type = type(key), type(item)
            local key_text = key_type == "string" or key_type == "number"
                or key_type == "boolean"
            key_text = key_text and tostring(key) or "object"
            local scalar = item_type == "string" or item_type == "number"
                or item_type == "boolean"
            local item_text = scalar and tostring(item) or "object"
            entries[#entries + 1] = "key=" .. string.format("%q", key_text:gsub("[%c]", " "):sub(1, 100))
                .. ",key_type=" .. key_type .. ",value_type=" .. item_type
                .. ",value=" .. string.format("%q", item_text:gsub("[%c]", " "):sub(1, 100))
        end
        fields[#fields + 1] = label .. "_shape=[" .. table.concat(entries, ";") .. "]"
    end
    shape("clips", clips)
    shape("subfolders", folders)
    check("CONTEXT_MISSING", context == true)
    check("TARGET_NOT_CONFIGURED", configured == true)
    check("PAGE_NOT_NIL", page == nil)
    check("NAME_NOT_PLACEHOLDER", name == "Untitled Project")
    check("UUID_INVALID", type(id) == "string" and id ~= "")
    check("TIMELINES_NOT_ZERO", timelines == 0)
    check("FOLDER_NOT_ROOT", folder == "")
    check("PROJECT_LIST_UNAVAILABLE", type(names) == "table")
    check("CURRENT_NAME_NOT_ABSENT", current_matches == 0)
    check("TARGET_NOT_UNIQUE", target_matches == 1)
    check("MEDIA_POOL_UNAVAILABLE", pool ~= nil)
    check("MEDIA_ROOT_UNAVAILABLE", media_root ~= nil)
    check("CLIPS_NOT_EMPTY_TABLE", empty_media_list(clips))
    check("SUBFOLDERS_NOT_EMPTY_TABLE", empty_media_list(folders))
    last_guard_snapshot = "STARTUP_PROJECT_CONFLICT reasons=" .. table.concat(failed, ",")
        .. " time=" .. tostring(os.time()) .. " " .. table.concat(fields, " ")
        .. " uuid_type=" .. type(id)
    return #failed == 0
end
local diagnostic_reported = false
local function describe_conflict(phase)
    if diagnostic_reported then return end
    diagnostic_reported = true
    local report = assert(last_guard_snapshot) .. " phase=" .. phase
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
    if not saved then
        -- Save a private preference snapshot to an explicit file, never the
        -- user's default preferences. Restore our temporary diagnostic key.
        local fu = fusion or fu
        local key = "Global.ResolveAgent.StartupDiagnostic." .. session
        local prior_ok, prior = pcall(function() return fu:GetPrefs(key) end)
        local exported = false
        if prior_ok then
            local ok = pcall(function()
                fu:SetPrefs(key, report)
                fu:SavePrefs(root .. "/startup-conflict.prefs")
                exported = bmd.fileexists(root .. "/startup-conflict.prefs") == true
            end)
            local restored = pcall(function()
                fu:SetPrefs(key, prior)
                assert(fu:GetPrefs(key) == prior, "Diagnostic preference restore failed")
            end)
            exported = ok and restored and exported
        end
        print("STARTUP_CONFLICT_PREFS_SAVED=" .. tostring(exported))
    end
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
                pcall(describe_conflict, "initial")
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
                local allowed = startup_placeholder(api, pm, before_load)
                local unchanged = before_load and before_load:GetUniqueId() == placeholder_id
                if not allowed or not unchanged then
                    last_guard_snapshot = last_guard_snapshot
                        .. " initial_uuid=" .. string.format("%q", placeholder_id)
                        .. " identity_unchanged=" .. tostring(unchanged == true)
                        .. (unchanged and "" or " additional_reason=IDENTITY_CHANGED")
                    pcall(describe_conflict, "before_load")
                    error("Startup placeholder changed; automatic switching refused")
                end
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
