#!/usr/bin/env python3
"""Apply a conversion manifest using the installed Resolve scripting API."""
import argparse,json,os,sys,platform,shutil
from pathlib import Path
from fractions import Fraction
from atem import probe,frames
from timing import Timing

def connect():
 roots={'Darwin':'/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules','Windows':os.path.expandvars(r'%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules'),'Linux':'/opt/resolve/Developer/Scripting/Modules'}
 sys.path.insert(0,os.environ.get('RESOLVE_SCRIPT_MODULES',roots[platform.system()]))
 import DaVinciResolveScript
 r=DaVinciResolveScript.scriptapp('Resolve')
 if not r:raise RuntimeError('Cannot connect to Resolve. Start Resolve; allow local scripting and local network access for this task. Do not change network-wide scripting settings.')
 return r

def clips(folder):
 yield from folder.GetClipList()
 for f in folder.GetSubFolderList():yield from clips(f)

def item_type(item):
 method=getattr(item,'GetType',None)
 return method() if callable(method) else 'video'

def video_items(t):
 return [x for x in (t.GetItemListInTrack('video',1) or []) if item_type(x)=='video']

def validate(t,plan):
 timing=Timing.from_plan(plan)
 actual_rate=str(t.GetSetting('timelineFrameRate')).split()[0]
 if Fraction(actual_rate)!=Fraction(timing.resolve_rate):raise RuntimeError(f'Resolve timeline rate mismatch: {actual_rate}')
 if timing.frames(t.GetStartTimecode())!=plan['origin']%timing.day:raise RuntimeError('Resolve timeline timecode origin or DF/NDF mismatch')
 actual=video_items(t);expected=[c for c in plan['cuts'] if c['angle'] not in (None,0)]
 if len(actual)!=len(expected):raise RuntimeError(f'Video item count {len(actual)} != {len(expected)}')
 for i,(item,cut) in enumerate(zip(actual,expected)):
  session=plan['sessions'][cut['session']];name=f'{session["multicam_name"]} - {cut["angle"]} {plan["camera_names"][str(cut["angle"])]}'
  m=item.GetMediaPoolItem()
  if not m or m.GetClipProperty('Type')!='Multicam':raise RuntimeError(f'Item {i} is not native multicam')
  if (item.GetStart(),item.GetEnd(),item.GetName(),item.GetLeftOffset())!=(cut['start'],cut['end'],name,cut['start']-session['start']):raise RuntimeError(f'Cut {i} timing/angle differs: {item.GetName()}')
 return len(actual)

def transition_inventory(t,plan,complete=False):
 expected={(x['start'],x['end']):x for x in plan.get('transitions',[]) if not x.get('unresolved')}
 if len(expected)!=sum(not x.get('unresolved') for x in plan.get('transitions',[])):raise RuntimeError('Duplicate planned transition intervals')
 actual={}
 for item in (t.GetItemListInTrack('video',1) or []):
  if item_type(item)!='transition':continue
  key=(item.GetStart(),item.GetEnd())
  if key in actual or key not in expected or item.GetName()!='Cross Dissolve' or item.GetDuration()!=expected[key]['duration_frames']:
   raise RuntimeError('Existing transition differs from this conversion; no automatic replacement is allowed')
  actual[key]=item
 if complete and set(actual)!=set(expected):raise RuntimeError('Missing reconstructed Resolve transitions')
 return actual

def review_marker_data(plan,row):
 return 'iso-assemble:mix:'+str(row['line'])+':'+str(row['end_line'])

def validate_review_markers(t,plan):
 markers=t.GetMarkers() or {}
 for row in plan.get('review_markers',[]):
  frame=row['frame']-plan['origin'];m=markers.get(frame)
  if not m or (m.get('name'),m.get('note'),m.get('duration'),m.get('customData'))!=(row['name'],row['note'],row['duration_frames'],review_marker_data(plan,row)):
   raise RuntimeError('Missing or changed ATEM Mix review marker')
 return len(plan.get('review_markers',[]))

