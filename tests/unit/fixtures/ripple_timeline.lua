
    serial=0
    function copy(x)
      if type(x)~='table' then return x end
      local y={};for k,v in pairs(x) do y[k]=copy(v) end;return y
    end
    function item(k,s,e,head)
      serial=serial+1
      local x={id=tostring(serial),s=s,e=e,head=head,props={ZoomX=1},linked={}}
      x.GetUniqueId=function(self) return self.id end
      x.GetStart=function(self) return self.s end
      x.GetEnd=function(self) return self.e end
      x.GetSourceStartTime=function(self) return self.head/60 end
      x.GetSourceEndTime=function(self) return (self.head+self.e-self.s)/60 end
      x.GetMediaPoolItem=function() return assets[k] end
      x.GetProperty=function(self) return copy(self.props) end
      x.SetProperty=function(self,p) self.props=copy(p);return true end
      x.GetFusionCompCount=function() return 0 end
      x.GetLinkedItems=function(self) return self.linked end
      x.GetClipEnabled=function() return true end
      x.GetMarkers=function() return {} end
      x.GetTakesCount=function() if k~=3 then return 0 end end
      return x
    end
    assets={}
    for k=1,3 do
      local path=k==2 and 'cam' or 'screen'
      assets[k]={GetUniqueId=function() return path end,
        GetClipProperty=function(_,key) return key=='FPS' and '60' or path end}
    end
    function timeline(name)
      local t={name=name,tracks={{},{},{}}}
      t.GetUniqueId=function(self) return self.name end
      t.GetStartFrame=function() return 0 end
      t.GetEndFrame=function(self) return self.tracks[1][#self.tracks[1]].e end
      t.GetTrackCount=function(_,k) return k=='video' and 2 or k=='audio' and 1 or 0 end
      t.GetSetting=function() return '60' end
      t.GetMarkers=function() return {} end
      t.GetIsTrackLocked=function() return MODE=='locked' end
      t.GetIsTrackEnabled=function() return true end
      t.GetItemListInTrack=function(self,kind,index)
        local list=self.tracks[kind=='audio' and 3 or index]
        table.sort(list,function(a,b) return a.s<b.s end);return list
      end
      t.SetClipsLinked=function(_,items)
        for _,x in ipairs(items) do
          x.linked={}
          for _,y in ipairs(items) do
            if x~=y then table.insert(x.linked,y) end
          end
        end
        return true
      end
      t.DuplicateTimeline=function(self,n)
        target=timeline(n)
        for i=1,#self.tracks[1] do
          local triple={}
          for k=1,3 do local x=self.tracks[k][i];local y=item(k,x.s,x.e,x.head)
            table.insert(target.tracks[k],y);triple[k]=y end
          target:SetClipsLinked(triple)
        end
        return target
      end
      t.DeleteClips=function(self,items,ripple)
        local ids={};local intervals={}
        for _,x in ipairs(items) do ids[x.id]=true;intervals[x.s]=x.e end
        for k=1,3 do
          local keep={}
          for _,x in ipairs(self.tracks[k]) do
            if not ids[x.id] then
              local shift=0
              if ripple then
                for lo,hi in pairs(intervals) do
                  if hi<=x.s then shift=shift+hi-lo end
                end
              end
              x.s=x.s-shift;x.e=x.e-shift;keep[#keep+1]=x
            end
          end
          self.tracks[k]=keep
        end
        return true
      end
      return t
    end
    source=timeline('source');current=source
    for i=1,4 do
      local triple={}
      for k=1,3 do local x=item(k,(i-1)*100,i*100,(i-1)*200);
        source.tracks[k][i]=x;triple[k]=x end
      source:SetClipsLinked(triple)
    end
    pool={AppendToTimeline=function(_,requests)
      local r=requests[1];local k=r.mediaType==2 and 3 or r.trackIndex
      local x=item(k,r.recordFrame,r.recordFrame+r.endFrame-r.startFrame,r.startFrame)
      table.insert(current.tracks[k],x);return {x}
    end}
    project={GetCurrentTimeline=function() return current end,
      SetCurrentTimeline=function(_,t) current=t;return true end,
      GetMediaPool=function() return pool end}
    h={check=function(x,e) if not x then error(e,0) end end,
      timelines=function(_,name) if name=='source' then return source end end,
      allowed=function() return true end,normalized=function(x) return x end}
    dofile=function() return function() return {} end end
    a={timeline_name='source',ripple_span={name='copy',start_frame=40,end_frame=260,
      expected_timeline_start=0,expected_timeline_end=400,groups={}}}
    for i=1,3 do a.ripple_span.groups[i]={index=i,start=(i-1)*100,['end']=i*100,
      screen_source_start=(i-1)*200,camera_source_start=(i-1)*200,
      screen_path='screen',camera_path='cam'} end
    if MODE=='wrong_source' then a.ripple_span.groups[2].screen_path='wrong' end
    if MODE=='wrong_bounds' then a.ripple_span.groups[2].start=101 end
