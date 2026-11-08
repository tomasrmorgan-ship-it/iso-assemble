#!/usr/bin/env python3
"""ISO Assemble's local application bridge. JSON events are consumed by the native UI."""
import argparse,contextlib,hashlib,json,os,sys,time,traceback,shutil
from pathlib import Path
from atem import preflight,parse
from timing import Timing
from convert import build
from ingest import discover_project,repair_for,audio_catalog,project_candidates

def emit(kind,**fields):
 print(json.dumps(dict(event=kind,**fields)),flush=True)

def snapshot(paths):
 return {str(Path(p).resolve()):[Path(p).stat().st_size,Path(p).stat().st_mtime_ns] for p in sorted(set(paths))}

def mix_status(plan):
 transitions=plan.get('transitions',[])
 return dict(mixPolicy=plan.get('mix_policy','strict'),transitions=len(transitions),
             linearTransitions=sum(not t['unresolved'] for t in transitions),
             unresolvedTransitions=sum(t['unresolved'] for t in transitions),
             requiresReview=bool(transitions),
             transitionStatus='planned-review-required' if transitions else 'no-active-transitions')

def write_mix_review(review,plan,out):
 """Keep successful opt-in planning distinct from faithful transition recovery."""
 status=mix_status(plan)
 review.update(scan_status='linear-mix-plan-requires-review',mix_policy=plan['mix_policy'],
               transition_plan=plan['transitions'],review_markers=plan['review_markers'],
               transition_warnings=plan['transition_warnings'],requires_review=True)
 lines=['ISO Assemble — ATEM Mix review','','Input: '+review['project'],
        'Records: '+str(review['record_count']),
        f'Recorded Mix intervals: {status["transitions"]}',
        f'Linear Cross Dissolves planned for Resolve: {status["linearTransitions"]}',
        f'Unresolved intervals retaining all original source selections: {status["unresolvedTransitions"]}',
        '',*review.get('normalization_notes',[]),'',*plan['transition_warnings'],'',
        'Exact frame ranges, source changes, fader samples, source lines and unresolved marker intervals are in ATEM Review.json.',
        'This is a reviewed conversion plan. Resolve application, export and reimport validation have not happened during this scan.',
        'Original ATEM records and source media are unchanged.']
 (out/'ATEM Review.json').write_text(json.dumps(review,indent=2))
 (out/'ATEM Review.txt').write_text('\n'.join(lines)+'\n')

def conversion_fingerprint(xml,chosen,files,plan):
 payload=xml+json.dumps(chosen,sort_keys=True).encode()+json.dumps(files,sort_keys=True).encode()
 # Preserve existing strict-cut fingerprints; reviewed Mix semantics are new.
 if plan.get('mix_policy','strict')!='strict':
  payload+=json.dumps(dict(mix_policy=plan['mix_policy'],transitions=plan.get('transitions',[])),sort_keys=True).encode()
 return hashlib.sha256(payload).hexdigest()

