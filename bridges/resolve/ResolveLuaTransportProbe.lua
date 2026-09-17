-- Bounded diagnostic only; not an MCP transport or arbitrary-code endpoint.
-- The local operator supplies a directory containing a trusted canary.lua.
-- Two fixed tokens trigger read-only exports of the already-open project.
local output = "__PROBE_OUTPUT__"
local expected_project = "sMailer"
local pm = assert(resolve:GetProjectManager())
local project = assert(pm:GetCurrentProject())
assert(project:GetName() == expected_project, "Unexpected project")
assert(type(bmd.wait) == "function", "No cooperative wait")
local seen = {}
for _ = 1, 40 do
    local current = pm:GetCurrentProject()
    if current == nil or current:GetUniqueId() ~= project:GetUniqueId() then
        break
    end
    local ok, token = pcall(dofile, output .. "/canary.lua")
    if ok and (token == "PING_A" or token == "PING_B") and not seen[token] then
        assert(pm:ExportProject(expected_project, output .. "/" .. token .. ".drp", false), "Export failed")
        seen[token] = true
        print("TRANSPORT_ACK=" .. token)
    end
    if seen.PING_A and seen.PING_B then break end
    bmd.wait(0.25)
end
print("TRANSPORT_DONE=" .. tostring(seen.PING_A == true and seen.PING_B == true))
