-- Fixed finishing operations. Preflight returns a mutation closure.
return function(api, root, helpers, shared)
    local check, timelines, allowed = helpers.check, helpers.timelines, helpers.allowed
    local normalized = helpers.normalized
    local jobs = shared.jobs -- Reload retains this running bridge's owned jobs.
    local function counts(timeline)
        local result = {video=0, audio=0, subtitle=0, first=-1, last=-1}
        for _,kind in ipairs({"video", "audio", "subtitle"}) do
            for track=1,timeline:GetTrackCount(kind) do
                for _,item in ipairs(timeline:GetItemListInTrack(kind, track) or {}) do
                    result[kind] = result[kind] + 1
                    if kind == "subtitle" then
                        result.first = result.first == -1 and item:GetStart() or math.min(result.first,item:GetStart())
                        result.last = math.max(result.last,item:GetEnd())
                    end
                end
            end
        end
        return result
    end
    local function summary(project, request)
        check(project:GetUniqueId() == request.project_id, "PROJECT_CHANGED")
        local timeline = timelines(project, request.arguments.timeline_name)
        check(timeline ~= nil, "TIMELINE_NOT_FOUND")
        local c = counts(timeline)
        local fps = tonumber(tostring(timeline:GetSetting("timelineFrameRate")):match("[%d.]+"))
        check(fps ~= nil, "VERIFY_FAILED")
        return string.format("timeline_%d_%d_%d_%d_%d_%d_%d_%d", c.video,c.audio,c.subtitle,
            timeline:GetStartFrame(),timeline:GetEndFrame(),c.first,c.last,math.floor(fps*1000+0.5))
    end
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
                -- DRP export is unavailable while Resolve renders. Allow short jobs
                -- to finish before the response export; never restart the job.
                local until_time = math.min(request.expires-1, os.time()+10)
                while project:IsRenderingInProgress() and os.time() < until_time do
                    bmd.wait(0.1)
                end
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
            local existing = counts(timeline)
            check(existing.video == 0 and existing.audio == 0, "SUBTITLE_REQUIRES_EMPTY_AV")
            for track=1,timeline:GetTrackCount("subtitle") do
                check(#(timeline:GetItemListInTrack("subtitle", track) or {}) == 0, "SUBTITLES_EXIST")
            end
            return function()
                check(project:SetCurrentTimeline(timeline) == true, "VERIFY_FAILED")
                local pool = project:GetMediaPool()
                local imported = pool:ImportMedia({a.subtitle_path})
                check(type(imported) == "table" and #imported == 1, "SUBTITLE_IMPORT_FAILED")
                local appended = pool:AppendToTimeline({{mediaPoolItem=imported[1], recordFrame=timeline:GetStartFrame()}})
                check(type(appended) == "table", "SUBTITLE_APPEND_FAILED")
                local until_time = math.min(request.expires, os.time()+5)
                local c = counts(timeline)
                while c.subtitle < a.cue_count and os.time() < until_time do
                    bmd.wait(0.1)
                    c = counts(timeline)
                end
                local fps = tonumber(tostring(timeline:GetSetting("timelineFrameRate")):match("[%d.]+"))
                check(fps and c.subtitle == a.cue_count, "SUBTITLE_COUNT_FAILED")
                check(math.abs(c.first-timeline:GetStartFrame()-a.first_start*fps) <= 1.1, "SUBTITLE_TIMING_FAILED")
                check(math.abs(c.last-timeline:GetStartFrame()-a.last_end*fps) <= 1.1, "SUBTITLE_TIMING_FAILED")
            end
        elseif action == "prepare_render" then
            check(timeline:GetEndFrame() > timeline:GetStartFrame(), "EMPTY_TIMELINE")
            return function()
                check(project:SetCurrentTimeline(timeline) == true, "VERIFY_FAILED")
                local previous_page = api:GetCurrentPage()
                check(api:OpenPage("deliver") == true, "DELIVER_PAGE_FAILED")
                bmd.wait(0.25)
                check(project:LoadRenderPreset("YouTube - 1080p") == true, "RENDER_PRESET_FAILED")
                check(project:SetCurrentRenderFormatAndCodec("MP4", "H264") == true, "RENDER_FORMAT_FAILED")
                check(project:SetCurrentRenderMode(1) == true, "RENDER_MODE_FAILED")
                local directory = root .. "/renders/" .. request.id
                check(project:SetRenderSettings({SelectAllFrames=true, TargetDir=directory,
                    CustomName="video", ExportVideo=true, ExportAudio=true,
                    FormatWidth=1920, FormatHeight=1080}) == true, "RENDER_BASE_SETTINGS_FAILED")
                check(project:SetRenderSettings({ExportSubtitle=true, SubtitleFormat="BurnIn"}) == true, "RENDER_SUBTITLE_SETTINGS_FAILED")
                check(project:SetRenderSettings({DataBurnIn="None"}) == true, "RENDER_BURNIN_SETTINGS_FAILED")
                -- Resolve Free rejects ReplaceExistingFilesInPlace in single-clip mode.
                -- Python reserves a fresh directory and rechecks it before start.
                local id = project:AddRenderJob()
                check(type(id) == "string" and #id <= 64 and id:match("^[%w%-]+$"), "RENDER_QUEUE_FAILED")
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
                if previous_page then api:OpenPage(previous_page) end
                return "job_" .. id
            end
        end
        error("INVALID_ARGUMENTS", 0)
    end
    return {preflight=preflight, status=status, summary=summary}
end
