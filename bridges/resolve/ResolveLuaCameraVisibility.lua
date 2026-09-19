-- Hide only a canonical V2 circle during explicit local-time intervals.
return function(h)
    local check=h.check
    local function equal(a,b)
        if type(a)~=type(b) then return false end
        if type(a)~='table' then return a==b end
        for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
        for k in pairs(b) do if a[k]==nil then return false end end
        return true
    end
    local function graph(item)
        check(item:GetFusionCompCount()==1,'CAMERA_UNSUPPORTED_GRAPH')
        local comp=item:GetFusionCompByIndex(1)
        local input=comp:FindTool('MediaIn1');local output=comp:FindTool('MediaOut1')
        local merge=comp:FindTool('Merge1');local mask=comp:FindTool('Ellipse1');local bg=comp:FindTool('Background1')
        check(input and output and merge and mask and bg,'CAMERA_UNSUPPORTED_GRAPH')
        local n=0;for _ in pairs(comp:GetToolList(false)) do n=n+1 end
        check(n==5,'CAMERA_UNSUPPORTED_GRAPH')
        local function linked(pin,tool)
            local value=pin:GetConnectedOutput()
            return value and value:GetTool():GetAttrs().TOOLS_Name==tool:GetAttrs().TOOLS_Name
        end
        check(linked(output.Input,merge) and linked(merge.Foreground,input)
            and linked(merge.Background,bg) and linked(merge.EffectMask,mask),'CAMERA_UNSUPPORTED_GRAPH')
        check(bg:GetInput('TopLeftAlpha')==0,'CAMERA_BACKGROUND_OPAQUE')
        return merge,{center=mask:GetInput('Center'),width=mask:GetInput('Width'),
            height=mask:GetInput('Height'),soft=mask:GetInput('SoftEdge'),alpha=bg:GetInput('TopLeftAlpha')}
    end
    local function layout(t,identity)
        local result={start=t:GetStartFrame(),finish=t:GetEndFrame(),fps=t:GetSetting('timelineFrameRate'),items={}}
        local index={}
        for _,kind in ipairs({'video','audio','subtitle'}) do
            result[kind]=t:GetTrackCount(kind)
            for track=1,t:GetTrackCount(kind) do
                for i,item in ipairs(t:GetItemListInTrack(kind,track) or {}) do
                    index[item:GetUniqueId()]=kind..'_'..track..'_'..i
                end
            end
        end
        for _,kind in ipairs({'video','audio','subtitle'}) do
            for track=1,t:GetTrackCount(kind) do
                for _,item in ipairs(t:GetItemListInTrack(kind,track) or {}) do
                    local id=item:GetUniqueId();local links={}
                    for _,other in ipairs(item:GetLinkedItems() or {}) do links[index[other:GetUniqueId()] or 'outside']=true end
                    local media=item:GetMediaPoolItem()
                    result.items[index[id]]={id=identity and id or '',start=item:GetStart(),finish=item:GetEnd(),
                        source_start=item:GetSourceStartTime(),source_end=item:GetSourceEndTime(),
                        media=media and media:GetUniqueId() or '',properties=item:GetProperty(),links=links,
                        fusion=item:GetFusionCompCount(),enabled=item:GetClipEnabled()}
                end
            end
        end
        return result
    end
    local function verify(merge,expression,intervals,length)
        check(merge.Blend:GetExpression()==expression,'CAMERA_EXPRESSION_CHANGED')
        local points={[0]=true,[length-1]=true}
        for _,r in ipairs(intervals) do
            for _,p in ipairs({r[1]-1,r[1],r[2]-1,r[2]}) do
                if p>=0 and p<length then points[p]=true end
            end
        end
        for p in pairs(points) do
            local expected=1
            for _,r in ipairs(intervals) do if p>=r[1] and p<r[2] then expected=0 end end
            check(merge:GetInput('Blend',p)==expected,'CAMERA_TIME_READBACK_FAILED')
        end
    end
    local function preflight(project,a)
        local p=a.camera_visibility;local source=h.timelines(project,a.timeline_name)
        check(source~=nil,'TIMELINE_NOT_FOUND')
        check(h.timelines(project,p.name)==nil,'NAME_EXISTS')
        check(project:GetCurrentTimeline():GetUniqueId()==source:GetUniqueId(),'CAMERA_ACTIVE_CHANGED')
        check(source:GetStartFrame()==p.expected_start and source:GetEndFrame()==p.expected_end,'CAMERA_BOUNDS_CHANGED')
        check(source:GetTrackCount('video')>=2 and not source:GetIsTrackLocked('video',2)
            and source:GetIsTrackEnabled('video',2),'CAMERA_TRACK_UNAVAILABLE')
        local before=layout(source,true);local comparable=layout(source,false)
        local items=source:GetItemListInTrack('video',2);local signatures={};local expressions={};local intervals={}
        for i,x in ipairs(p.items) do
            local item=items[x.index]
            check(item and item:GetStart()==x.start and item:GetEnd()==x['end'],'CAMERA_BOUNDS_CHANGED')
            check(item:GetClipEnabled() and h.allowed(x.path)
                and h.normalized(item:GetMediaPoolItem():GetClipProperty('File Path'))==h.normalized(x.path),'SOURCE_CHANGED')
            local merge,signature=graph(item);signatures[i]=signature
            check(not merge.Blend:GetExpression() and not merge.Blend:GetConnectedOutput()
                and merge:GetInput('Blend')==1,'CAMERA_ALREADY_ANIMATED')
            local terms={};intervals[i]={};local previous=-1
            for _,r in ipairs(x.intervals) do
                local lo=r[1]-x.start;local hi=r[2]-x.start
                check(lo>=0 and lo>previous and lo<hi and hi<=x['end']-x.start,'INVALID_RANGE')
                previous=hi;intervals[i][#intervals[i]+1]={lo,hi}
                terms[#terms+1]=string.format('(time >= %d and time < %d)',lo,hi)
            end
            expressions[i]='iif('..table.concat(terms,' or ')..', 0, 1)'
        end
        -- SaveProject and backup export are performed by the caller before this closure.
        return function()
            local target=source:DuplicateTimeline(p.name)
            check(target and target:GetUniqueId()~=source:GetUniqueId(),'CAMERA_COPY_FAILED')
            check(equal(comparable,layout(target,false)),'CAMERA_COPY_CHANGED')
            check(project:SetCurrentTimeline(target),'CAMERA_SELECT_FAILED')
            local copied=layout(target,true);local camera=target:GetItemListInTrack('video',2)
            for i,x in ipairs(p.items) do
                local merge,signature=graph(camera[x.index])
                check(equal(signature,signatures[i]),'CAMERA_MASK_CHANGED')
                merge.Blend:SetExpression(expressions[i])
                verify(merge,expressions[i],intervals[i],x['end']-x.start)
                local _,after=graph(camera[x.index]);check(equal(after,signature),'CAMERA_MASK_CHANGED')
            end
            check(equal(copied,layout(target,true)),'CAMERA_TIMELINE_CHANGED')
            check(equal(before,layout(source,true)),'CAMERA_SOURCE_CHANGED')
            for _,x in ipairs(p.items) do
                local original=graph(items[x.index]);check(not original.Blend:GetExpression()
                    and original:GetInput('Blend')==1,'CAMERA_SOURCE_CHANGED')
            end
        end
    end
    local function inspect(item)
        local merge=graph(item);local expression=merge.Blend:GetExpression()
        check(type(expression)=='string','CAMERA_NO_VISIBILITY_EXPRESSION')
        local intervals={};local terms={};local checksum=0;local previous=-1
        for lo,hi in expression:gmatch('time >= (%d+) and time < (%d+)') do
            lo=tonumber(lo);hi=tonumber(hi)
            check(lo>previous and lo<hi and hi<=item:GetEnd()-item:GetStart(),'CAMERA_EXPRESSION_CHANGED')
            previous=hi;intervals[#intervals+1]={lo,hi}
            terms[#terms+1]=string.format('(time >= %d and time < %d)',lo,hi)
            checksum=(checksum*65599+lo)%2147483647
            checksum=(checksum*65599+hi)%2147483647
        end
        check(#intervals>=1 and #intervals<=64,'CAMERA_EXPRESSION_CHANGED')
        check(expression=='iif('..table.concat(terms,' or ')..', 0, 1)','CAMERA_EXPRESSION_CHANGED')
        verify(merge,expression,intervals,item:GetEnd()-item:GetStart())
        return string.format('visibility_%d_%d_%d_%d',#intervals,checksum,intervals[1][1],intervals[#intervals][2])
    end
    -- Capture only canonical source-bound visibility, including an unanimated circle.
    local function capture(item)
        local merge=graph(item)
        local expression=merge.Blend:GetExpression()
        if not expression then
            check(not merge.Blend:GetConnectedOutput() and merge:GetInput('Blend')==1,'CAMERA_ALREADY_ANIMATED')
            return {}
        end
        inspect(item)
        local ranges={}
        for lo,hi in expression:gmatch('time >= (%d+) and time < (%d+)') do
            ranges[#ranges+1]={tonumber(lo),tonumber(hi)}
        end
        return ranges
    end
    local function transfer(item,ranges,offset,length)
        local merge=graph(item);local clipped={};local terms={}
        for _,r in ipairs(ranges) do
            local lo=math.max(0,r[1]-offset);local hi=math.min(length,r[2]-offset)
            if lo<hi then
                clipped[#clipped+1]={lo,hi}
                terms[#terms+1]=string.format('(time >= %d and time < %d)',lo,hi)
            end
        end
        if #clipped>0 then
            local expression='iif('..table.concat(terms,' or ')..', 0, 1)'
            merge.Blend:SetExpression(expression)
            verify(merge,expression,clipped,length)
        else
            merge.Blend:SetExpression(nil)
            merge:SetInput('Blend',1)
        end
        check(equal(capture(item),clipped),'CAMERA_TRANSFER_CHANGED')
        return clipped
    end
    return {preflight=preflight,inspect=inspect,capture=capture,transfer=transfer}
end
