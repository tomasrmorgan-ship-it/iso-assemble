#!/usr/bin/env python3
"""Read-only validation of Premiere 26.2's saved native project against the plan.
No project XML is modified. Unknown structures fail closed.
"""
import gzip,json,xml.etree.ElementTree as E
from pathlib import Path
from timing import Timing

def verify(project,manifest):
 plan=json.loads(Path(manifest).read_text()) if not isinstance(manifest,dict) else manifest
 TICKS=Timing.from_plan(plan).ticks
 raw=Path(project).read_bytes();root=E.fromstring(gzip.decompress(raw) if raw[:2]==b'\x1f\x8b' else raw)
 ids={e.get('ObjectID'):e for e in root if e.get('ObjectID')};uids={e.get('ObjectUID'):e for e in root if e.get('ObjectUID')}
 def ref(e):
  if e is None:raise ValueError('Missing native project reference')
  return ids[e.get('ObjectRef')] if e.get('ObjectRef') else uids[e.get('ObjectURef')]
 def frame(text):
  t=int(text or '0')
  if t%TICKS:raise ValueError(f'Non-frame-aligned native timing: {t}')
  return t//TICKS
 def tracks(seq,kind):
  result=[]
  for x in seq.findall('TrackGroups/TrackGroup/Second'):
   g=ref(x)
   if g.tag==kind+'TrackGroup':result.extend(ref(t) for t in g.findall('TrackGroup/Tracks/Track'))
  return result
 def items(track):return [ref(x) for x in track.findall('ClipTrack/ClipItems/TrackItems/TrackItem')]
 def clip(item):return ref(ref(item.find('ClipTrackItem/SubClip')).find('Clip'))
 def source(c):return ref(c.find('Clip/Source'))
 def media(c):return ref(source(c).find('MediaSource/Media'))
 def path(m):return '/'+m.findtext('ActualMediaFilePath').lstrip('/')
 def interval(item):
  t=item.find('ClipTrackItem/TrackItem');return frame(t.findtext('Start')),frame(t.findtext('End'))
 seqs=[s for s in root.findall('Sequence') if s.findtext('Name')==plan['name']+'_Edit']
 if len(seqs)!=1:raise ValueError('Expected exactly one main edit sequence')
 seq=seqs[0];origin=frame(seq.findtext('Node/Properties/MZ.ZeroPoint'))
 if origin!=plan['origin']:raise ValueError('Sequence timecode origin mismatch')
 vt=tracks(seq,'Video')
 if len(vt)!=1:raise ValueError('Expected one multicam video track')
 native=items(vt[0]);expected=plan['cuts']
 if len(native)!=len(expected):raise ValueError(f'Cut count mismatch: {len(native)} versus {len(expected)}')
 groups={}
 for item,want in zip(native,expected):
  c=clip(item);a,b=interval(item)
  if c.findtext('Clip/IsMulticam')!='true':raise ValueError('Found a flattened clip')
  got=(a+origin,b+origin,int(c.findtext('Clip/SelectedTrackIndex') or 0)+1,frame(c.findtext('Clip/InPoint')))
  target=(want['start'],want['end'],want['angle'],want['source_in'])
  if got!=target:raise ValueError(f'Native cut mismatch: {got} versus {target}')
  mc=ref(source(c).find('SequenceSource/Sequence'));key=mc.get('ObjectUID');groups[key]=(mc,want['group_start'],want['group_end'])
 if len(groups)!=plan['native_multicam_groups']:raise ValueError('Native multicam source count mismatch')
 camera_paths=[];boundary_checks=[]
 for mc,start,end in groups.values():
  ts=tracks(mc,'Video')
  if len(ts)!=len(plan['camera_names']):raise ValueError('Missing multicam camera track')
  for camera,track in enumerate(ts,1):
   its=items(track)
   if len(its)!=1:raise ValueError('Unexpected source track structure')
   item=its[0];c=clip(item);m=media(c);p=path(m);camera_paths.append(p)
   if interval(item)!=(0,end-start) or frame(c.findtext('Clip/InPoint'))!=0:raise ValueError('Source alignment/duration mismatch')
   if frame(m.findtext('AlternateStart'))!=start:raise ValueError('Source timecode mismatch')
   name=ref(item.find('ClipTrackItem/SubClip')).findtext('Name','')
   if name!=str(camera)+' '+plan['camera_names'][str(camera)]:raise ValueError(f'Angle name mismatch: {name}')
   boundary_checks.append(dict(camera=camera,path=p,first_frame=start,last_frame=end-1))
 ats=tracks(seq,'Audio')
 if len(ats)!=1:raise ValueError('Expected one independent stereo audio track')
 ai=items(ats[0]);af=plan['audio']['files']
 if len(ai)!=len(af):raise ValueError('Primary audio file count mismatch')
 for item,want in zip(ai,af):
  c=clip(item);a,b=interval(item)
  if (a+origin,b+origin)!=(want['start'],want['end']) or path(media(c))!=want['path']:raise ValueError('Primary audio path/timing mismatch')
  channels=[int(ref(x).findtext('ChannelIndex') or 0) for x in c.findall('SecondaryContents/SecondaryContentItem')]
  if channels!=[0,1]:raise ValueError(f'Stereo channels not preserved: {channels}')
  if c.findtext('Clip/IsMulticam')=='true':raise ValueError('Audio must be independent of multicam')
 actual={path(m) for m in root.findall('Media') if m.find('ActualMediaFilePath') is not None}
 missing=set(plan['media_paths'])-actual
 if missing:raise ValueError(f'Missing imported media: {sorted(missing)}')
 unresolved=[p for p in actual if not Path(p).is_file()]
 if unresolved:raise ValueError(f'Unresolved media: {unresolved}')
 return dict(project=str(project),native_multicam_cuts_verified=len(native),original_live_cuts=plan['original_live_cuts'],native_multicam_groups=len(groups),camera_files=len(set(camera_paths)),all_media_files=len(actual),audio_source=plan['audio']['id'],stereo_channels=[0,1],audio_independent=True,technical_splices=plan['technical_splices'],boundary_checks=boundary_checks,all_media_paths_exist=True,method='Read-only inspection of Premiere-saved native project; checks exact integer ticks, selected native multicam track, media paths, source timing and stereo channels. UI reopen/angle switching reported separately.')

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('project');p.add_argument('manifest');a=p.parse_args();print(json.dumps(verify(a.project,a.manifest),indent=2))
