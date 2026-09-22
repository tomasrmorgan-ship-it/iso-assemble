#!/usr/bin/env python3
"""Build native Resolve multicam FCPXML using verified ATEM timing. No transcoding."""
import argparse,json,sys,hashlib,xml.etree.ElementTree as E
from pathlib import Path
from atem import preflight,frames
from timing import Timing

def element(parent,tag,**attrs):return E.SubElement(parent,tag,{k:str(v) for k,v in attrs.items()})
def build(data,name,camera_names=None):
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
   if m.get('transitionActive') or m.get('fadeToBlack','Inactive')!='Inactive' or any(k.get('onAir') for k in m.get('upstreamKeys',[])):
    raise ValueError(f'Unsupported active transition, fade or key at line {ev["line"]}; retain original reference; conversion stopped')
  if any(k.get('onAir') for k in ev['state'].get('downstreamKeys',[])):raise ValueError(f'Active downstream key at line {ev["line"]}')
  if not active:sessions[ev['session']]['end']=ev['frame']
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
 return E.tostring(r,encoding='utf-8',xml_declaration=True),dict(timing=timing.data(),origin=origin,end=end,cuts=cuts,sessions=[{k:v for k,v in s.items() if k!='media'} for s in sessions],camera_names=names)

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--input',required=True);ap.add_argument('--media-root',required=True);ap.add_argument('--output-dir',required=True);ap.add_argument('--name',default='ATEM_Multicam');ap.add_argument('--camera-names',help='JSON mapping camera numbers to names');ap.add_argument('--repair-prefix',nargs=2);ap.add_argument('--dry-run',action='store_true')
 a=ap.parse_args()
 try:
  if '/' in a.name or '\\' in a.name or a.name in ('.','..'):raise ValueError('Project name must not be a path')
  out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
  data=preflight(a.input,a.media_root,a.repair_prefix);xml,plan=build(data,a.name,json.loads(a.camera_names) if a.camera_names else None)
  fingerprint=hashlib.sha256(xml).hexdigest();manifest=out/'conversion.json'
  if manifest.exists() and json.loads(manifest.read_text())['fingerprint']!=fingerprint:raise ValueError('Output already contains a different conversion; select a new directory')
  plan.update(fingerprint=fingerprint,input_sha256=data['sha256'],input=data['input'],media_root=str(Path(a.media_root).resolve()),name=a.name,warnings=data['warnings'],media=[{k:v for k,v in m.items() if k!='probe'} for m in data['media']])
  manifest.write_text(json.dumps(plan,indent=2));(out/'preflight.json').write_text(json.dumps(data,indent=2))
  if not a.dry_run:(out/(a.name+'.fcpxml')).write_bytes(xml)
  print(f'{"Dry run" if a.dry_run else "Interchange ready"}: {len(data["media"])} sources, {len(plan["sessions"])} recording sessions, {sum(c["angle"] not in (None,0) for c in plan["cuts"])} editable cuts. Resolve import and validation still required.')
 except (ValueError,OSError,KeyError) as e:ap.exit(2,f'Conversion stopped: {e}\n')
if __name__=='__main__':main()
