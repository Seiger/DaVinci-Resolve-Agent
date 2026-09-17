-- Manual compatibility probe, NOT the production bridge.
-- Install a copy with the three placeholders filled by the local operator.
-- Only the explicitly named test project may receive diagnostic bins.
-- No media import, timeline edit, render, subprocess or network access.
local output = "__PROBE_OUTPUT__"
local run_id = "__PROBE_RUN_ID__"
local expected_project = "DaVinci Agent M4 Test"
local challenge = "__PROBE_CHALLENGE__"
local rows = {"run_id=" .. run_id}

local function record(key, value)
    rows[#rows + 1] = key .. "=" .. tostring(value)
end

local function attempt(fn)
    local ok, value = pcall(fn)
    return ok and value == true
end

local app = resolve
if app == nil and type(Resolve) == "function" then
    local ok, value = pcall(Resolve)
    if ok then app = value end
end
if app == nil and bmd ~= nil then
    local ok, value = pcall(function() return bmd.scriptapp("Resolve") end)
    if ok then app = value end
end
record("resolve_api", app ~= nil)

local read_ok = attempt(function()
    local file = assert(io.open(output .. "/challenge.txt", "rb"))
    local value = file:read("*a")
    file:close()
    return value == challenge
end)
record("io_read", read_ok)

local function write_report()
    return attempt(function()
        local file = assert(io.open(output .. "/report.txt", "wb"))
        assert(file:write(table.concat(rows, "\n") .. "\n"))
        assert(file:close())
        return true
    end)
end

local write_ok = write_report()
record("io_write", write_ok)
record("require_present", type(require) == "function")
record("dofile_present", type(dofile) == "function")

local manager, project
local api_ok = attempt(function()
    manager = app:GetProjectManager()
    project = manager:GetCurrentProject()
    record("resolve_version", app:GetVersionString())
    record("project_open", project ~= nil)
    return manager ~= nil
end)
record("project_api", api_ok)

-- Export uses the documented Resolve API, independently of Lua file I/O.
-- Keep the original test project backed up before adding visible probe results.
if api_ok and project ~= nil and project:GetName() == expected_project then
    local pool = project:GetMediaPool()
    local root = pool:GetRootFolder()
    local folder_name = "Agent Lua Probe " .. run_id
    for _, child in ipairs(root:GetSubFolderList() or {}) do
        if child:GetName() == folder_name then
            record("replay", true)
            write_report()
            return
        end
    end
    local exported = attempt(function()
        return manager:ExportProject(
            expected_project, output .. "/before.drp", false
        )
    end)
    record("project_export", exported)
    if exported then
        local bins_ok = attempt(function()
            local folder = assert(pool:AddSubFolder(root, folder_name))
            for _, row in ipairs(rows) do
                assert(pool:AddSubFolder(folder, row))
            end
            return true
        end)
        record("diagnostic_bins", bins_ok)
        if bins_ok then
            record("project_save", attempt(function() return manager:SaveProject() end))
            record("result_export", attempt(function()
                return manager:ExportProject(
                    expected_project, output .. "/result.drp", false
                )
            end))
        end
    end
else
    record("test_project_guard", false)
end

write_report()
pcall(function() print(table.concat(rows, "\n")) end)
