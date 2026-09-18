-- A temporal rectangle on screen V1, underneath separate camera tracks.
return function(h)
    local check=h.check
    local function equal(a,b)
        if type(a)~=type(b) then return false end
        if type(a)~="table" then return a==b end
        for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
        for k in pairs(b) do if a[k]==nil then return false end end
        return true
    end
    local function state(t,selected)
        local result={start=t:GetStartFrame(),finish=t:GetEndFrame(),fps=t:GetSetting("timelineFrameRate"),items={}}
        for _,kind in ipairs({"video","audio","subtitle"}) do
            result[kind]=t:GetTrackCount(kind)
            for track=1,t:GetTrackCount(kind) do
                for _,item in ipairs(t:GetItemListInTrack(kind,track) or {}) do
                    local id=item:GetUniqueId();local media=item:GetMediaPoolItem();local linked={}
                    for _,v in ipairs(item:GetLinkedItems() or {}) do linked[v:GetUniqueId()]=true end
                    result.items[id]={kind=kind,track=track,start=item:GetStart(),finish=item:GetEnd(),
                        source_start=item:GetSourceStartTime(),source_end=item:GetSourceEndTime(),
                        media=media and media:GetUniqueId() or "",props=item:GetProperty(),links=linked,
                        enabled=item:GetClipEnabled(),fusion=not selected[id] and item:GetFusionCompCount() or -1}
                end
            end
        end
        return result
    end
    local function graph(item)
        check(item:GetFusionCompCount()==1,"PRIVACY_GRAPH_CHANGED")
        local comp=item:GetFusionCompByIndex(1)
        local input=comp:FindTool("MediaIn1");local output=comp:FindTool("MediaOut1")
        local blur=comp:FindTool("ResolveAgentPrivacyBlur")
        local mask=comp:FindTool("ResolveAgentPrivacyMask")
        check(input and output and blur and mask,"PRIVACY_GRAPH_CHANGED")
        check(blur:GetAttrs().TOOLB_PassThrough~=true and mask:GetAttrs().TOOLB_PassThrough~=true,"PRIVACY_GRAPH_CHANGED")
        local function connected(pin,tool)
            local out=pin:GetConnectedOutput()
            return out and out:GetTool():GetAttrs().TOOLS_Name==tool:GetAttrs().TOOLS_Name
        end
        check(connected(output.Input,blur) and connected(blur.Input,input)
            and connected(blur.EffectMask,mask),"PRIVACY_GRAPH_CHANGED")
        local n=0;for _ in pairs(comp:GetToolList(false)) do n=n+1 end
        check(n==4,"PRIVACY_GRAPH_CHANGED")
        return mask,blur,n
    end
    local function inspect(item)
        local mask,blur,n=graph(item)
        local expression=mask.Level:GetExpression()
        check(type(expression)=="string","PRIVACY_EXPRESSION_CHANGED")
        local first=tonumber(expression:match("time >= (%d+)"))
        local last=tonumber(expression:match("time < (%d+)"))
        check(first and last and first<last,"PRIVACY_EXPRESSION_CHANGED")
        local center=mask:GetInput("Center")
        local function milli(v) return math.floor(v*1000+0.5) end
        local count=0;local checksum=0;local finish=last;local terms={};local previous=-1
        for lo,hi in expression:gmatch("time >= (%d+) and time < (%d+)") do
            lo=tonumber(lo);hi=tonumber(hi);count=count+1
            check(lo>previous and lo<hi and hi<=item:GetEnd()-item:GetStart(),"PRIVACY_EXPRESSION_CHANGED")
            previous=hi;terms[#terms+1]=string.format("(time >= %d and time < %d)",lo,hi)
            check(mask:GetInput("Level",lo-1)==0 and mask:GetInput("Level",lo)==1
                and mask:GetInput("Level",hi-1)==1 and mask:GetInput("Level",hi)==0,"PRIVACY_TIME_FAILED")
            checksum=(checksum*65599+lo)%2147483647
            checksum=(checksum*65599+hi)%2147483647
            finish=hi
        end
        check(count>=1 and count<=64,"PRIVACY_EXPRESSION_CHANGED")
        local canonical="iif("..table.concat(terms," or ")..", 1, 0)"
        local legacy=string.format("iif(time >= %d and time < %d, 1, 0)",first,last)
        check(expression==canonical or (count==1 and expression==legacy),"PRIVACY_EXPRESSION_CHANGED")
        return string.format("privacy2_%d_1_%d_%d_%d_%d_%d_%d_%d_%d_%d_%d_%d_%d_%d",n,first,finish,
            milli(blur:GetInput("XBlurSize")),milli(center[1]),milli(center[2]),
            milli(mask:GetInput("Width")),milli(mask:GetInput("Height")),
            mask:GetInput("Level",first-1),mask:GetInput("Level",first),
            mask:GetInput("Level",last-1),mask:GetInput("Level",last),count,checksum)
    end
    local function preflight(project,a,defer_state)
        local t=h.timelines(project,a.timeline_name)
        check(t~=nil,"TIMELINE_NOT_FOUND")
        check(project:GetCurrentTimeline():GetUniqueId()==t:GetUniqueId(),"PRIVACY_ACTIVE_CHANGED")
        local item=(t:GetItemListInTrack("video",1) or {})[a.item_index]
        check(item and item:GetMediaPoolItem() and h.allowed(a.expected_media_path)
            and h.normalized(item:GetMediaPoolItem():GetClipProperty("File Path"))==h.normalized(a.expected_media_path),"SOURCE_CHANGED")
        local p=a.privacy_blur
        check(item:GetStart()==p.expected_clip_start and item:GetEnd()==p.expected_clip_end,"PRIVACY_BOUNDS_CHANGED")
        check(p.start_frame>=item:GetStart() and p.start_frame<p.end_frame and p.end_frame<=item:GetEnd(),"INVALID_RANGE")
        check(item:GetFusionCompCount()==0,"FUSION_COMP_EXISTS")
        check(not t:GetIsTrackLocked("video",1) and t:GetIsTrackEnabled("video",1)
            and item:GetClipEnabled(),"PRIVACY_TRACK_DISABLED")
        local selected={[item:GetUniqueId()]=true}
        local before=not defer_state and state(t,selected) or nil
        local first=p.start_frame-item:GetStart();local last=p.end_frame-item:GetStart()
        local ranges={{first,last}};local terms={string.format("(time >= %d and time < %d)",first,last)}
        for _,range in ipairs(p.additional_intervals or {}) do
            local lo=range.start_frame-item:GetStart();local hi=range.end_frame-item:GetStart()
            check(lo>ranges[#ranges][2] and lo<hi and hi<=item:GetEnd()-item:GetStart(),"INVALID_RANGE")
            ranges[#ranges+1]={lo,hi};terms[#terms+1]=string.format("(time >= %d and time < %d)",lo,hi)
        end
        local expression="iif("..table.concat(terms," or ")..", 1, 0)"
        return function()
            local comp=item:AddFusionComp();check(comp~=nil,"FUSION_UNAVAILABLE")
            local input=comp:FindTool("MediaIn1");local output=comp:FindTool("MediaOut1")
            check(input and output,"FUSION_IO_MISSING")
            local blur=comp:AddTool("Blur",0,0);local mask=comp:AddTool("RectangleMask",0,2)
            check(blur and mask,"FUSION_NODE_FAILED")
            blur:SetAttrs({TOOLS_Name="ResolveAgentPrivacyBlur"})
            mask:SetAttrs({TOOLS_Name="ResolveAgentPrivacyMask"})
            blur:SetInput("XBlurSize",p.strength);blur:SetInput("YBlurSize",p.strength)
            mask:SetInput("Center",{p.center_x,p.center_y})
            mask:SetInput("Width",p.width);mask:SetInput("Height",p.height)
            mask:SetInput("SoftEdge",0)
            mask.Level:SetExpression(expression)
            blur:ConnectInput("Input",input);blur:ConnectInput("EffectMask",mask)
            output:ConnectInput("Input",blur)
            graph(item)
            local center=mask:GetInput("Center")
            check(mask.Level:GetExpression()==expression and math.abs(blur:GetInput("XBlurSize")-p.strength)<0.001
                and math.abs(blur:GetInput("YBlurSize")-p.strength)<0.001
                and math.abs(center[1]-p.center_x)<0.00001
                and math.abs(center[2]-p.center_y)<0.00001
                and mask:GetInput("SoftEdge")==0
                and math.abs(mask:GetInput("Width")-p.width)<0.00001
                and math.abs(mask:GetInput("Height")-p.height)<0.00001,"PRIVACY_READBACK_FAILED")
            for _,range in ipairs(ranges) do
                check(mask:GetInput("Level",range[1]-1)==0 and mask:GetInput("Level",range[1])==1
                    and mask:GetInput("Level",range[2]-1)==1 and mask:GetInput("Level",range[2])==0,"PRIVACY_TIME_FAILED")
            end
            if before then check(equal(before,state(t,selected)),"PRIVACY_TIMELINE_CHANGED") end
        end
    end
    local function preflight_batch(project,a)
        local t=h.timelines(project,a.timeline_name);check(t~=nil,"TIMELINE_NOT_FOUND")
        check(type(a.privacy_batch)=="table" and #a.privacy_batch>=1 and #a.privacy_batch<=100,"INVALID_ARGUMENTS")
        local selected={};local operations={};local items=t:GetItemListInTrack("video",1) or {}
        for _,entry in ipairs(a.privacy_batch) do
            local item=items[entry.item_index];check(item~=nil,"ITEM_NOT_FOUND")
            local id=item:GetUniqueId();check(not selected[id],"DUPLICATE_ITEM")
            selected[id]=true
            operations[#operations+1]=preflight(project,{timeline_name=a.timeline_name,
                item_index=entry.item_index,expected_media_path=entry.expected_media_path,
                privacy_blur=entry.privacy_blur},true)
        end
        local before=state(t,selected)
        return function()
            for _,operation in ipairs(operations) do operation() end
            check(equal(before,state(t,selected)),"PRIVACY_TIMELINE_CHANGED")
        end
    end
    return {preflight=preflight,preflight_batch=preflight_batch,inspect=inspect}
end
