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

def repair_for(root,project,explicit=None,allow_mov=True):
 root=Path(root).resolve()
 _,sources=parse(project)
 def verified(references):
  paths=[(root/f).resolve() for f in references]
  return len(set(paths))==len(paths) and all(p.is_relative_to(root) and p.is_file() for p in paths)
 def missing_message(references,reason):
  missing=[f for f in references if not (root/f).resolve().is_relative_to(root) or not (root/f).is_file()]
  lines=[f'{reason} ATEM project {Path(project).name} references {len(missing)} missing or unavailable media file(s).',
         f'Recording root: {root}','Missing referenced files:']
  movs=[]
  for f in missing:
   candidate=(root/Path(f).with_suffix('.mov')).resolve()
   found=Path(f).suffix.lower()=='.mp4' and candidate.is_relative_to(root) and candidate.is_file()
   if found:movs.append(candidate)
   lines.append('  '+f+(' [same-stem MOV present; unverified]' if found else ''))
  if movs:
   lines.append(f'The DRP still references MP4 files, while corresponding MOV files are present for {len(movs)} of these references. '
                'MOV candidates are not automatically approved or substituted; matching names alone do not verify their frame counts, timestamps or timecodes.')
  lines.append('For MOV exports using one selected audio source, choose "Camera files with shared audio" in Output, then scan the recording folder again. That workflow reads camera media and WAVs directly and does not use the DRP.')
  lines.append('For Resolve/Premiere multicam conversion, restore the original referenced media or relink a separate project to replacement media after verifying frame counts, timestamps and timecodes. '
               'If only the filename prefix changed, ensure every referenced camera file is present under one consistent prefix; the recording folder name need not match that prefix.')
  lines.append('Advanced CLI: --repair-prefix OLD NEW supplies an explicit prefix mapping; every resulting reference must exist inside the recording root. No source files or project references were changed.')
  return '\n'.join(lines)
 if explicit:
  if len(explicit)!=2 or not all(isinstance(x,str) for x in explicit) or not explicit[0]:raise ValueError('Filename repair requires a nonempty old prefix and a new prefix.')
  repaired=[f.replace(*explicit) for f in sources]
  if verified(repaired):return explicit
  raise ValueError(missing_message(repaired,'The requested prefix mapping does not resolve every reference.'))
 if verified(sources):return None
 # Infer a common filename prefix from actual MP4 files, not just root.name.
 # Only a unique complete mapping is accepted; partial matches and MOVs never
 # authorize replacing references or assuming equivalent media timing.
 pattern=re.compile(r'(.+) CAM (\d+) (\d+)\.mp4',re.I)
 matches=[pattern.fullmatch(Path(f).name) for f in sources]
 prefixes={m[1] for m in matches if m}
 verified_repairs=[]
 if all(matches) and len(prefixes)==1:
  old=next(iter(prefixes));candidates={root.name}
  for f,expected in zip(sources,matches):
   parent=(root/Path(f).parent).resolve()
   if not parent.is_relative_to(root) or not parent.is_dir():continue
   for path in parent.iterdir():
    actual=pattern.fullmatch(path.name)
    if actual and (int(actual[2]),int(actual[3]))==(int(expected[2]),int(expected[3])):candidates.add(actual[1])
  for new in sorted(candidates):
   if new!=old and verified([f.replace(old,new) for f in sources]):verified_repairs.append([old,new])
 if len(verified_repairs)==1:
  inferred=verified_repairs[0]
  if any(verified([f]) for f in sources):return {f:f if verified([f]) else f.replace(*inferred) for f in sources}
  return inferred
 if allow_mov and all(matches):
  # These are candidate reference mappings only. preflight validates every
  # replacement's rate, exact duration, camera/part identity and ATEM timecode
  # before the conversion can use it. Existing original files always win.
  mov_pattern=re.compile(r'(.+) CAM (\d+) (\d+)\.mov',re.I)
  mov_prefixes=set();exact={};mov_options={}
  for f,expected in zip(sources,matches):
   original=(root/f).resolve()
   if original.is_relative_to(root) and original.is_file():exact[f]=f;continue
   parent=(root/Path(f).parent).resolve();options=[]
   if parent.is_relative_to(root) and parent.is_dir():
    for path in parent.iterdir():
     match=mov_pattern.fullmatch(path.name);resolved=path.resolve()
     if match and (int(match[2]),int(match[3]))==(int(expected[2]),int(expected[3])) and resolved.is_relative_to(root) and resolved.is_file():
      options.append((match[1],str(path.relative_to(root))));mov_prefixes.add(match[1])
   mov_options[f]=options
   same=[relative for prefix,relative in options if prefix==expected[1]]
   if len(same)>1:raise ValueError(missing_message(sources,f'Multiple same-stem MOV candidates exist for {f}; select one verified media set.'))
   if len(same)==1:exact[f]=same[0]
  mappings=[]
  if len(exact)==len(sources) and verified(exact.values()):mappings.append(exact)
  else:
   for prefix in sorted(mov_prefixes):
    mapping=dict(exact)
    for f in sources:
     if f in mapping:continue
     options=[relative for p,relative in mov_options.get(f,[]) if p==prefix]
     if len(options)==1:mapping[f]=options[0]
    if len(mapping)==len(sources) and verified(mapping.values()) and mapping not in mappings:mappings.append(mapping)
  if len(mappings)==1:return mappings[0]
  if len(mappings)>1:raise ValueError(missing_message(sources,'Multiple complete MOV replacement mappings are present; select the intended verified media set.'))
 reason='Multiple complete filename-prefix mappings are present; choose the intended media set.' if len(verified_repairs)>1 else 'No complete verified filename-prefix repair was found.'
 raise ValueError(missing_message(sources,reason))

