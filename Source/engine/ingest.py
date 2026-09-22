#!/usr/bin/env python3
"""Discover a complete ATEM recording root, then select its independent primary audio."""
import argparse,hashlib,json,re,sys
from pathlib import Path
from fractions import Fraction
from atem import probe,parse,preflight,frames
from convert import build
from timing import Timing

def project_candidates(root):
 valid=[]
 for p in sorted(root.rglob('*.drp')):
  if p.name.startswith('._'):continue
  try:
   with p.open() as f:r=json.loads(f.readline())
   if isinstance(r,dict) and 'masterTimecode' in r:valid.append(p)
  except (UnicodeError,ValueError,OSError):continue
 return valid

def discover_project(root,explicit=None):
 if explicit:return Path(explicit).resolve()
 valid=project_candidates(root)
 if len(valid)!=1:raise ValueError(f'Found {len(valid)} ATEM projects; specify --project. Candidates: {valid}')
 return valid[0]

def repair_for(root,project,explicit=None):
 if explicit:return explicit
 _,sources=parse(project)
 if all((root/f).is_file() for f in sources):return None
 # Repair only the common camera filename prefix when every replacement exists.
 prefixes=set()
 for f in sources:
  m=re.fullmatch(r'(.+) CAM \d+ \d+\.mp4',Path(f).name)
  if not m:raise ValueError('Missing references cannot be safely repaired; use --repair-prefix')
  prefixes.add(m[1])
 if len(prefixes)==1:
  old=next(iter(prefixes));new=root.name
  if all((root/f.replace(old,new)).is_file() for f in sources):return [old,new]
 raise ValueError('Cannot infer one verified filename repair; use --repair-prefix')