def scan(root,out,selected=None,mix_policy='strict'):
 if mix_policy not in ('strict','linear-review'):raise ValueError('Choose strict conversion or reviewed linear Mix transitions.')
 root=Path(root).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
 if not selected:
  candidates=project_candidates(root)
  if len(candidates)>1:
   emit('project_choices',paths=[str(p) for p in candidates]);return
 project=discover_project(root,selected);repair=repair_for(root,project)
 emit('progress',message='Reading the ATEM edit and checking every camera file…')
 from diagnostics import event_review,write_review
 events,_=parse(project)
 if not events:raise ValueError('Empty ATEM project')
 review=event_review(events,project,Timing.from_mode(events[0]['state'].get('videoMode'),events[0]['state']['masterTimecode']))
 review_path=write_review(review,out)
 try:data=preflight(project,root,repair)
 except (ValueError,OSError,KeyError,StopIteration) as error:
  review.update(scan_status='blocked',error=str(error));write_review(review,out)
  raise ValueError(f'{error}\nSee {review_path} for event and transition details.') from error
 emit('progress',message='Detected 1080p '+Timing.from_plan(data).resolve_rate+' '+Timing.from_plan(data).display+'; checking synchronization…')
 review['normalization_notes']=data['warnings']
 try:_,plan=build(data,'Preflight',mix_policy=mix_policy)
 except (ValueError,KeyError) as error:
  review.update(scan_status='blocked',error=str(error));write_review(review,out)
  raise ValueError(f'{error}\nSee {review_path} for event and transition details.') from error
 if plan.get('transitions'):write_mix_review(review,plan,out)
 else:review['scan_status']='event-and-video-checks-passed';write_review(review,out)
 plan['media']=data['media'];plan['_events']=data['events']
 emit('progress',message='Discovering program audio and all captured audio ISOs…')
 cat=audio_catalog(root,plan);cat.update(project=str(project),reference_repair=repair)
 paths=[str(project)]+[x['path'] for x in cat['inventory']]
 package=dict(root=str(root),data=data,catalog=cat,snapshot=snapshot(paths),mix_policy=mix_policy)
 (out/'scan.json').write_text(json.dumps(package))
 (out/'audio-catalog.json').write_text(json.dumps(cat,indent=2))
 emit('scanned',frameRate=Timing.from_plan(data).resolve_rate+' '+Timing.from_plan(data).display,root=str(root),output=str(out),cameras=len(plan['camera_names']),clips=len(data['media']),audioISOs=sum(x['kind']=='audio_iso' for x in cat['inventory']),sessions=len(plan['sessions']),cuts=sum(c['angle'] not in (0,None) for c in plan['cuts']),choices=[dict(id=c['id'],label=c['label']) for c in cat['candidates'] if c['selectable']],warnings=data['warnings']+cat['warnings']+plan.get('transition_warnings',[]),**mix_status(plan))