def apply_transitions(t,plan):
 """Apply only explicit reviewed Mix plans; preserve every original multicam cut."""
 if not plan.get('transitions') and not plan.get('review_markers'):
  transition_inventory(t,plan,complete=True)
  return 0
 validate(t,plan)
 actual=transition_inventory(t,plan)
 indexed={n:item for (n,_),item in zip(((n,c) for n,c in enumerate(plan['cuts']) if c['angle'] not in (None,0)),video_items(t))}
 pending=[]
 for row in plan.get('transitions',[]):
  if row.get('unresolved'):continue
  left=indexed[row['from_cut_index']];right=indexed[row['to_cut_index']]
  a=plan['cuts'][row['from_cut_index']];b=plan['cuts'][row['to_cut_index']]
  if a['session']!=b['session'] or a['angle']!=row['from_angle'] or b['angle']!=row['to_angle'] or left.GetEnd()!=right.GetStart() or right.GetStart()!=row['end'] or left.GetStart()>row['start'] or right.GetLeftOffset()<row['duration_frames']:
   raise RuntimeError('Native multicam transition handles or adjacent cuts differ from the verified plan')
  if not callable(getattr(left,'AddTransition',None)):raise RuntimeError('This Resolve version cannot apply native multicam transitions')
  if (row['start'],row['end']) not in actual:pending.append((left,row))
 # Check all collisions before making changes, including markers on a safe rerun.
 markers=t.GetMarkers() or {}
 for row in plan.get('review_markers',[]):
  m=markers.get(row['frame']-plan['origin'])
  if m and (m.get('name'),m.get('note'),m.get('duration'),m.get('customData'))!=(row['name'],row['note'],row['duration_frames'],review_marker_data(plan,row)):
   raise RuntimeError('A different marker occupies a required review position; existing marker preserved')
 for left,row in pending:
  item=left.AddTransition(row['resolve_options'])
  if not item or item_type(item)!='transition' or (item.GetStart(),item.GetEnd(),item.GetDuration())!=(row['start'],row['end'],row['duration_frames']):raise RuntimeError('Resolve did not create the exact requested dissolve interval')
 for row in plan.get('review_markers',[]):
  frame=row['frame']-plan['origin']
  if frame not in markers and not t.AddMarker(frame,'Red',row['name'],row['note'],row['duration_frames'],review_marker_data(plan,row)):raise RuntimeError('Could not add required ATEM Mix review marker')
 validate(t,plan);validate_review_markers(t,plan)
 return len(transition_inventory(t,plan,complete=True))

def programs(root,timing=None):
 timing=timing or Timing()
 result=[]
 for path in sorted(Path(root).glob('*.mp4')):
  if path.name.startswith('._'):continue
  d=probe(path)
  if d['format'].get('tags',{}).get('com.apple.proapps.cameraName')!='0':continue
  v=next(x for x in d['streams'] if x['codec_type']=='video');a=next((x for x in d['streams'] if x['codec_type']=='audio'),None)
  if not a or a.get('channels')!=2 or a.get('sample_rate')!='48000':raise RuntimeError(f'Unverified program audio: {path}')
  if Fraction(v['avg_frame_rate'])!=timing.fps or Fraction(a['duration_ts'])*Fraction(a['time_base'])!=timing.seconds(int(v['nb_frames'])):raise RuntimeError(f'Program video/audio duration or rate mismatch: {path}')
  result.append(dict(path=str(path.resolve()),start=timing.frames(v['tags']['timecode']),frames=int(v['nb_frames'])))
 if not result:raise RuntimeError('No identifiable ATEM program mix (cameraName=0). Ask the user which mix to use.')
 return result

def append_verified(mp,t,m,start,count,kind,track=1):
 # Resolve 21 audio-only endpoint is exclusive, video endpoint normally inclusive.
 # Inspect the actual result; one bounded correction prevents silent off-by-one edits.
 for endpoint in (count-1,count):
  items=mp.AppendToTimeline([dict(mediaPoolItem=m,startFrame=0,endFrame=endpoint,recordFrame=start,mediaType=kind,trackIndex=track)])
  if not items or len(items)!=1:raise RuntimeError('Resolve failed to append exactly one item')
  x=items[0]
  if x.GetStart()==start and x.GetDuration()==count:return x
  if not t.DeleteClips(items,False):raise RuntimeError('Cannot remove unsuccessful append; stop to avoid duplicates')
 raise RuntimeError(f'Cannot append exact duration {count} for {m.GetName()}')