def audio_catalog(root,plan):
 timing=Timing.from_plan(plan)
 root=Path(root).resolve();candidates={};inventory=[];warnings=[]
 camera_paths={m['path'] for m in plan['media']}
 for path in sorted(root.rglob('*')):
  if not path.is_file() or path.name.startswith('._') or path.suffix.lower() not in ('.wav','.mp4','.mov','.aif','.aiff','.flac'):continue
  resolved=str(path.resolve())
  if not path.resolve().is_relative_to(root):raise ValueError(f'Media symlink escapes root: {path}')
  if resolved in camera_paths:inventory.append(dict(path=resolved,kind='camera_iso'));continue
  print(f'Inspect audio: {path.name}',file=sys.stderr)
  d=probe(path);a=next((x for x in d['streams'] if x['codec_type']=='audio'),None);tags=d['format'].get('tags',{})
  if not a:inventory.append(dict(path=resolved,kind='other_media'));continue
  duration=Fraction(a['duration_ts'])*Fraction(a['time_base']);n=duration*timing.fps
  row=dict(path=resolved,kind='audio_iso' if path.suffix.lower() in ('.wav','.aif','.aiff','.flac') else 'program_or_other',sample_rate=int(a['sample_rate']),channels=a['channels'],duration_seconds=str(duration),frames=int(n) if n.denominator==1 else None,tags=tags)
  inventory.append(row)
  if tags.get('com.apple.proapps.cameraName')=='0':
   v=next(x for x in d['streams'] if x['codec_type']=='video');start=timing.frames(v['tags']['timecode']);key='program';label='ATEM stereo program mix'
   if Fraction(v['avg_frame_rate'])!=timing.fps or n.denominator!=1 or int(n)!=int(v['nb_frames']):raise ValueError(f'Program audio/video duration mismatch: {path}')
  else:
   m=re.search(r'(CAM|MIC)\s+(\d+)\s+(\d+)\.(?:wav|aiff?|flac)$',path.name,re.I)
   if not m:
    warnings.append(f'Imported but not selectable automatically (unrecognized audio source name): {path.name}');continue
   key=f'{m[1].lower()}{int(m[2])}';label=f'{m[1].upper()} {int(m[2])} ISO'
   creation=tags.get('creation_time','')
   matches=[s for s in plan['sessions'] if s['end']-s['start']==n and any(e['session']==i and e['state']['masterTimecode'][:8]==creation for i,x in enumerate(plan['sessions']) if x is s for e in plan.get('_events',[])[:])]
   # Match BWF start directly first; otherwise require exact recording duration AND original creation clock.
   ref=Fraction(int(tags['time_reference']),row['sample_rate']) if tags.get('time_reference','').isdigit() else None
   direct=[s for s in plan['sessions'] if s['end']-s['start']==n and ref is not None and abs(ref-timing.seconds(s['start']))<=Fraction(1,row['sample_rate'])]
   match=direct or matches
   if len(match)!=1:
    warnings.append(f'Imported but not selectable: cannot verify session timing for {path.name}');continue
   start=match[0]['start'];expected=timing.seconds(start)
   if ref is not None and abs(ref-expected)>Fraction(1,row['sample_rate']):
    boundaries={m['start'] for m in plan['media'] if match[0]['start']<m['start']<match[0]['end']}
    if not any(abs(ref-timing.seconds(b))<=Fraction(1,row['sample_rate']) for b in boundaries):raise ValueError(f'Conflicting BWF timestamp in {path}; manual timing verification required')
    warnings.append(f'{path.name}: BWF time_reference points to internal file rollover; mapped full-length WAV using original creation clock plus exact recording duration')
  row.update(source_id=key,start=start,end=start+int(n))
  c=candidates.setdefault(key,dict(id=key,label=label,files=[]));c['files'].append(dict(path=resolved,start=start,end=start+int(n),frames=int(n),channels=row['channels'],sample_rate=row['sample_rate']))
 for c in candidates.values():
  c['files'].sort(key=lambda x:x['start']);c['selectable']=True;c['issues']=[]
  for s in plan['sessions']:
   cursor=s['start']
   for f in [f for f in c['files'] if s['start']<=f['start']<s['end']]:
    if f['start']!=cursor:c['issues'].append(f'Gap/overlap at {f["path"]}')
    cursor=f['end']
   if cursor!=s['end']:c['issues'].append(f'Incomplete coverage for recording {s["id"]}')
  if any(f['sample_rate']!=48000 or f['channels']!=2 for f in c['files']):c['issues'].append('This version requires 48 kHz stereo')
  c['selectable']=not c['issues']
 return dict(root=str(root),inventory=inventory,candidates=list(candidates.values()),warnings=warnings)

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',required=True);ap.add_argument('--project');ap.add_argument('--output-dir',required=True);ap.add_argument('--name');ap.add_argument('--primary-audio',help='program, mic1, mic2, cam1..cam8; omit to list choices without assembly');ap.add_argument('--camera-names');ap.add_argument('--repair-prefix',nargs=2);ap.add_argument('--dry-run',action='store_true');a=ap.parse_args()
 try:
  root=Path(a.root).resolve();out=Path(a.output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
  project=discover_project(root,a.project);repair=repair_for(root,project,a.repair_prefix);data=preflight(project,root,repair);name=a.name or root.name+'_Multicam'
  if '/' in name or '\\' in name or name in ('.','..'):raise ValueError('Project name must not be a path')
  xml,plan=build(data,name,json.loads(a.camera_names) if a.camera_names else None);plan['media']=data['media'];plan['_events']=data['events'];catalog=audio_catalog(root,plan);plan.pop('_events')
  catalog.update(project=str(project),reference_repair=repair)
  (out/'audio-catalog.json').write_text(json.dumps(catalog,indent=2));(out/'preflight.json').write_text(json.dumps(data,indent=2))
  for c in catalog['candidates']:print(f'{c["id"]}: {c["label"]} ({len(c["files"])} files) — {"available" if c["selectable"] else c["issues"]}')
  if not a.primary_audio:print('Choose the primary audio with --primary-audio. All discovered audio ISOs will be imported, but only the selection will play.');return
  chosen=next((c for c in catalog['candidates'] if c['id']==a.primary_audio and c['selectable']),None)
  if not chosen:raise ValueError('Primary audio choice is unavailable; inspect audio-catalog.json')
  fingerprint=hashlib.sha256(xml+json.dumps(catalog,sort_keys=True).encode()+a.primary_audio.encode()).hexdigest();target=out/'conversion.json'
  if target.exists() and json.loads(target.read_text())['fingerprint']!=fingerprint:raise ValueError('Changed selection/configuration: use a new output directory and project name; do not overwrite an existing conversion')
  plan.update(fingerprint=fingerprint,input_sha256=data['sha256'],input=str(project),media_root=str(root),name=name,warnings=data['warnings']+catalog['warnings'],media=[{k:v for k,v in m.items() if k!='probe'} for m in data['media']],audio=dict(selected=chosen['id'],label=chosen['label'],files=chosen['files']),audio_inventory=catalog['inventory'])
  target.write_text(json.dumps(plan,indent=2))
  if not a.dry_run:(out/(name+'.fcpxml')).write_bytes(xml)
  print(f'{"Dry run" if a.dry_run else "Ready for Resolve assembly"}: {len(plan["media"])} camera files, {sum(x["kind"]=="audio_iso" for x in catalog["inventory"])} audio ISO files; primary={chosen["label"]}')
 except (ValueError,OSError,KeyError,StopIteration) as e:ap.exit(2,f'Root ingest stopped: {e}\n')
if __name__=='__main__':main()