def create(out,name,primary):
 from resolve_project import connect,apply
 from resolve_compatibility import check_version,ensure_compatible
 from verify_project import verify
 from project_layout import select_edit_session
 from export_validation import load_export_for_verification
 from fresh_run import allocate_fresh_run,cleanup_test_projects
 out=Path(out).resolve();package=json.loads((out/'scan.json').read_text());data=package['data'];cat=package['catalog']
 if snapshot(package['snapshot'])!=package['snapshot']:raise ValueError('The recording files changed after scanning. Choose the folder again to rescan before creating the project.')
 if not name.strip() or '/' in name or '\\' in name or name in ('.','..'):raise ValueError('Enter a project name without path separators.')
 chosen=next((c for c in cat['candidates'] if c['id']==primary and c['selectable']),None)
 if not chosen:raise ValueError('Select a primary audio source before creating the project.')
 mix_policy=package.get('mix_policy','strict')
 if mix_policy not in ('strict','linear-review'):raise ValueError('The saved Mix setting is invalid. Scan the folder again.')
 emit('progress',message='Connecting to DaVinci Resolve…')
 r=None
 for attempt in range(30):
  try:r=connect();break
  except RuntimeError:
   if attempt==29:raise RuntimeError('Could not connect to Resolve. Finish opening Resolve and select a local project library. Resolve Studio must allow local scripting in Preferences → System → General → External scripting using Local. Then retry Create Project.')
   time.sleep(2)
 version=r.GetVersionString()
 check_version(version,needs_mix=mix_policy=='linear-review')
 scan_output=out;requested_name=name
 pm=r.GetProjectManager()
 out,name=allocate_fresh_run(scan_output,requested_name,pm.GetProjectListInCurrentFolder())
 for filename in ('scan.json','audio-catalog.json','ATEM Review.json','ATEM Review.txt'):
  source=scan_output/filename
  if source.is_file() and not source.is_symlink():shutil.copy2(source,out/filename)
 emit('progress',message=f'Creating a fresh project: {name}. Previous conversions will not be reused.')
 xml,plan=build(data,name,mix_policy=mix_policy);fingerprint=conversion_fingerprint(xml,chosen,package['snapshot'],plan)
 plan.update(name=name,input=data['input'],input_sha256=data['sha256'],media_root=package['root'],fingerprint=fingerprint,media=[{k:v for k,v in m.items() if k!='probe'} for m in data['media']],warnings=data['warnings']+cat['warnings']+plan.get('transition_warnings',[]),audio=dict(selected=chosen['id'],label=chosen['label'],files=chosen['files']),audio_inventory=cat['inventory'])
 manifest=out/'conversion.json'
 if manifest.exists() and json.loads(manifest.read_text())['fingerprint']!=fingerprint:raise ValueError('This output folder already contains a different conversion or audio selection. Choose another output folder to preserve it.')
 pm=r.GetProjectManager();existing=pm.GetProjectListInCurrentFolder()
 if name in existing and not (out/'resolve-state.json').exists():raise ValueError(f'A Resolve project named {name} already exists. Choose a different project name; it has not been changed.')
 compatibility=ensure_compatible(r,data,out,needs_mix=mix_policy=='linear-review',progress=lambda message:emit('progress',message=message))
 plan['requested_name']=requested_name
 plan['resolve_compatibility']=compatibility
 manifest.write_text(json.dumps(plan,indent=2));(out/(name+'.fcpxml')).write_bytes(xml)
 emit('progress',message='Creating native multicam clips, reconstructing live cuts, and importing all audio ISOs…')
 with contextlib.redirect_stdout(sys.stderr):apply(manifest)
 emit('progress',message='Reopening the exported project and verifying native multicam cuts, media and audio…')
 plan=json.loads(manifest.read_text())
 target=out/(name+'.drp')
 p,export_check=load_export_for_verification(pm,target,out/'export-check-state.json',fingerprint)
 report=verify(manifest);report['export']=str(target);report['export_sha256']=export_check['export_sha256'];report['export_import']=export_check;report['verification']='Automatic Resolve API checks after native export and reimport, including active edit timeline and organized media bins. Viewer controls are checked separately by the app.'
 report.update(mix_policy=mix_policy,transition_warnings=plan.get('transition_warnings',[]),review_markers=plan.get('review_markers',[]),requires_review=bool(plan.get('transitions')))
 (out/'validation.json').write_text(json.dumps(report,indent=2))
 proof_state=json.loads((out/'Resolve Compatibility'/'state.json').read_text())
 owned_tests={**proof_state['project_ids'],export_check['name']:export_check['project_id']}
 emit('progress',message='Verification passed. Removing this run’s temporary test projects and opening the finished edit…')
 report['temporary_project_cleanup']=cleanup_test_projects(pm,owned_tests,name)
 for warning in report['temporary_project_cleanup']['warnings']:emit('progress',message=warning)
 p=pm.LoadProject(name)
 if not p:raise RuntimeError('Could not return to the completed editing project')
 report['final_edit_session']=select_edit_session(r,p,plan)
 if not pm.SaveProject():raise RuntimeError('Resolve could not save the selected edit session')
 (out/'validation.json').write_text(json.dumps(report,indent=2))
 message='Project exported and reopened on the finished cut timeline. Media is organized into bins.'
 status=mix_status(plan)
 if plan.get('transitions'):
  status['transitionStatus']='applied-review-required'
  message=(f'Project created, exported and reopened. {status["linearTransitions"]} linear Mix transitions were reconstructed; '
           f'{status["unresolvedTransitions"]} marked intervals and the original fader curves still need comparison with the program reference.')
 emit('complete',export=str(target),output=str(out),project=name,prepareViewer=True,timeline=name+'_Edit',cuts=report['cuts_verified'],audio=chosen['label'],message=message,**status)

def premiere_create(out,name,primary):
 from premiere import generate
 from verify_premiere import verify as verify_native
 out=Path(out).resolve();package=json.loads((out/'scan.json').read_text())
 if snapshot(package['snapshot'])!=package['snapshot']:raise ValueError('Media changed after scanning. Scan again.')
 if not name.strip() or '/' in name or '\\' in name or name in ('.','..'):raise ValueError('Enter a project name without path separators.')
 if any(m.get('transitionActive') for ev in package['data'].get('events',[]) for m in ev['state'].get('mixEffectBlocks',[])):
  raise ValueError('Premiere export cannot reconstruct the ATEM Mix transitions in this recording. Use the reviewed Resolve conversion. No transitions were approximated or discarded and no Premiere file was created.')
 emit('progress',message='Building native Premiere multicam interchange and independent stereo audio…')
 xml,report=generate(package,name,primary)
 fingerprint=hashlib.sha256(xml+json.dumps(package['snapshot'],sort_keys=True).encode()).hexdigest()
 mf=out/'premiere-manifest.json';target=out/(name+'.prproj');interchange=out/(name+'.xml')
 if mf.exists() and json.loads(mf.read_text()).get('fingerprint')!=fingerprint:raise ValueError('This folder contains a different Premiere conversion. Choose a new output folder.')
 if target.exists() and not mf.exists():raise ValueError('An unowned Premiere project already exists here. Choose a new output folder.')
 report['fingerprint']=fingerprint;mf.write_text(json.dumps(report,indent=2));interchange.write_bytes(xml)
 if target.exists():
  premiere_verify(out,name);return
 emit('premiere_ready',xml=str(interchange),project=str(target),name=name,splices=len(report['technical_splices']),message='Opening Premiere. Use File → Save As to save the named project in the selected results folder. ISO Assemble will verify it automatically.')

