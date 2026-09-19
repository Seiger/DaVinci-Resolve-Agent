-- Cross-group ripple on a duplicate with canonical source-bound privacy transfer.
return function(h,root,request_id,audit)
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
    return function(project,a)
        local c=a.ripple_batch;local source=h.timelines(project,a.timeline_name)
        local edges=c.allow_group_edges==true
        local existing=h.timelines(project,c.name)
        check(source and ((audit and existing) or (not audit and not existing)),'RIPPLE_SOURCE_OR_NAME_CHANGED')
        if not audit then check(project:GetCurrentTimeline():GetUniqueId()==source:GetUniqueId(),'RIPPLE_ACTIVE_CHANGED') end
        check(source:GetStartFrame()==c.expected_timeline_start and source:GetEndFrame()==c.expected_timeline_end,'RIPPLE_BOUNDS_CHANGED')
        check(source:GetTrackCount('video')==2 and source:GetTrackCount('audio')==1 and source:GetTrackCount('subtitle')==0
            and next(source:GetMarkers() or {})==nil,'RIPPLE_SOURCE_TRACKS')
        local before=snapshot(source);local n=#before[1];local fps=tonumber(source:GetSetting('timelineFrameRate'))
        local plans={};local cutcount=0;local delta=0
        for _,g in ipairs(c.groups) do check(g.index>=1 and g.index<=n,'RIPPLE_BOUNDS_CHANGED');plans[g.index]=g;cutcount=cutcount+#g.intervals
            for _,r in ipairs(g.intervals) do delta=delta+r[2]-r[1] end end
        check(n+cutcount<=1000 and delta<c.expected_timeline_end-c.expected_timeline_start
            and #before[2]==n and #before[3]==n,'RIPPLE_GROUP_COUNTS')
        local original={};local graphs={{},{},{}}
        for k,t in ipairs(tracks) do
            -- Editability is a mutation precondition, not a read-only audit
            -- requirement. Resolve can return nil track state for inactive timelines.
            if not audit then
                check(not source:GetIsTrackLocked(t[1],t[2]) and source:GetIsTrackEnabled(t[1],t[2]),'RIPPLE_TRACK_STATE')
            end
            original[k]=source:GetItemListInTrack(t[1],t[2])
            for i,item in ipairs(original[k]) do
                local x=before[k][i];local g=plans[i]
                check(x.start==before[1][i].start and x.finish==before[1][i].finish and (i==1 or x.start==before[k][i-1].finish),'RIPPLE_GROUP_ALIGNMENT')
                local count=0;for _ in pairs(x.links) do count=count+1 end;check(count==2,'RIPPLE_LINK_FAILED')
                for kk in ipairs(tracks) do check(kk==k or x.links[before[kk][i].id],'RIPPLE_LINK_FAILED') end
                if x.fusion>0 then
                    check(k~=3,'RIPPLE_UNSUPPORTED_FUSION')
                    graphs[k][i]={kind=k==1 and 'privacy' or 'circle',data=k==1 and privacy_data(item) or circle_signature(item)}
                end
                if g then
                    local path=k==2 and g.camera_path or g.screen_path;local head=k==2 and g.camera_source_start or g.screen_source_start
                    check(h.allowed(path) and h.normalized(item:GetMediaPoolItem():GetClipProperty('File Path'))==h.normalized(path),'SOURCE_CHANGED')
                    check(tonumber(item:GetMediaPoolItem():GetClipProperty('FPS'))==fps,'SYNC_FPS_MISMATCH')
                    check(x.start==g.start and x.finish==g['end'] and math.abs(x.source_start*fps-head)<0.001,'RIPPLE_BOUNDS_CHANGED')
                    check(math.abs((x.source_end-x.source_start)*fps-(x.finish-x.start))<1.001,'RIPPLE_UNSUPPORTED_RETIME')
                    check(x.enabled and next(item:GetMarkers() or {})==nil,'RIPPLE_ITEM_STATE')
                    if k~=3 then check(item:GetTakesCount()<=1,'RIPPLE_TAKES') end
                    local previous=g.start
                    for j,r in ipairs(g.intervals) do
                        check((previous<r[1] or (edges and j==1 and previous==r[1]))
                            and r[1]<r[2] and (r[2]<g['end'] or (edges and r[2]==g['end'])),'INVALID_RANGE')
                        previous=r[2]
                    end
                end
            end
        end
        local desired={};local shift=0
        for i,x in ipairs(before[1]) do
            local g=plans[i];local lo=x.start
            if g then for _,r in ipairs(g.intervals) do
                if lo<r[1] then desired[#desired+1]={index=i,lo=lo,hi=r[1],shift=shift} end
                shift=shift+r[2]-r[1];lo=r[2]
            end end
            if lo<x.finish then desired[#desired+1]={index=i,lo=lo,hi=x.finish,shift=shift} end
        end
        local function verify(target)
            check(target:GetTrackCount('video')==2 and target:GetTrackCount('audio')==1
                and target:GetTrackCount('subtitle')==0 and tonumber(target:GetSetting('timelineFrameRate'))==fps
                and next(target:GetMarkers() or {})==nil,'RIPPLE_TARGET_TRACKS')
            check(target:GetEndFrame()==c.expected_timeline_end-delta and target:GetStartFrame()==c.expected_timeline_start,'RIPPLE_VERIFY_FAILED')
            local after=snapshot(target)
            for k,t in ipairs(tracks) do
                check(#after[k]==#desired,'RIPPLE_VERIFY_FAILED');local items=target:GetItemListInTrack(t[1],t[2])
                for j,d in ipairs(desired) do
                    local old=before[k][d.index];local new=after[k][j];local item=items[j];local offset=d.lo-old.start
                    check(new.start==d.lo-d.shift and new.finish==d.hi-d.shift and new.media==old.media and new.enabled==old.enabled,'RIPPLE_VERIFY_FAILED')
                    check(math.abs(new.source_start-old.source_start-offset/fps)<0.00001 and math.abs((new.source_end-new.source_start)*fps-(d.hi-d.lo))<1.001,'RIPPLE_SOURCE_CHANGED')
                    check(equal(new.properties,old.properties),'RIPPLE_PROPERTIES_FAILED')
                    local links=links(item);local count=0;for _ in pairs(links) do count=count+1 end;check(count==2,'RIPPLE_LINK_FAILED')
                    for kk,tt in ipairs(tracks) do check(kk==k or links[target:GetItemListInTrack(tt[1],tt[2])[j]:GetUniqueId()],'RIPPLE_LINK_FAILED') end
                    local graph=graphs[k][d.index]
                    if graph then
                        local expected={};for key,v in pairs(graph.data) do expected[key]=v end
                        if k==2 then
                            expected.visibility=clipped({ranges=graph.data.visibility},offset,d.hi-d.lo)
                            check(equal(circle_signature(item),expected),'RIPPLE_VISIBILITY_CHANGED')
                        else
                            expected.ranges=clipped(graph.data,offset,d.hi-d.lo)
                            if #expected.ranges>0 then check(equal(privacy_data(item),expected),'RIPPLE_PRIVACY_CHANGED')
                            else check(item:GetFusionCompCount()==0,'RIPPLE_PRIVACY_CHANGED') end
                        end
                    else check(new.fusion==old.fusion,'RIPPLE_FUSION_CHANGED') end
                end
            end
            check(equal(before,snapshot(source)),'RIPPLE_SOURCE_CHANGED')
            for k,data in pairs(graphs) do for i,g in pairs(data) do
                check(equal(k==1 and privacy_data(original[k][i]) or circle_signature(original[k][i]),g.data),'RIPPLE_SOURCE_CHANGED')
            end end
        end
        if audit then verify(existing);return 'ripple_verified' end
        return function()
            local target=source:DuplicateTimeline(c.name);check(target,'RIPPLE_COPY_FAILED')
            check(project:SetCurrentTimeline(target),'RIPPLE_SELECT_FAILED')
            local copied=snapshot(target);local remove={};local discard={}
            for k,t in ipairs(tracks) do
                local items=target:GetItemListInTrack(t[1],t[2]);check(#copied[k]==n,'RIPPLE_COPY_FAILED')
                for i,item in ipairs(items) do
                    check(layout_equal(before[k][i],copied[k][i],false),'RIPPLE_COPY_FAILED')
                    local graph=graphs[k][i]
                    if graph and k==2 then visibility.transfer(item,graph.data.visibility,0,item:GetEnd()-item:GetStart()) end
                    if plans[i] then
                        remove[#remove+1]=item
                        if graph then graph.path=root..'/'..request_id..'.'..k..'.'..i..'.comp'
                            check(original[k][i]:ExportFusionComp(graph.path,1)==true,'RIPPLE_FUSION_EXPORT_FAILED') end
                    end
                end
            end
            check(target:DeleteClips(remove,false),'RIPPLE_REMOVE_FAILED')
            for _,g in ipairs(c.groups) do
                local pieces={};local lo=g.start
                for _,r in ipairs(g.intervals) do
                    if lo<r[1] then pieces[#pieces+1]={lo,r[1],true} end
                    pieces[#pieces+1]={r[1],r[2],false};lo=r[2]
                end
                if lo<g['end'] then pieces[#pieces+1]={lo,g['end'],true} end
                for _,piece in ipairs(pieces) do
                    local lo,hi,keep=piece[1],piece[2],piece[3];local triple={}
                    for k,t in ipairs(tracks) do
                        local head=(k==2 and g.camera_source_start or g.screen_source_start)+lo-g.start
                        local added=project:GetMediaPool():AppendToTimeline({{mediaPoolItem=original[k][g.index]:GetMediaPoolItem(),
                            startFrame=head,endFrame=head+hi-lo,mediaType=k==3 and 2 or 1,trackIndex=t[2],recordFrame=lo}})
                        check(type(added)=='table' and #added==1,'RIPPLE_INSERT_FAILED');local item=added[1];triple[k]=item
                        check(item:GetStart()==lo and item:GetEnd()==hi and math.abs(item:GetSourceStartTime()*fps-head)<0.001,'RIPPLE_INSERT_READBACK_FAILED')
                        check(item:SetProperty(before[k][g.index].properties),'RIPPLE_PROPERTIES_FAILED')
                        local graph=graphs[k][g.index]
                        if keep and graph then
                            local ranges=graph.kind=='privacy' and clipped(graph.data,lo-g.start,hi-lo) or nil
                            if not ranges or #ranges>0 then
                                check(item:ImportFusionComp(graph.path)~=nil,'RIPPLE_FUSION_IMPORT_FAILED')
                                if ranges then
                                    local mask=item:GetFusionCompByIndex(1):FindTool('ResolveAgentPrivacyMask');local terms={}
                                    for _,r in ipairs(ranges) do terms[#terms+1]=string.format('(time >= %d and time < %d)',r[1],r[2]) end
                                    mask.Level:SetExpression('iif('..table.concat(terms,' or ')..', 1, 0)')
                                else visibility.transfer(item,graph.data.visibility,lo-g.start,hi-lo) end
                            end
                        end
                    end
                    check(target:SetClipsLinked(triple,true),'RIPPLE_LINK_FAILED')
                    if not keep then for _,item in ipairs(triple) do discard[#discard+1]=item end end
                end
            end
            check(target:DeleteClips(discard,true),'RIPPLE_DELETE_FAILED')
            verify(target)
        end
    end
end
