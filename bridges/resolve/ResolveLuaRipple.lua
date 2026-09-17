-- Narrow first-group ripple on a duplicate. Never rebuild downstream clips.
return function(h)
    local check=h.check
    local tracks={{"video",1},{"video",2},{"audio",1}}
    local function equal(a,b)
        if type(a)~=type(b) then return false end
        if type(a)~="table" then return a==b end
        for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
        for k in pairs(b) do if a[k]==nil then return false end end
        return true
    end
    local function links(item)
        local ids={}
        for _,v in ipairs(item:GetLinkedItems() or {}) do ids[v:GetUniqueId()]=true end
        return ids
    end
    local function snapshot(t)
        local result={}
        for k,s in ipairs(tracks) do
            result[k]={}
            for i,item in ipairs(t:GetItemListInTrack(s[1],s[2]) or {}) do
                local media=item:GetMediaPoolItem()
                check(media~=nil,"RIPPLE_UNSUPPORTED_LAYOUT")
                result[k][i]={id=item:GetUniqueId(),start=item:GetStart(),finish=item:GetEnd(),
                    source_start=item:GetSourceStartTime(),source_end=item:GetSourceEndTime(),
                    media=media:GetUniqueId(),properties=item:GetProperty(),
                    fusion=item:GetFusionCompCount(),links=links(item),enabled=item:GetClipEnabled()}
            end
        end
        return result
    end
    local function layout_equal(a,b,identity)
        if not identity then
            a={start=a.start,finish=a.finish,source_start=a.source_start,source_end=a.source_end,
                media=a.media,properties=a.properties,fusion=a.fusion,enabled=a.enabled}
            b={start=b.start,finish=b.finish,source_start=b.source_start,source_end=b.source_end,
                media=b.media,properties=b.properties,fusion=b.fusion,enabled=b.enabled}
        end
        return equal(a,b)
    end
    return function(project,a)
        local c=a.ripple_cut
        check(type(c)=="table","INVALID_ARGUMENTS")
        local source=h.timelines(project,a.timeline_name)
        check(source~=nil,"TIMELINE_NOT_FOUND")
        check(h.timelines(project,c.name)==nil,"NAME_EXISTS")
        check(project:GetCurrentTimeline():GetUniqueId()==source:GetUniqueId(),"RIPPLE_ACTIVE_CHANGED")
        check(source:GetStartFrame()==c.expected_timeline_start
            and source:GetEndFrame()==c.expected_timeline_end,"RIPPLE_BOUNDS_CHANGED")
        check(source:GetTrackCount("video")==2 and source:GetTrackCount("audio")==1
            and source:GetTrackCount("subtitle")==0 and next(source:GetMarkers() or {})==nil,
            "RIPPLE_UNSUPPORTED_LAYOUT")
        local fps=tonumber(source:GetSetting("timelineFrameRate"))
        check(fps and fps>0,"RIPPLE_UNSUPPORTED_LAYOUT")
        check(c.expected_timeline_start<c.start_frame and c.start_frame<c.end_frame
            and c.end_frame<c.expected_group_end,"INVALID_RANGE")
        local before=snapshot(source)
        check(#before[1]>1 and #before[1]<=1000 and #before[2]==#before[1]
            and #before[3]==#before[1],"RIPPLE_UNSUPPORTED_LAYOUT")
        local assets,props={},{}
        for k,s in ipairs(tracks) do
            check(not source:GetIsTrackLocked(s[1],s[2])
                and source:GetIsTrackEnabled(s[1],s[2]),"RIPPLE_UNSUPPORTED_LAYOUT")
            local items=source:GetItemListInTrack(s[1],s[2])
            local first=items[1]
            assets[k]=first:GetMediaPoolItem();props[k]=first:GetProperty()
            local path=k==2 and c.camera_path or c.screen_path
            local head=k==2 and c.camera_source_start or c.screen_source_start
            check(h.allowed(path) and h.normalized(assets[k]:GetClipProperty("File Path"))==h.normalized(path),"SOURCE_CHANGED")
            check(tonumber(assets[k]:GetClipProperty("FPS"))==fps,"SYNC_FPS_MISMATCH")
            check(first:GetStart()==c.expected_timeline_start and first:GetEnd()==c.expected_group_end
                and math.abs(first:GetSourceStartTime()*fps-head)<0.001,"RIPPLE_BOUNDS_CHANGED")
            local span=(first:GetSourceEndTime()-first:GetSourceStartTime())*fps
            check(math.abs(span-(c.expected_group_end-c.expected_timeline_start))<0.001
                or math.abs(span-(c.expected_group_end-c.expected_timeline_start-1))<0.001,"RIPPLE_UNSUPPORTED_LAYOUT")
            check(first:GetFusionCompCount()==0 and next(first:GetMarkers() or {})==nil
                and first:GetClipEnabled()==true,"RIPPLE_UNSUPPORTED_LAYOUT")
            for i,item in ipairs(items) do
                local x=before[k][i]
                check(x.start==before[1][i].start and x.finish==before[1][i].finish
                    and (i==1 or x.start==before[k][i-1].finish),"RIPPLE_UNSUPPORTED_LAYOUT")
                local n=0;for _ in pairs(x.links) do n=n+1 end
                check(n==2,"RIPPLE_UNSUPPORTED_LAYOUT")
                for j in ipairs(tracks) do
                    check(j==k or x.links[before[j][i].id],"RIPPLE_UNSUPPORTED_LAYOUT")
                end
            end
        end
        -- The caller performs SaveProject + backup export before this closure.
        return function()
            local target=source:DuplicateTimeline(c.name)
            check(target and target:GetUniqueId()~=source:GetUniqueId(),"RIPPLE_COPY_FAILED")
            check(tonumber(target:GetSetting("timelineFrameRate"))==fps
                and target:GetStartFrame()==c.expected_timeline_start
                and target:GetEndFrame()==c.expected_timeline_end,"RIPPLE_COPY_FAILED")
            check(project:SetCurrentTimeline(target)==true,"RIPPLE_SELECT_FAILED")
            local copied=snapshot(target)
            local first={}
            for k,s in ipairs(tracks) do
                check(#copied[k]==#before[k],"RIPPLE_COPY_FAILED")
                for i,v in ipairs(copied[k]) do
                    check(v.id~=before[k][i].id and layout_equal(v,before[k][i],false),"RIPPLE_COPY_FAILED")
                end
                first[k]=target:GetItemListInTrack(s[1],s[2])[1]
            end
            check(target:DeleteClips(first,false)==true,"RIPPLE_REMOVE_FAILED")
            local ranges={{c.expected_timeline_start,c.start_frame},{c.start_frame,c.end_frame},
                {c.end_frame,c.expected_group_end}}
            local inserted={}
            for ri,r in ipairs(ranges) do
                inserted[ri]={}
                for k,s in ipairs(tracks) do
                    local offset=r[1]-c.expected_timeline_start
                    local head=(k==2 and c.camera_source_start or c.screen_source_start)+offset
                    local n=r[2]-r[1]
                    local added=project:GetMediaPool():AppendToTimeline({{mediaPoolItem=assets[k],
                        startFrame=head,endFrame=head+n,mediaType=s[1]=="video" and 1 or 2,
                        trackIndex=s[2],recordFrame=r[1]}})
                    check(type(added)=="table" and #added==1,"RIPPLE_INSERT_FAILED")
                    local item=added[1]
                    check(item:GetStart()==r[1] and item:GetEnd()==r[2]
                        and math.abs(item:GetSourceStartTime()*fps-head)<0.001
                        and math.abs(item:GetSourceEndTime()*fps-(head+n))<0.001,
                        "RIPPLE_INSERT_READBACK_FAILED")
                    check(item:GetMediaPoolItem():GetUniqueId()==assets[k]:GetUniqueId(),"RIPPLE_INSERT_READBACK_FAILED")
                    check(item:SetProperty(props[k])==true and equal(item:GetProperty(),props[k]),"RIPPLE_PROPERTIES_FAILED")
                    inserted[ri][k]=item
                end
                check(target:SetClipsLinked(inserted[ri],true)==true,"RIPPLE_LINK_FAILED")
            end
            check(target:DeleteClips(inserted[2],true)==true,"RIPPLE_DELETE_FAILED")
            local delta=c.end_frame-c.start_frame
            local after=snapshot(target)
            check(target:GetStartFrame()==c.expected_timeline_start
                and target:GetEndFrame()==c.expected_timeline_end-delta,"RIPPLE_VERIFY_FAILED")
            for k in ipairs(tracks) do
                check(#after[k]==#copied[k]+1,"RIPPLE_VERIFY_FAILED")
                for i=2,#copied[k] do
                    local old=copied[k][i]
                    old.start=old.start-delta;old.finish=old.finish-delta
                    check(layout_equal(old,after[k][i+1],true),"RIPPLE_DOWNSTREAM_CHANGED")
                end
                for i,ri in ipairs({1,3}) do
                    local item=inserted[ri][k]
                    local shift=ri==3 and delta or 0
                    check(item:GetStart()==ranges[ri][1]-shift and item:GetEnd()==ranges[ri][2]-shift,
                        "RIPPLE_VERIFY_FAILED")
                    local ids=links(item)
                    for j,other in ipairs(inserted[ri]) do
                        check(j==k or ids[other:GetUniqueId()],"RIPPLE_LINK_FAILED")
                    end
                end
            end
            check(equal(before,snapshot(source)),"RIPPLE_SOURCE_CHANGED")
            check(source:GetStartFrame()==c.expected_timeline_start
                and source:GetEndFrame()==c.expected_timeline_end
                and tonumber(source:GetSetting("timelineFrameRate"))==fps,"RIPPLE_SOURCE_CHANGED")
        end
    end
end
