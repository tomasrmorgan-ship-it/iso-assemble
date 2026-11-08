#!/usr/bin/env python3
"""Build native Resolve multicam FCPXML using verified ATEM timing. No transcoding."""
import argparse,json,sys,hashlib,xml.etree.ElementTree as E
from pathlib import Path
from atem import preflight,frames
from timing import Timing

def element(parent,tag,**attrs):return E.SubElement(parent,tag,{k:str(v) for k,v in attrs.items()})

def _mix_intervals(events, timing):
 """Read complete Mix state edges; never infer an unlogged destination angle."""
 pending={};previous={};session=None;result=[]
 for ev in events:
  if ev['session']!=session:
   if pending:raise ValueError('Incomplete Mix at recording boundary; review the original reference')
   previous={};session=ev['session']
  current={m.get('_index_',0):m for m in ev['state'].get('mixEffectBlocks',[])}
  for index,m in current.items():
   active=bool(m.get('transitionActive'));before=previous.get(index)
   if active:
    if m.get('transitionType')!='Mix':raise ValueError(f'Unsupported transition type at line {ev["line"]}; only reviewed Mix is supported')
    if not m.get('onAir') or m.get('transitionBackground') is False:
     raise ValueError(f'Mix does not operate on the active background at line {ev["line"]}')
    if index not in pending:
     if before is None:raise ValueError(f'Recording begins during an active Mix at line {ev["line"]}; start is unknown')
     pending[index]=dict(type='Mix',session=session,block=index,line=ev['line'],start=ev['frame'],
                         start_timecode=timing.timecode(ev['frame']),from_angle=m.get('source'),
                         position_samples=[],source_changes=[])
   if index in pending:
    if m.get('transitionType')!='Mix':raise ValueError(f'Transition type changed during Mix at line {ev["line"]}')
    item=pending[index];value=m.get('transitionPosition')
    if value is not None and (type(value) not in (int,float) or not 0<=value<=1):
     raise ValueError(f'Invalid Mix fader position at line {ev["line"]}: {value!r}')
    if value is not None and (not item['position_samples'] or item['position_samples'][-1]['value']!=value):
     item['position_samples'].append(dict(frame=ev['frame'],line=ev['line'],value=value))
    if before is not None and m.get('source')!=before.get('source') and ev['frame']>=item['start']:
     item['source_changes'].append(dict(frame=ev['frame'],line=ev['line'],from_angle=before.get('source'),to_angle=m.get('source')))
    if not active:
     item.update(end=ev['frame'],end_line=ev['line'],end_timecode=timing.timecode(ev['frame']),
                 duration_frames=ev['frame']-item['start'],to_angle=m.get('source'))
     if item['duration_frames']<=0:raise ValueError(f'Mix has nonpositive duration at lines {item["line"]}–{ev["line"]}')
     item['same_angle_endpoints']=item['from_angle']==item['to_angle']
     item['internal_source_changes']=[change for change in item['source_changes'] if change['frame']<item['end']]
     item['intermediate_fader_positions_logged']=any(0<sample['value']<1 for sample in item['position_samples'])
     result.append(item);del pending[index]
  if any(index not in current for index in pending):raise ValueError('Active Mix block disappeared before its end')
  previous=current
 if pending:raise ValueError('Incomplete Mix at end of recording; review the original reference')
 return result


