-- Narrow single-group ripple on a duplicate. Preserve untouched items.
return function(h,root,request_id,audit,repair)
    local check=h.check
    local visibility=dofile(root.."/camera_visibility.lua")(h)
    local tracks={{"video",1},{"video",2},{"audio",1}}
    local function equal(a,b)
        if type(a)~=type(b) then return false end
        if type(a)~="table" then return a==b end
        for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
        for k in pairs(b) do if a[k]==nil then return false end end
        return true
    end
    -- Only the bridge's simple five-node circle graph may be transferred.
    -- Export/import preserves the actual native composition, not a substitute mask.
    local function circle_signature(item)
        check(item:GetFusionCompCount()==1,"RIPPLE_UNSUPPORTED_FUSION")
        local comp=item:GetFusionCompByIndex(1)
        local ts=comp:GetToolList(false);local n=0
        for _ in pairs(ts) do n=n+1 end
        check(n==5,"RIPPLE_UNSUPPORTED_FUSION")
        local input=comp:FindTool("MediaIn1");local out=comp:FindTool("MediaOut1")
        local merge=comp:FindTool("Merge1");local ellipse=comp:FindTool("Ellipse1")
        local bg=comp:FindTool("Background1")
        check(input and out and merge and ellipse and bg,"RIPPLE_UNSUPPORTED_FUSION")
        local function connected(pin,tool)
            local output=pin:GetConnectedOutput()
            return output and output:GetTool():GetAttrs().TOOLS_Name==tool:GetAttrs().TOOLS_Name
        end
        check(connected(out.Input,merge) and connected(merge.Foreground,input)
            and connected(merge.Background,bg) and connected(merge.EffectMask,ellipse),"RIPPLE_UNSUPPORTED_FUSION")
        local center=ellipse:GetInput("Center")
        local width=ellipse:GetInput("Width");local height=ellipse:GetInput("Height")
        local soft=ellipse:GetInput("SoftEdge");local alpha=bg:GetInput("TopLeftAlpha")
        check(type(center)=="table" and type(width)=="number" and width==height
            and alpha==0,"RIPPLE_UNSUPPORTED_FUSION")
        return {center=center,width=width,height=height,soft=soft,alpha=alpha,visibility=visibility.capture(item)}
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
    local function audit_existing(project,a)
        local c=a.ripple_cut;local source=h.timelines(project,a.timeline_name);local target=h.timelines(project,c.name)
        check(source and target,'RIPPLE_AUDIT_TIMELINE_MISSING')
        local before=snapshot(source);local after=snapshot(target);local index=c.group_index or 1
        local pending={}
        local delta=c.end_frame-c.start_frame;local fps=tonumber(source:GetSetting('timelineFrameRate'))
        check(fps and tonumber(target:GetSetting('timelineFrameRate'))==fps,'RIPPLE_AUDIT_FPS')
        for _,timeline in ipairs({source,target}) do
            check(timeline:GetTrackCount('video')==2 and timeline:GetTrackCount('audio')==1 and timeline:GetTrackCount('subtitle')==0,'RIPPLE_AUDIT_COUNTS')
        end
        for k,t in ipairs(tracks) do
            local item=source:GetItemListInTrack(t[1],t[2])[index]
            local path=k==2 and c.camera_path or c.screen_path;local head=k==2 and c.camera_source_start or c.screen_source_start
            check(item and item:GetStart()==(c.expected_group_start or c.expected_timeline_start) and item:GetEnd()==c.expected_group_end,'RIPPLE_AUDIT_BOUNDS')
            check(h.allowed(path) and h.normalized(item:GetMediaPoolItem():GetClipProperty('File Path'))==h.normalized(path)
                and math.abs(item:GetSourceStartTime()*fps-head)<0.001,'RIPPLE_AUDIT_SOURCE')
        end
        check(source:GetEndFrame()==c.expected_timeline_end and target:GetEndFrame()==c.expected_timeline_end-delta,'RIPPLE_AUDIT_BOUNDS')
        check(source:GetStartFrame()==c.expected_timeline_start and target:GetStartFrame()==c.expected_timeline_start,'RIPPLE_AUDIT_BOUNDS')
        for k,t in ipairs(tracks) do
            check(#after[k]==#before[k]+1,'RIPPLE_AUDIT_COUNTS')
            local olditems=source:GetItemListInTrack(t[1],t[2]);local newitems=target:GetItemListInTrack(t[1],t[2])
            for j,y in ipairs(after[k]) do
                local i=j<=index and j or j-1;local x=before[k][i]
                local lo=i==index and (j==index and x.start or c.end_frame) or x.start
                local hi=i==index and (j==index and c.start_frame or x.finish) or x.finish
                local offset=lo-x.start;local shift=lo>=c.end_frame and delta or 0
                check(y.start==lo-shift and y.finish==hi-shift and y.media==x.media and y.enabled==x.enabled,'RIPPLE_AUDIT_LAYOUT')
                check(math.abs(y.source_start-x.source_start-offset/fps)<0.00001 and math.abs((y.source_end-y.source_start)*fps-(hi-lo))<1.001,'RIPPLE_AUDIT_SOURCE')
                check(equal(y.properties,x.properties),'RIPPLE_AUDIT_PROPERTIES')
                local ids=links(newitems[j]);local n=0;for _ in pairs(ids) do n=n+1 end
                check(n==2,'RIPPLE_AUDIT_LINKS')
                for kk,tt in ipairs(tracks) do check(kk==k or ids[target:GetItemListInTrack(tt[1],tt[2])[j]:GetUniqueId()],'RIPPLE_AUDIT_LINKS') end
                if k==2 and x.fusion>0 then
                    local old=circle_signature(olditems[i]);local new=circle_signature(newitems[j]);local expected={}
                    for _,r in ipairs(old.visibility) do
                        local a0=math.max(0,r[1]-offset);local b0=math.min(hi-lo,r[2]-offset)
                        if a0<b0 then expected[#expected+1]={a0,b0} end
                    end
                    if repair then pending[#pending+1]={item=newitems[j],ranges=old.visibility,offset=offset,length=hi-lo}
                    else check(equal(expected,new.visibility),'RIPPLE_AUDIT_VISIBILITY_'..tostring(i):gsub('%d',function(d) return string.char(65+tonumber(d)) end)) end
                    old.visibility=nil;new.visibility=nil
                    for key,v in pairs(old) do
                        check(equal(v,new[key]),'RIPPLE_AUDIT_'..key:upper()..'_'..tostring(i):gsub('%d',function(d) return string.char(65+tonumber(d)) end))
                    end
                elseif k==1 and x.fusion>0 then
                    check(i~=index,'RIPPLE_AUDIT_UNSUPPORTED_PRIVACY_BOUNDARY')
                    local privacy=dofile(root..'/privacy.lua')(h)
                    check(privacy.inspect(olditems[i])==privacy.inspect(newitems[j]),'RIPPLE_AUDIT_PRIVACY')
                else check(y.fusion==x.fusion,'RIPPLE_AUDIT_FUSION') end
            end
        end
        if repair then
            check(project:GetCurrentTimeline():GetUniqueId()==target:GetUniqueId(),'RIPPLE_ACTIVE_CHANGED')
            return function()
                for _,p in ipairs(pending) do visibility.transfer(p.item,p.ranges,p.offset,p.length) end
                check(equal(after,snapshot(target)) and equal(before,snapshot(source)),'RIPPLE_AUDIT_LAYOUT')
                dofile(root..'/ripple.lua')(h,root,request_id,true,false)(project,a)
            end
        end
        return 'ripple_verified'
    end
    if audit then return audit_existing end
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
        local index=c.group_index or 1
        local group_start=c.expected_group_start or c.expected_timeline_start
        check(index>=1 and index%1==0 and group_start>=c.expected_timeline_start
            and group_start<c.start_frame,"INVALID_RANGE")
        local before=snapshot(source)
        check(index<=#before[1],"RIPPLE_BOUNDS_CHANGED")
        check(#before[1]>1 and #before[1]<=1000 and #before[2]==#before[1]
            and #before[3]==#before[1],"RIPPLE_UNSUPPORTED_LAYOUT")
        local assets,props={},{}
        local circle,original_camera
        local old_cameras={}
        for k,s in ipairs(tracks) do
            check(not source:GetIsTrackLocked(s[1],s[2])
                and source:GetIsTrackEnabled(s[1],s[2]),"RIPPLE_UNSUPPORTED_LAYOUT")
            local items=source:GetItemListInTrack(s[1],s[2])
            local first=items[index]
            assets[k]=first:GetMediaPoolItem();props[k]=first:GetProperty()
            local path=k==2 and c.camera_path or c.screen_path
            local head=k==2 and c.camera_source_start or c.screen_source_start
            check(h.allowed(path) and h.normalized(assets[k]:GetClipProperty("File Path"))==h.normalized(path),"SOURCE_CHANGED")
            check(tonumber(assets[k]:GetClipProperty("FPS"))==fps,"SYNC_FPS_MISMATCH")
            check(first:GetStart()==group_start and first:GetEnd()==c.expected_group_end
                and math.abs(first:GetSourceStartTime()*fps-head)<0.001,"RIPPLE_BOUNDS_CHANGED")
            local span=(first:GetSourceEndTime()-first:GetSourceStartTime())*fps
            check(math.abs(span-(c.expected_group_end-group_start))<0.001
                or math.abs(span-(c.expected_group_end-group_start-1))<0.001,"RIPPLE_UNSUPPORTED_LAYOUT")
            if first:GetFusionCompCount()>0 then
                check(k==2,"RIPPLE_UNSUPPORTED_FUSION")
                circle=circle_signature(first);original_camera=first
            end
            check(next(first:GetMarkers() or {})==nil
                and first:GetClipEnabled()==true,"RIPPLE_UNSUPPORTED_LAYOUT")
            for i,item in ipairs(items) do
                local x=before[k][i]
                if k==2 and item:GetFusionCompCount()>0 then old_cameras[i]=circle_signature(item) end
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
            local comp_path=root .. "/" .. request_id .. ".circle.comp"
            if circle then
                check(original_camera:ExportFusionComp(comp_path,1)==true,"RIPPLE_FUSION_EXPORT_FAILED")
            end
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
                first[k]=target:GetItemListInTrack(s[1],s[2])[index]
            end
            -- Resolve can drop Blend expressions when duplicating a timeline.
            for i,data in pairs(old_cameras) do
                local item=target:GetItemListInTrack('video',2)[i]
                visibility.transfer(item,data.visibility,0,item:GetEnd()-item:GetStart())
                check(equal(circle_signature(item),data),'RIPPLE_VISIBILITY_CHANGED')
            end
            check(target:DeleteClips(first,false)==true,"RIPPLE_REMOVE_FAILED")
            local ranges={{group_start,c.start_frame},{c.start_frame,c.end_frame},
                {c.end_frame,c.expected_group_end}}
            local inserted={}
            for ri,r in ipairs(ranges) do
                inserted[ri]={}
                for k,s in ipairs(tracks) do
                    local offset=r[1]-group_start
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
                    if circle and k==2 and ri~=2 then
                        check(item:ImportFusionComp(comp_path)~=nil,"RIPPLE_FUSION_IMPORT_FAILED")
                        local expected={};for key,value in pairs(circle) do expected[key]=value end
                        expected.visibility=visibility.transfer(item,circle.visibility,offset,n)
                        check(equal(expected,circle_signature(item)),"RIPPLE_FUSION_CHANGED")
                    end
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
                for i=1,#copied[k] do
                    if i~=index then
                        local old=copied[k][i]
                        local shift=i>index and delta or 0
                        local target_index=i>index and i+1 or i
                        old.start=old.start-shift;old.finish=old.finish-shift
                        check(layout_equal(old,after[k][target_index],true),"RIPPLE_DOWNSTREAM_CHANGED")
                        if k==2 and old_cameras[i] then
                            check(equal(circle_signature(target:GetItemListInTrack('video',2)[target_index]),old_cameras[i]),'RIPPLE_VISIBILITY_CHANGED')
                        end
                    end
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
            for i,data in pairs(old_cameras) do check(equal(circle_signature(source:GetItemListInTrack('video',2)[i]),data),'RIPPLE_SOURCE_CHANGED') end
            check(source:GetStartFrame()==c.expected_timeline_start
                and source:GetEndFrame()==c.expected_timeline_end
                and tonumber(source:GetSetting("timelineFrameRate"))==fps,"RIPPLE_SOURCE_CHANGED")
        end
    end
end
