-- Bounded synchronized assembly. One shared cut-map drives V1/V2/A1.
return function(h)
    local check = h.check
    local function integer(n) return type(n)=="number" and n==math.floor(n) and n>=0 end
    return function(project, a)
        local timeline = h.timelines(project, a.timeline_name)
        check(timeline ~= nil, "TIMELINE_NOT_FOUND")
        check(type(a.sync_groups)=="table" and #a.sync_groups>=1 and #a.sync_groups<=25, "INVALID_ARGUMENTS")
        local pool, fps = project:GetMediaPool(), tonumber(timeline:GetSetting("timelineFrameRate"))
        check(fps ~= nil, "SYNC_FPS_MISMATCH")
        local groups = {}
        local record = timeline:GetStartFrame()
        for _,kind in ipairs({"video","audio"}) do
            for track=1,timeline:GetTrackCount(kind) do
                for _,item in ipairs(timeline:GetItemListInTrack(kind,track) or {}) do
                    record=math.max(record,item:GetEnd())
                end
            end
        end
        for _,g in ipairs(a.sync_groups) do
            check(h.allowed(g.screen_path) and h.allowed(g.camera_path)
                and h.normalized(g.screen_path)~=h.normalized(g.camera_path), "MEDIA_NOT_ALLOWED")
            local screen, camera = h.find_asset(pool,g.screen_path), h.find_asset(pool,g.camera_path)
            check(screen and camera, "ASSET_NOT_FOUND")
            local full=g.camera_delay_frames~=nil
            check(not full or integer(g.camera_delay_frames) and g.camera_delay_frames<=600, "INVALID_RANGE")
            local ss,cs=full and 0 or g.screen_start_frame,full and 0 or g.camera_start_frame
            local sn=full and tonumber(screen:GetClipProperty("Frames")) or g.frame_count
            local cn=full and tonumber(camera:GetClipProperty("Frames")) or g.frame_count
            check(integer(ss) and integer(cs) and integer(sn) and sn>0 and integer(cn) and cn>0, "INVALID_RANGE")
            for _,pair in ipairs({{screen,ss,sn},{camera,cs,cn}}) do
                local frames=tonumber(pair[1]:GetClipProperty("Frames"))
                local source_fps=tonumber(pair[1]:GetClipProperty("FPS"))
                check(source_fps and math.abs(source_fps-fps)<0.001, "SYNC_FPS_MISMATCH")
                check(frames and pair[2]+pair[3]<=frames, "INVALID_RANGE")
            end
            groups[#groups+1]={screen=screen,camera=camera,screen_start=ss,
                camera_start=cs,screen_count=sn,camera_count=cn,record=record,
                delay=full and g.camera_delay_frames or 0,full=full}
            record=record+math.max(sn,cn+(full and g.camera_delay_frames or 0))
        end
        -- Returned closure runs only after the common saved DRP backup.
        return function()
            check(project:SetCurrentTimeline(timeline)==true, "VERIFY_FAILED")
            while timeline:GetTrackCount("video")<2 do
                check(timeline:AddTrack("video")==true, "SYNC_TRACK_FAILED")
            end
            while timeline:GetTrackCount("audio")<1 do
                check(timeline:AddTrack("audio","stereo")==true, "SYNC_TRACK_FAILED")
            end
            for _,g in ipairs(groups) do
                local specs={
                    {asset=g.screen,source=g.screen_start,kind="video",track=1,media=1,count=g.screen_count,record=g.record},
                    {asset=g.camera,source=g.camera_start,kind="video",track=2,media=1,count=g.camera_count,record=g.record+g.delay},
                    {asset=g.screen,source=g.screen_start,kind="audio",track=1,media=2,count=g.screen_count,record=g.record},
                }
                local linked={}
                for _,s in ipairs(specs) do
                    local info={mediaPoolItem=s.asset,
                        -- Resolve 21.1 live readback uses an exclusive source end.
                        -- Public start/count describes inclusive [start,start+count-1].
                        mediaType=s.media,trackIndex=s.track,recordFrame=s.record}
                    if not g.full then info.startFrame=s.source;info.endFrame=s.source+s.count end
                    local result=pool:AppendToTimeline({info})
                    check(type(result)=="table" and #result==1, "SYNC_INSERT_FAILED")
                    local item=result[1]
                    local track=item:GetTrackTypeAndIndex()
                    check(type(track)=="table" and track[1]==s.kind and track[2]==s.track, "SYNC_TRACK_READBACK_FAILED")
                    check(item:GetMediaPoolItem():GetUniqueId()==s.asset:GetUniqueId(), "SYNC_SOURCE_READBACK_FAILED")
                    check(item:GetStart()==s.record and item:GetEnd()==s.record+s.count, "SYNC_POSITION_READBACK_FAILED")
                    local actual_end=item:GetSourceEndFrame()
                    local expected_end=s.source+s.count-(g.full and 1 or 0)
                    -- Whole MKV duration may include one frame of AAC/container
                    -- padding beyond the native video out-point. No source trim
                    -- was requested; allow only this observed one-frame padding.
                    check(item:GetSourceStartFrame()==s.source and
                        (actual_end==expected_end or g.full and actual_end==expected_end-1), "SYNC_RANGE_READBACK_FAILED")
                    linked[#linked+1]=item
                end
                check(timeline:SetClipsLinked(linked,true)==true, "SYNC_LINK_FAILED")
                for _,item in ipairs(linked) do
                    local ids={}
                    for _,other in ipairs(item:GetLinkedItems() or {}) do ids[other:GetUniqueId()]=true end
                    for _,other in ipairs(linked) do
                        check(other:GetUniqueId()==item:GetUniqueId() or ids[other:GetUniqueId()], "SYNC_LINK_READBACK_FAILED")
                    end
                end
            end
        end
    end
end