def _plan_mix_transitions(intervals, cuts, sessions, names):
 """Keep the camera cut at the Mix END, with a left-aligned end dissolve.

 The incoming multicam item's source start stays at END; its left source handle
 supplies [START, END). FCPXML remains a native multicam cut assembly. The plan
 must be applied and its returned ranges checked in Resolve 21.1 or newer.
 """
 markers=[];warnings=[]
 if intervals:
  warnings.append('Mix review mode plans linear Cross Dissolves from recorded start/end frames. '
                  'ATEM endpoint states do not establish the original manual fader curve; compare with the program reference. '
                  'FCPXML contains the original multicam cuts; transitions remain pending separate Resolve application and validation.')
 for item in intervals:
  item.update(cut_frame=item['end'],requires_review=True,applied=False,
              curve='linear approximation; original manual curve unverified')
  reasons=[]
  if item['same_angle_endpoints']:reasons.append('same camera at both endpoints; the intermediate transition target is unknown')
  if item['internal_source_changes']:reasons.append('camera source changes inside the active Mix; preserve every logged switch')
  if item['from_angle'] not in names or item['to_angle'] not in names:
   reasons.append('Mix endpoint is not a verified camera angle')
  samples=item['position_samples']
  if not samples or samples[0]['value']!=0 or samples[-1]['value']!=1:
   reasons.append('fader endpoints are not a verified complete 0-to-1 Mix')
  left=[(i,c) for i,c in enumerate(cuts) if c['session']==item['session'] and c['end']==item['end']]
  right=[(i,c) for i,c in enumerate(cuts) if c['session']==item['session'] and c['start']==item['end']]
  if len(left)!=1 or len(right)!=1:
   reasons.append('no unique adjacent multicam cut pair at the recorded Mix end')
  else:
   li,lc=left[0];ri,rc=right[0]
   if lc['angle']!=item['from_angle'] or rc['angle']!=item['to_angle']:
    reasons.append('adjacent cut angles differ from the recorded Mix endpoints')
   if lc['start']>item['start']:
    reasons.append('a preserved cut or source-file boundary divides the proposed dissolve interval')
   s=sessions[item['session']]
   if item['start']<s['start'] or item['end']>=s['end']:
    reasons.append('insufficient recording handles for a complete two-sided Mix')
   item.update(from_cut_index=li,to_cut_index=ri,incoming_handle_frames=item['duration_frames'],
               incoming_source_start_frame=rc['start']-s['start'],
               incoming_handle_start_frame=item['start']-s['start'])
  item['unresolved']=bool(reasons)
  if reasons:
   item.update(status='unresolved_review',reconstruction='original_source_selections',review_reasons=reasons)
   note=(f'Mix lines {item["line"]}–{item["end_line"]}, {item["start_timecode"]}–{item["end_timecode"]}: '
         +'; '.join(reasons)+'. Original source selections retained; inspect the program reference.')
   warnings.append(note)
   markers.append(dict(frame=item['start'],end=item['end'],duration_frames=item['duration_frames'],
                       session=item['session'],line=item['line'],end_line=item['end_line'],
                       name='Unresolved ATEM Mix',note=note,requires_review=True))
  else:
   item.update(status='pending_resolve_application',reconstruction='linear_cross_dissolve',
               resolve_options=dict(type='Cross Dissolve',category='simple',position='end',
                                    alignment='left',duration=item['duration_frames']))
 return markers,warnings