def apply(plan_path):
 plan_path=Path(plan_path).resolve();out=plan_path.parent;plan=json.loads(plan_path.read_text());timing=Timing.from_plan(plan);name=plan['name'];statefile=out/'resolve-state.json';r=connect();pm=r.GetProjectManager();existing=name in pm.GetProjectListInCurrentFolder()
 proof=plan.get('resolve_compatibility')
 if proof and proof.get('resolve_version')!=r.GetVersionString():raise RuntimeError('Resolve changed versions after the compatibility check. Retry Create Project to check the current version before conversion.')
 state=json.loads(statefile.read_text()) if statefile.exists() else None
 if existing and (not state or state.get('fingerprint')!=plan['fingerprint']):raise RuntimeError('Project name already exists without matching conversion state; choose a new project name. No existing project was modified.')
 print(f'Resolve {r.GetVersionString()}: {name}',flush=True)
 p=pm.LoadProject(name) if existing else pm.CreateProject(name)
 if not p:raise RuntimeError('Cannot create/load target project')
 if state and state['project_id']!=p.GetUniqueId():raise RuntimeError('Project identity differs from saved conversion state')
 previous_state=state or {}
 state=dict(fingerprint=plan['fingerprint'],project_id=p.GetUniqueId(),name=name,complete=False);statefile.write_text(json.dumps(state,indent=2))
 mp=p.GetMediaPool();all_t={p.GetTimelineByIndex(i).GetName():p.GetTimelineByIndex(i) for i in range(1,p.GetTimelineCount()+1)}
 edit=all_t.get(name+'_Edit')
 if not edit:
  if not p.SetSetting('timelineFrameRate',timing.resolve_rate+(' DF' if timing.drop else '')):raise RuntimeError('Resolve rejected the requested timeline frame rate')
  p.SetSetting('timelineResolutionWidth','1920');p.SetSetting('timelineResolutionHeight','1080')
  edit=mp.ImportTimelineFromFile(str(out/(name+'.fcpxml')))
  if not edit:raise RuntimeError('Resolve timeline import failed')
 count=validate(edit,plan);print(f'Validated {count} native multicam cuts',flush=True)
 transitions=apply_transitions(edit,plan)
 if transitions:print(f'Applied and verified {transitions} linear dissolves; {len(plan.get("review_markers",[]))} unresolved Mix events marked for review',flush=True)
 pg=programs(plan['media_root'],timing);selected=plan.get('audio',{'selected':'program','label':'ATEM Program Mix','files':pg});
 all_audio=[x['path'] for x in plan.get('audio_inventory',[]) if x['kind']=='audio_iso']
 mp.ImportMedia([x['path'] for x in pg]+all_audio);pool={c.GetClipProperty('File Path'):c for c in clips(mp.GetRootFolder())}
 session_media=[]
 selected_files=selected['files']
 for session in plan['sessions']:
  files=sorted((x for x in selected_files if session['start']<=x['start']<session['end']),key=lambda x:x['start']);cursor=session['start']
  for f in files:
   if f['start']!=cursor:raise RuntimeError('Program audio has a gap or overlap')
   cursor+=f['frames']
  if cursor!=session['end']:raise RuntimeError('Program audio does not cover recording')
  # Resolve may automatically span physical files. Account for each source once.
  cursor=session['start']
  while cursor<session['end']:
   f=next(x for x in files if x['start']==cursor);m=pool.get(f['path'])
   if not m:raise RuntimeError(f'No Resolve source at program boundary {cursor}')
   n=int(m.GetClipProperty('Frames') or f['frames'])
   if cursor+n>session['end']:raise RuntimeError('Program span exceeds recording boundary')
   session_media.append((m,cursor,n));cursor+=n
 p.SetCurrentTimeline(edit)
 audio=edit.GetItemListInTrack('audio',1)
 if audio:
  if [(a.GetStart(),a.GetEnd()) for a in audio]!=[(s,s+n) for _,s,n in session_media]:raise RuntimeError('Existing audio does not match verified program coverage; stop rather than duplicate')
  if [a.GetMediaPoolItem().GetClipProperty('File Path') for a in audio]!=[m.GetClipProperty('File Path') for m,_,_ in session_media]:raise RuntimeError('Existing audio uses a different mix; stop rather than replace it')
 else:
  for m,start,n in session_media:append_verified(mp,edit,m,start,n,2)
 edit.SetTrackName('audio',1,selected['label']+' - independent stereo')
 reference_name=name+'_Live_Program_Reference'
 if reference_name not in all_t and not any('Original_ATEM_Reference' in n for n in all_t):
  reference=mp.CreateEmptyTimeline(reference_name);reference.SetStartTimecode(edit.GetStartTimecode())
  for session in plan['sessions']:
   cursor=session['start']
   while cursor<session['end']:
    f=next(x for x in pg if x['start']==cursor);m=pool[f['path']];n=int(m.GetClipProperty('Frames'))
    if cursor+n>session['end']:raise RuntimeError('Program reference exceeds recording boundary')
    append_verified(mp,reference,m,cursor,n,1);append_verified(mp,reference,m,cursor,n,2);cursor+=n
  reference.SetTrackName('audio',1,'Original program mix')
 p.SetCurrentTimeline(edit)
 if not pm.SaveProject():raise RuntimeError('Resolve save failed')
 target=out/(name+'.drp')
 if target.resolve()==Path(plan['input']).resolve():raise RuntimeError('Export would overwrite original ATEM project')
 if target.exists():
  if previous_state.get('complete') and previous_state.get('export')==str(target):
   statefile.write_text(json.dumps(previous_state,indent=2));print(f'Already exported and validated: {target}',flush=True);return
  raise RuntimeError('Export destination already exists; refusing to overwrite')
 # Export is only allowed into this conversion-owned directory.
 if not pm.ExportProject(name,str(target)):raise RuntimeError('Resolve project export failed')
 state.update(complete=True,resolve_version=r.GetVersionString(),cuts_verified=count,transitions_verified=transitions,export=str(target));statefile.write_text(json.dumps(state,indent=2))
 print(f'Exported {target}. Reimport and UI verification remain required.',flush=True)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);a=p.parse_args()
 try:apply(a.manifest)
 except Exception as e:p.exit(2,f'Resolve conversion stopped: {e}\n')
if __name__=='__main__':main()