def _verified_audio_reference(plan,timing):
 # Legacy callers without a full media inventory retain the existing BWF/
 # duration checks. Real conversion plans provide every verified camera part.
 media=plan.get('media',[])
 if not media or any(not {'camera','path','frames','start','timecode'}<=set(m) for m in media):return None
 groups={}
 for m in media:
  match=re.fullmatch(r'.+ CAM (\d+) (\d+)\.(mp4|mov)',Path(m['path']).name,re.I)
  if not match:return None  # Generic preverified plans keep the existing BWF checks.
  if int(match[1])!=m['camera']:raise ValueError('Verified camera identity differs from its filename: '+m['path'])
  group=groups.setdefault(m['camera'],{})
  part=int(match[2])
  if part in group:raise ValueError('Duplicate verified camera part in audio mapping: '+m['path'])
  group[part]=dict(path=m['path'],part=part,start=m['start'],media=dict(frames=m['frames'],fps=str(timing.fps),timecode=m['timecode']))
 reference=[groups[min(groups)][n] for n in sorted(groups[min(groups)])]
 expected=[(m['part'],m['start'],m['media']['frames'],m['media']['timecode']) for m in reference]
 for camera,parts in groups.items():
  actual=[(parts[n]['part'],parts[n]['start'],parts[n]['media']['frames'],parts[n]['media']['timecode']) for n in sorted(parts)]
  if actual!=expected:raise ValueError(f'Camera {camera}: part timing differs; audio cannot be matched by sample length safely')
 return reference

def audio_catalog(root,plan):
 timing=Timing.from_plan(plan)
 root=Path(root).resolve();candidates={};inventory=[];warnings=[]
 reference=_verified_audio_reference(plan,timing);iso_groups={}
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
   if reference is not None:
    samples=duration*row['sample_rate']
    row.update(source_id=key,part=int(m[3]),samples=int(samples) if samples.denominator==1 else None)
    group=iso_groups.setdefault(key,dict(label=label,rows=[]));group['rows'].append(row)
    continue
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
 if reference is not None:
  from attach_audio import _map_parts
  by_part={m['part']:m for m in reference}
  for key,group in iso_groups.items():
   rows=sorted(group['rows'],key=lambda row:row['part']);c=candidates.setdefault(key,dict(id=key,label=group['label'],files=[]))
   try:
    if len({r['part'] for r in rows})!=len(rows):raise ValueError('Duplicate audio part numbers')
    if any(r['sample_rate']!=48000 or r['channels']!=2 or r['samples'] is None for r in rows):raise ValueError('Exact audio mapping requires integer sample counts and 48 kHz stereo')
    mapping=_map_parts(reference,[dict(path=r['path'],media=dict(samples=r['samples'])) for r in rows])
    for row in rows:
     mapped=[m for m in mapping if m['wav']==row['path']]
     start=by_part[mapped[0]['part']]['start'];count=sum(m['frames'] for m in mapped)
     row.update(start=start,end=start+count,frames=count,timing_basis='exact WAV sample length matched to verified camera parts')
     c['files'].append(dict(path=row['path'],start=start,end=start+count,frames=count,channels=row['channels'],sample_rate=row['sample_rate']))
     ref=Fraction(int(row['tags']['time_reference']),row['sample_rate']) if str(row['tags'].get('time_reference','')).isdigit() else None
     if ref is not None and ref!=timing.seconds(start):
      warnings.append(f'{Path(row["path"]).name}: BWF time_reference differs from verified camera timing and was not used; exact WAV sample length matches video part(s) '+', '.join(str(m['part']) for m in mapped))
    c['timing_basis']='exact WAV sample-length groups; original creation/BWF clocks were not used'
   except ValueError as error:
    c['files']=[];c['mapping_issue']=str(error)
    warnings.append(f'{group["label"]}: cannot verify exact audio-to-video part mapping: {error}')
 for c in candidates.values():
  c['files'].sort(key=lambda x:x['start']);c['selectable']=True;c['issues']=[c['mapping_issue']] if c.get('mapping_issue') else []
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
