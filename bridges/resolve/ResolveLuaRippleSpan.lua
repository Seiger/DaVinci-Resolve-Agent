-- Cross-group ripple on a duplicate with canonical source-bound privacy transfer.
return function(h,root,request_id)
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

    local privacy=dofile(root.."/privacy.lua")(h)
    local function privacy_data(item)
        privacy.inspect(item) -- Reject noncanonical graphs/expressions before edits.
        local comp=item:GetFusionCompByIndex(1)
        local mask=comp:FindTool("ResolveAgentPrivacyMask")
        local blur=comp:FindTool("ResolveAgentPrivacyBlur")
        local ranges={}
        for lo,hi in mask.Level:GetExpression():gmatch("time >= (%d+) and time < (%d+)") do
            ranges[#ranges+1]={tonumber(lo),tonumber(hi)}
        end
        return {ranges=ranges,center=mask:GetInput("Center"),width=mask:GetInput("Width"),
            height=mask:GetInput("Height"),soft=mask:GetInput("SoftEdge"),
            x=blur:GetInput("XBlurSize"),y=blur:GetInput("YBlurSize")}
    end
    local function clipped(data,offset,length)
        local result={}
        for _,r in ipairs(data.ranges) do
            local lo=math.max(0,r[1]-offset);local hi=math.min(length,r[2]-offset)
            if lo<hi then result[#result+1]={lo,hi} end
        end
        return result
    end
    local phase="ENTRY"
    local function preflight(project,a)
        local c=a.ripple_span
        local source=h.timelines(project,a.timeline_name)
        check(source and not h.timelines(project,c.name),"RIPPLE_SOURCE_OR_NAME_CHANGED")
        check(project:GetCurrentTimeline():GetUniqueId()==source:GetUniqueId(),"RIPPLE_ACTIVE_CHANGED")
        check(source:GetStartFrame()==c.expected_timeline_start and source:GetEndFrame()==c.expected_timeline_end,"RIPPLE_BOUNDS_CHANGED")
        check(source:GetTrackCount("video")==2 and source:GetTrackCount("audio")==1
            and source:GetTrackCount("subtitle")==0 and next(source:GetMarkers() or {})==nil,"RIPPLE_UNSUPPORTED_LAYOUT")
        local fps=tonumber(source:GetSetting("timelineFrameRate"));check(fps and fps>0,"SYNC_FPS_MISMATCH")
        phase="SNAPSHOT"
        local before=snapshot(source);local n=#before[1]
        check(n<=1000 and n==#before[2] and n==#before[3],"RIPPLE_UNSUPPORTED_LAYOUT")
        local first=c.groups[1].index;local last=c.groups[#c.groups].index
        local delta=c.end_frame-c.start_frame
        check(first>=1 and last<=n and first<last,"INVALID_RANGE")
        check(c.groups[1].start<c.start_frame and c.start_frame<c.groups[1]['end']
            and c.groups[#c.groups].start<c.end_frame and c.end_frame<c.groups[#c.groups]['end'],"INVALID_RANGE")
        local selected={};local graphs={};local old_graphs={}
        for k,t in ipairs(tracks) do
            phase="TRACK_"..k
            check(not source:GetIsTrackLocked(t[1],t[2]) and source:GetIsTrackEnabled(t[1],t[2]),"RIPPLE_UNSUPPORTED_LAYOUT")
            local items=source:GetItemListInTrack(t[1],t[2]);selected[k]={};graphs[k]={};old_graphs[k]={}
            for i,item in ipairs(items) do
                local x=before[k][i]
                check(x.start==before[1][i].start and x.finish==before[1][i].finish
                    and (i==1 or x.start==before[k][i-1].finish),"RIPPLE_UNSUPPORTED_LAYOUT")
                local count=0;for _ in pairs(x.links) do count=count+1 end
                check(count==2,"RIPPLE_UNSUPPORTED_LAYOUT")
                for j in ipairs(tracks) do check(j==k or x.links[before[j][i].id],"RIPPLE_UNSUPPORTED_LAYOUT") end
                -- Preserve local privacy timing on all untouched screen clips, too.
                if k==1 and x.fusion>0 then phase="PRIVACY_"..i;old_graphs[k][i]=privacy_data(item) end
                if k==2 and x.fusion>0 then old_graphs[k][i]=circle_signature(item) end
            end
            for gi,g in ipairs(c.groups) do
                phase="GROUP_"..k.."_"..gi
                local item=items[g.index];check(item~=nil,"ITEM_NOT_FOUND")
                selected[k][gi]=item
                local media=item:GetMediaPoolItem();local path=k==2 and g.camera_path or g.screen_path
                local head=k==2 and g.camera_source_start or g.screen_source_start
                check(h.allowed(path) and h.normalized(media:GetClipProperty("File Path"))==h.normalized(path),"SOURCE_CHANGED")
                check(tonumber(media:GetClipProperty("FPS"))==fps,"SYNC_FPS_MISMATCH")
                check(item:GetStart()==g.start and item:GetEnd()==g['end']
                    and math.abs(item:GetSourceStartTime()*fps-head)<0.001,"RIPPLE_BOUNDS_CHANGED")
                local span=(item:GetSourceEndTime()-item:GetSourceStartTime())*fps
                check(math.abs(span-(g["end"]-g.start))<0.001
                    or math.abs(span-(g["end"]-g.start-1))<0.001,"RIPPLE_UNSUPPORTED_LAYOUT")
                check(item:GetClipEnabled() and next(item:GetMarkers() or {})==nil,"RIPPLE_UNSUPPORTED_LAYOUT")
                if k~=3 then
                    local takes=item:GetTakesCount()
                    check(type(takes)=="number" and takes<=1,"RIPPLE_UNSUPPORTED_LAYOUT")
                end
                if item:GetFusionCompCount()>0 then
                    if k==1 then graphs[k][gi]={kind='privacy',data=privacy_data(item)}
                    elseif k==2 then graphs[k][gi]={kind='circle',data=circle_signature(item)}
                    else error("RIPPLE_UNSUPPORTED_FUSION",0) end
                end
            end
        end
        return function()
            local target=source:DuplicateTimeline(c.name)
            check(target and target:GetUniqueId()~=source:GetUniqueId(),"RIPPLE_COPY_FAILED")
            check(project:SetCurrentTimeline(target),"RIPPLE_SELECT_FAILED")
            local copied=snapshot(target)
            local originals={};local remove={}
            for k,t in ipairs(tracks) do
                check(#copied[k]==n,"RIPPLE_COPY_FAILED")
                originals[k]=target:GetItemListInTrack(t[1],t[2])
                for i,x in ipairs(copied[k]) do check(layout_equal(x,before[k][i],false),"RIPPLE_COPY_FAILED") end
                for i=first,last do remove[#remove+1]=originals[k][i] end
            end
            for i,data in pairs(old_graphs[2]) do
                local item=originals[2][i]
                visibility.transfer(item,data.visibility,0,item:GetEnd()-item:GetStart())
                check(equal(circle_signature(item),data),'RIPPLE_VISIBILITY_CHANGED')
            end
            -- Export only canonical boundary compositions before replacing those items.
            for k in ipairs(tracks) do
                for _,gi in ipairs({1,#c.groups}) do
                    local graph=graphs[k][gi]
                    if graph then
                        graph.path=root..'/'..request_id..'.'..k..'.'..gi..'.comp'
                        check(selected[k][gi]:ExportFusionComp(graph.path,1)==true,"RIPPLE_FUSION_EXPORT_FAILED")
                    end
                end
            end
            check(target:DeleteClips(remove,false),"RIPPLE_REMOVE_FAILED")
            local retained={};local discard={}
            for gi,g in ipairs(c.groups) do
                local cuts={g.start}
                if g.start<c.start_frame and c.start_frame<g['end'] then cuts[#cuts+1]=c.start_frame end
                if g.start<c.end_frame and c.end_frame<g['end'] then cuts[#cuts+1]=c.end_frame end
                cuts[#cuts+1]=g['end']
                for ri=1,#cuts-1 do
                    local lo,hi=cuts[ri],cuts[ri+1];local keep=hi<=c.start_frame or lo>=c.end_frame
                    local triple={}
                    for k,t in ipairs(tracks) do
                        local head=(k==2 and g.camera_source_start or g.screen_source_start)+lo-g.start
                        local added=project:GetMediaPool():AppendToTimeline({{mediaPoolItem=selected[k][gi]:GetMediaPoolItem(),
                            startFrame=head,endFrame=head+hi-lo,mediaType=k==3 and 2 or 1,trackIndex=t[2],recordFrame=lo}})
                        check(type(added)=='table' and #added==1,"RIPPLE_INSERT_FAILED")
                        local item=added[1];triple[k]=item
                        check(item:GetStart()==lo and item:GetEnd()==hi and math.abs(item:GetSourceStartTime()*fps-head)<0.001
                            and math.abs(item:GetSourceEndTime()*fps-(head+hi-lo))<0.001,"RIPPLE_INSERT_READBACK_FAILED")
                        local props=before[k][g.index].properties
                        check(item:SetProperty(props) and equal(item:GetProperty(),props),"RIPPLE_PROPERTIES_FAILED")
                        local graph=graphs[k][gi]
                        if keep and graph then
                            local ranges=graph.kind=='privacy' and clipped(graph.data,lo-g.start,hi-lo) or nil
                            if not ranges or #ranges>0 then
                                check(item:ImportFusionComp(graph.path)~=nil,"RIPPLE_FUSION_IMPORT_FAILED")
                                if ranges then
                                    local mask=item:GetFusionCompByIndex(1):FindTool('ResolveAgentPrivacyMask')
                                    local terms={};for _,r in ipairs(ranges) do terms[#terms+1]=string.format('(time >= %d and time < %d)',r[1],r[2]) end
                                    mask.Level:SetExpression('iif('..table.concat(terms,' or ')..', 1, 0)')
                                    local expected={};for key,value in pairs(graph.data) do expected[key]=value end;expected.ranges=ranges
                                    check(equal(privacy_data(item),expected),'RIPPLE_PRIVACY_CHANGED')
                                else
                                    local expected={};for key,value in pairs(graph.data) do expected[key]=value end
                                    expected.visibility=visibility.transfer(item,graph.data.visibility,lo-g.start,hi-lo)
                                    check(equal(circle_signature(item),expected),'RIPPLE_FUSION_CHANGED')
                                end
                            end
                        end
                    end
                    check(target:SetClipsLinked(triple,true),'RIPPLE_LINK_FAILED')
                    if keep then retained[#retained+1]={items=triple,lo=lo,hi=hi}
                    else for _,item in ipairs(triple) do discard[#discard+1]=item end end
                end
            end
            check(target:DeleteClips(discard,true),'RIPPLE_DELETE_FAILED')
            local after=snapshot(target);local count=n-#c.groups+2
            check(target:GetEndFrame()==c.expected_timeline_end-delta and target:GetStartFrame()==c.expected_timeline_start,'RIPPLE_VERIFY_FAILED')
            for k,t in ipairs(tracks) do
                check(#after[k]==count,'RIPPLE_VERIFY_FAILED')
                local items=target:GetItemListInTrack(t[1],t[2])
                for i=1,n do
                    if i<first or i>last then
                        local j=i<first and i or i-#c.groups+2
                        local old=copied[k][i];local shift=i>last and delta or 0
                        old.start=old.start-shift;old.finish=old.finish-shift
                        check(layout_equal(old,after[k][j],true),'RIPPLE_DOWNSTREAM_CHANGED')
                        if old_graphs[k][i] then check(equal(k==1 and privacy_data(items[j]) or circle_signature(items[j]),old_graphs[k][i]),'RIPPLE_GRAPH_CHANGED') end
                    end
                end
            end
            for _,r in ipairs(retained) do
                local shift=r.lo>=c.end_frame and delta or 0
                for k,item in ipairs(r.items) do
                    check(item:GetStart()==r.lo-shift and item:GetEnd()==r.hi-shift,'RIPPLE_VERIFY_FAILED')
                    local ids=links(item);for j,other in ipairs(r.items) do check(j==k or ids[other:GetUniqueId()],'RIPPLE_LINK_FAILED') end
                end
            end
            check(equal(before,snapshot(source)),'RIPPLE_SOURCE_CHANGED')
            for k,data in pairs(old_graphs) do
                local items=source:GetItemListInTrack(tracks[k][1],tracks[k][2])
                for i,graph in pairs(data) do check(equal(k==1 and privacy_data(items[i]) or circle_signature(items[i]),graph),'RIPPLE_SOURCE_CHANGED') end
            end
            check(source:GetEndFrame()==c.expected_timeline_end,'RIPPLE_SOURCE_CHANGED')
        end
    end
    return function(project,a)
        local ok,value=pcall(preflight,project,a)
        if not ok then
            if tostring(value):match("^[A-Z_]+$") then error(value,0) end
            error("RIPPLE_PREFLIGHT_"..phase:gsub("%d",function(d) return string.char(65+tonumber(d)) end),0)
        end
        return value
    end
end