def build(data,name,camera_names=None,mix_policy='strict'):
 if mix_policy not in ('strict','linear-review'):raise ValueError('Unknown Mix policy; use strict or linear-review')
 timing=Timing.from_plan(data);time=timing.xml_time
 media=data['media'];events=data['events'];names={x['camera']:x['name'] for x in media}
 if camera_names:names.update({int(k):v for k,v in camera_names.items()})
 sessions=[]
 for ev in events:
  if ev['session']<0:raise ValueError('Events before recording header are unsupported')
  if ev['session']==len(sessions): sessions.append({'start':ev['frame'],'end':None,'id':ev['state']['recordingId']})
  me=ev['state'].get('mixEffectBlocks',[])
  active=[x for x in me if x.get('onAir')]
  if len(active)>1:raise ValueError(f'Multiple active M/E blocks at line {ev["line"]}')
  for m in me:
   if m.get('transitionActive') and mix_policy=='strict' and m.get('transitionType')=='Mix' and m.get('fadeToBlack','Inactive')=='Inactive' and not any(k.get('onAir') for k in m.get('upstreamKeys',[])):
    raise ValueError(f'Unsupported active transition in strict mode at line {ev["line"]}: this is an ATEM Mix. For Resolve, enable "Rebuild mixes as linear dissolves; mark uncertain events for review", then scan again. Premiere does not support these Mix transitions.')
   if (m.get('transitionActive') and mix_policy=='strict') or m.get('fadeToBlack','Inactive')!='Inactive' or any(k.get('onAir') for k in m.get('upstreamKeys',[])):
    raise ValueError(f'Unsupported active transition, fade or key at line {ev["line"]}; retain original reference; conversion stopped')
  if any(k.get('onAir') for k in ev['state'].get('downstreamKeys',[])):raise ValueError(f'Active downstream key at line {ev["line"]}')
  if not active:sessions[ev['session']]['end']=ev['frame']
 transitions=_mix_intervals(events,timing) if mix_policy=='linear-review' else []
 for s in sessions:
  if s['end'] is None:raise ValueError('Recording has no explicit stop event')
  s['media']=[m for m in media if s['start']<=m['start']<s['end']]
  for camera in names:
   clips=sorted((m for m in s['media'] if m['camera']==camera),key=lambda m:m['start'])
   if not clips:raise ValueError(f'No media for angle {camera} in recording {s["id"]}')
   cursor=s['start']
   for m in clips:
    if m['start']!=cursor:raise ValueError(f'Gap or overlap in angle {camera} at {m["path"]}: {m["start"]-cursor} frames')
    cursor=m['end']
   if cursor!=s['end']:raise ValueError(f'Angle {camera} endpoint differs from recording stop by {cursor-s["end"]} frames')
 origin=sessions[0]['start'];end=sessions[-1]['end'];cuts=[]
 for i,ev in enumerate(events):
  stop=events[i+1]['frame'] if i+1<len(events) else end
  if stop<=ev['frame']:continue
  me=next((m for m in ev['state']['mixEffectBlocks'] if m.get('onAir')),None)
  source=me.get('source') if me else None
  if source is not None and source not in names and source!=0:raise ValueError(f'Unsupported source {source} at line {ev["line"]}')
  c=dict(start=ev['frame'],end=stop,angle=source,session=ev['session'],line=ev['line'])
  if cuts and all(c[k]==cuts[-1][k] for k in ('angle','session')) and 'sources' not in ev['update']:cuts[-1]['end']=stop
  else:cuts.append(c)
 review_markers,transition_warnings=_plan_mix_transitions(transitions,cuts,sessions,names)
 r=E.Element('fcpxml',version='1.8');res=element(r,'resources');element(res,'format',id='f1',name='ATEM 1080p '+timing.resolve_rate,frameDuration=time(1),width=1920,height=1080)
 for i,m in enumerate(media):
  m['asset_id']=f'a{i}';element(res,'asset',id=m['asset_id'],name=Path(m['path']).name,src=Path(m['path']).as_uri(),start=time(m['start']),duration=time(m['frames']),hasVideo=1,format='f1',hasAudio=1,audioSources=1,audioChannels=2)
 for si,s in enumerate(sessions):
  s['multicam_name']=f'{name}_Session_{si+1:02d}'
  m=element(res,'media',id=f'mc{si}',name=s['multicam_name']);mc=element(m,'multicam',format='f1',tcStart='0s',tcFormat=timing.display,duration=time(s['end']-s['start']))
  for cam,n in sorted(names.items()):
   angle=element(mc,'mc-angle',name=f'{cam} {n}',angleID=f'session{si}_angle{cam}')
   for src in sorted((x for x in s['media'] if x['camera']==cam),key=lambda x:x['start']):
    c=element(angle,'clip',name=Path(src['path']).name,offset=time(src['start']-s['start']),start=time(src['start']),duration=time(src['frames']),format='f1',tcFormat=timing.display)
    element(c,'video',ref=src['asset_id'],offset=time(src['start']),start=time(src['start']),duration=time(src['frames']))
 lib=element(r,'library');event=element(lib,'event',name=name);project=element(event,'project',name=name+'_Edit');seq=element(project,'sequence',format='f1',tcStart=time(origin),duration=time(end-origin),tcFormat=timing.display);sp=element(seq,'spine')
 for c in cuts:
  if c['angle'] in (None,0):element(sp,'gap',name='Not recording' if c['angle'] is None else 'Switcher black',offset=time(c['start']),start='0s',duration=time(c['end']-c['start']))
  else:
   s=sessions[c['session']];clip=element(sp,'mc-clip',name=s['multicam_name'],ref=f'mc{c["session"]}',offset=time(c['start']),start=time(c['start']-s['start']),duration=time(c['end']-c['start']),srcEnable='video');element(clip,'mc-source',angleID=f'session{c["session"]}_angle{c["angle"]}',srcEnable='video')
 E.indent(r)
 return E.tostring(r,encoding='utf-8',xml_declaration=True),dict(timing=timing.data(),origin=origin,end=end,cuts=cuts,sessions=[{k:v for k,v in s.items() if k!='media'} for s in sessions],camera_names=names,mix_policy=mix_policy,transitions=transitions,review_markers=review_markers,transition_warnings=transition_warnings)

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--input',required=True);ap.add_argument('--media-root',required=True);ap.add_argument('--output-dir',required=True);ap.add_argument('--name',default='ATEM_Multicam');ap.add_argument('--camera-names',help='JSON mapping camera numbers to names');ap.add_argument('--repair-prefix',nargs=2);ap.add_argument('--dry-run',action='store_true');ap.add_argument('--mix-policy',choices=('strict','linear-review'),default='strict',help='Opt in to reviewed linear Mix plans; Resolve application and reference review are still required')
 a=ap.parse_args()
 try:
  if '/' in a.name or '\\' in a.name or a.name in ('.','..'):raise ValueError('Project name must not be a path')
  out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
  data=preflight(a.input,a.media_root,a.repair_prefix);xml,plan=build(data,a.name,json.loads(a.camera_names) if a.camera_names else None,mix_policy=a.mix_policy)
  signature=xml+(json.dumps(plan['transitions'],sort_keys=True).encode() if plan['transitions'] else b'')
  fingerprint=hashlib.sha256(signature).hexdigest();manifest=out/'conversion.json'
  if manifest.exists() and json.loads(manifest.read_text())['fingerprint']!=fingerprint:raise ValueError('Output already contains a different conversion; select a new directory')
  plan.update(fingerprint=fingerprint,input_sha256=data['sha256'],input=data['input'],media_root=str(Path(a.media_root).resolve()),name=a.name,warnings=data['warnings']+plan['transition_warnings'],media=[{k:v for k,v in m.items() if k!='probe'} for m in data['media']])
  manifest.write_text(json.dumps(plan,indent=2));(out/'preflight.json').write_text(json.dumps(data,indent=2))
  if not a.dry_run:(out/(a.name+'.fcpxml')).write_bytes(xml)
  print(f'{"Dry run" if a.dry_run else "Interchange ready"}: {len(data["media"])} sources, {len(plan["sessions"])} recording sessions, {sum(c["angle"] not in (None,0) for c in plan["cuts"])} editable cuts. Resolve import and validation still required.')
  if plan['transitions']:print(f'Mix review: {sum(not t["unresolved"] for t in plan["transitions"])} linear transitions planned, {sum(t["unresolved"] for t in plan["transitions"])} unresolved intervals marked. FCPXML contains cuts only; apply and validate the transition plan in Resolve.')
 except (ValueError,OSError,KeyError) as e:ap.exit(2,f'Conversion stopped: {e}\n')
if __name__=='__main__':main()