def premiere_verify(out,name):
 from verify_premiere import verify as verify_native
 out=Path(out).resolve();target=out/(name+'.prproj')
 report=verify_native(target,out/'premiere-manifest.json')
 (out/'premiere-validation.json').write_text(json.dumps(report,indent=2))
 emit('complete',export=str(target),audio=report['audio_source'],message=f"Premiere project saved and verified: {report['native_multicam_cuts_verified']} editable multicam clips. Reopen/angle-switch UI checks are not automated.")

def audio_scan(root,out):
 from attach_audio import discover
 emit('progress',message='Finding camera files and available audio ISOs…')
 catalog=discover(root)
 emit('audio_scanned',output=str(Path(out).resolve()),root=catalog['root'],
      cameras=catalog['cameras'],clips=catalog['clips'],audioISOs=catalog['audioISOs'],choices=catalog['choices'])
 for warning in catalog.get('warnings',[]):emit('progress',message=warning)

def audio_plan(root,out,source):
 from attach_audio import make_plan
 plan=make_plan(root,source,out,progress=lambda message:emit('progress',message=message))
 details='\n'.join(f"Part {row['part']}: {Path(row['wav']).name}, samples [{row['start_sample']}, {row['end_sample']})" for row in plan['mapping'])
 size=plan['estimated_output_bytes']/1_000_000_000
 emit('audio_plan',output=plan['output'],report=plan['report'],source=plan['source'],
      summary=f"{len(plan['outputs'])} camera files · {source} audio · about {size:.2f} GB of new media",
      details=details+'\nDry-run report: '+plan['report']+'\nThis check did not create or change MOV files.')

def audio_build(out):
 from attach_audio import build
 report=build(out,progress=lambda message:emit('progress',message=message))
 emit('complete',export=report['output'],audio='Chosen WAV source; see verification report',
      message=f"{report['verified_count']} camera files verified. Import the new MOVs into your editor. The original ATEM project still uses its original media.")

def main():
 ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='command',required=True)
 s=sub.add_parser('scan');s.add_argument('--root',required=True);s.add_argument('--output',required=True);s.add_argument('--project');s.add_argument('--mix-policy',choices=('strict','linear-review'),default='strict')
 c=sub.add_parser('create');c.add_argument('--output',required=True);c.add_argument('--name',required=True);c.add_argument('--audio',required=True)
 p=sub.add_parser('premiere');p.add_argument('--output',required=True);p.add_argument('--name',required=True);p.add_argument('--audio',required=True)
 v=sub.add_parser('verify-premiere');v.add_argument('--output',required=True);v.add_argument('--name',required=True)
 s=sub.add_parser('audio-scan');s.add_argument('--root',required=True);s.add_argument('--output',required=True)
 p=sub.add_parser('audio-plan');p.add_argument('--root',required=True);p.add_argument('--output',required=True);p.add_argument('--audio',required=True)
 b=sub.add_parser('audio-build');b.add_argument('--output',required=True)
 a=ap.parse_args()
 try:
  if a.command=='scan':scan(a.root,a.output,a.project,mix_policy=a.mix_policy)
  elif a.command=='audio-scan':audio_scan(a.root,a.output)
  elif a.command=='audio-plan':audio_plan(a.root,a.output,a.audio)
  elif a.command=='audio-build':audio_build(a.output)
  elif a.command=='premiere':premiere_create(a.output,a.name,a.audio)
  elif a.command=='verify-premiere':premiere_verify(a.output,a.name)
  else:create(a.output,a.name,a.audio)
 except (ValueError,OSError) as e:
  emit('error',message=str(e));sys.exit(1)
 except Exception as e:
  traceback.print_exc(file=sys.stderr);emit('error',message=str(e));sys.exit(1)
if __name__=='__main__':main()
