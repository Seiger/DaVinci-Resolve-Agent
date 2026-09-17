-- Fixed finishing operations. Preflight returns a mutation closure.
return function(api, root, helpers)
    local check, timelines, allowed = helpers.check, helpers.timelines, helpers.allowed
    local normalized = helpers.normalized
    local jobs = {} -- Jobs belong to this running bridge only.
    local function job(project, a)
        local owned = jobs[a.job_id]
        check(owned and owned.project == project:GetUniqueId(), "JOB_NOT_OWNED")
        return owned
    end
    local function status(project, request)
        check(project:GetUniqueId() == request.project_id, "PROJECT_CHANGED")
        job(project, request.arguments)
        local state = project:GetRenderJobStatus(request.arguments.job_id)
        check(type(state) == "table", "VERIFY_FAILED")
        local value = tostring(state.JobStatus):lower()
        if value == "complete" or value == "completed" then return "state_complete" end
        if value == "failed" or value == "cancelled" or value == "canceled" then return "state_failed" end
        if value == "rendering" or value == "in progress" then return "state_running" end
        if value == "ready" or value == "queued" then return "state_queued" end
        return "state_unknown"
    end
    local function preflight(project, request)
        local a, action = request.arguments, request.action
        if action == "start_render" then
            local owned = job(project, a)
            check(not owned.started, "JOB_ALREADY_STARTED")
            local unchanged = false
            for _, info in ipairs(project:GetRenderJobList() or {}) do
                if info.JobId == a.job_id then
                    check(type(info.TargetDir) == "string"
                        and normalized(info.TargetDir) == normalized(owned.directory)
                        and info.TimelineName == owned.name, "JOB_CHANGED")
                    unchanged = true
                end
            end
            check(unchanged, "JOB_CHANGED")
            return function()
                check(project:GetCurrentTimeline():GetUniqueId() == owned.timeline, "VERIFY_FAILED")
                owned.started = true -- Never resubmit an uncertain start.
                check(project:StartRendering({a.job_id}, false) == true, "VERIFY_FAILED")
            end
        end
        local timeline = timelines(project, a.timeline_name)
        check(timeline ~= nil, "TIMELINE_NOT_FOUND")
        if action == "set_clip_properties" then
            check(a.track_type == "video" or a.track_type == "audio", "INVALID_ARGUMENTS")
            local items = timeline:GetItemListInTrack(a.track_type, a.track_index) or {}
            local item = items[a.item_index]
            check(item ~= nil, "ITEM_NOT_FOUND")
            local media = item:GetMediaPoolItem()
            check(media and normalized(media:GetClipProperty("File Path")) == normalized(a.expected_media_path), "SOURCE_CHANGED")
            local limits = {ZoomX={0.1,4}, ZoomY={0.1,4}, Pan={-3840,3840}, Tilt={-2160,2160}, Opacity={0,100}, AudioVolume={-60,12}}
            check(type(a.properties) == "table" and next(a.properties) ~= nil, "INVALID_ARGUMENTS")
            for key,value in pairs(a.properties) do
                local bound = limits[key]
                check(bound and type(value) == "number" and value >= bound[1] and value <= bound[2], "INVALID_ARGUMENTS")
                check((a.track_type == "audio") == (key == "AudioVolume"), "INVALID_ARGUMENTS")
            end
            return function()
                check(project:SetCurrentTimeline(timeline) == true, "VERIFY_FAILED")
                local changes = {}
                for k,v in pairs(a.properties) do changes[k] = v end
                if a.track_type == "audio" then changes.AudioVolumeEnabled = true
                else
                    if changes.ZoomX or changes.ZoomY or changes.Pan or changes.Tilt then
                        changes.TransformEnabled = true
                    end
                    if changes.ZoomX or changes.ZoomY then changes.ZoomGang = false end
                    if changes.Opacity then changes.CompositeEnabled = true end
                end
                check(item:SetProperties(changes) == true, "VERIFY_FAILED")
                local result = item:GetProperties()
                for k,v in pairs(changes) do
                    check(type(v) == "number" and type(result[k]) == "number" and math.abs(result[k]-v) < 0.001 or result[k] == v, "VERIFY_FAILED")
                end
            end
        elseif action == "add_subtitles" then
            check(allowed(a.subtitle_path) and a.cue_count >= 1 and a.cue_count <= 2000, "INVALID_ARGUMENTS")
            for track=1,timeline:GetTrackCount("subtitle") do
                check(#(timeline:GetItemListInTrack("subtitle", track) or {}) == 0, "SUBTITLES_EXIST")
            end
            return function()
                check(project:SetCurrentTimeline(timeline) == true, "VERIFY_FAILED")
                local pool = project:GetMediaPool()
                local imported = pool:ImportMedia({a.subtitle_path})
                check(type(imported) == "table" and #imported == 1, "VERIFY_FAILED")
                local appended = pool:AppendToTimeline({imported[1]})
                check(type(appended) == "table", "VERIFY_FAILED")
                local count = 0
                local first, last
                for track=1,timeline:GetTrackCount("subtitle") do
                    for _,item in ipairs(timeline:GetItemListInTrack("subtitle", track) or {}) do
                        count = count + 1
                        first = math.min(first or item:GetStart(), item:GetStart())
                        last = math.max(last or item:GetEnd(), item:GetEnd())
                    end
                end
                local fps = tonumber(tostring(timeline:GetSetting("timelineFrameRate")):match("[%d.]+"))
                check(fps and first and last and count == a.cue_count, "VERIFY_FAILED")
                check(math.abs(first-timeline:GetStartFrame()-a.first_start*fps) <= 1.1, "VERIFY_FAILED")
                check(math.abs(last-timeline:GetStartFrame()-a.last_end*fps) <= 1.1, "VERIFY_FAILED")
            end
        elseif action == "prepare_render" then
            check(timeline:GetEndFrame() > timeline:GetStartFrame(), "EMPTY_TIMELINE")
            return function()
                check(project:SetCurrentTimeline(timeline) == true, "VERIFY_FAILED")
                check(project:LoadRenderPreset("YouTube - 1080p") == true, "VERIFY_FAILED")
                check(project:SetCurrentRenderFormatAndCodec("MP4", "H264") == true, "VERIFY_FAILED")
                check(project:SetCurrentRenderMode(1) == true, "VERIFY_FAILED")
                local directory = root .. "/renders/" .. request.id
                check(project:SetRenderSettings({SelectAllFrames=true, TargetDir=directory,
                    CustomName="video", ExportVideo=true, ExportAudio=true,
                    FormatWidth=1920, FormatHeight=1080, ExportSubtitle=true,
                    SubtitleFormat="BurnIn", DataBurnIn="None", ReplaceExistingFilesInPlace=false}) == true, "VERIFY_FAILED")
                local id = project:AddRenderJob()
                check(type(id) == "string" and #id <= 64 and id:match("^[%w%-]+$"), "VERIFY_FAILED")
                local found = false
                for _,info in ipairs(project:GetRenderJobList() or {}) do
                    if info.JobId == id then
                        check(normalized(info.TargetDir) == normalized(directory), "VERIFY_FAILED")
                        check(info.TimelineName == timeline:GetName(), "VERIFY_FAILED")
                        found = true
                    end
                end
                check(found, "VERIFY_FAILED")
                jobs[id] = {project=project:GetUniqueId(), timeline=timeline:GetUniqueId(),
                    name=timeline:GetName(), directory=directory, started=false}
                return "job_" .. id
            end
        end
        error("INVALID_ARGUMENTS", 0)
    end
    return {preflight=preflight, status=status}
end
