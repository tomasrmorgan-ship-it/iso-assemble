#!/usr/bin/env python3
"""ISO Assemble's local application bridge. JSON events are consumed by the native UI."""
import argparse,contextlib,hashlib,json,os,sys,time,traceback
from pathlib import Path
from atem import preflight
from timing import Timing
from convert import build
from ingest import discover_project,repair_for,audio_catalog,project_candidates

def emit(kind,**fields):
 print(json.dumps(dict(event=kind,**fields)),flush=True)

def snapshot(paths):
 return {str(Path(p).resolve()):[Path(p).stat().st_size,Path(p).stat().st_mtime_ns] for p in sorted(set(paths))}

def scan(root,out,selected=None):
 root=Path(root).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
 if not selected:
  candidates=project_candidates(root)
  if len(candidates)>1:
   emit('project_choices',paths=[str(p) for p in candidates]);return
 project=discover_project(root,selected);repair=repair_for(root,project)
 emit('progress',message='Reading the ATEM edit and checking every camera file…')
 data=preflight(project,root,repair)
 emit('progress',message='Detected 1080p '+Timing.from_plan(data).resolve_rate+' '+Timing.from_plan(data).display+'; checking synchronization…')
 _,plan=build(data,'Preflight');plan['media']=data['media'];plan['_events']=data['events']
 emit('progress',message='Discovering program audio and all captured audio ISOs…')
 cat=audio_catalog(root,plan);cat.update(project=str(project),reference_repair=repair)
 paths=[str(project)]+[x['path'] for x in cat['inventory']]
 package=dict(root=str(root),data=data,catalog=cat,snapshot=snapshot(paths))
 (out/'scan.json').write_text(json.dumps(package))
 (out/'audio-catalog.json').write_text(json.dumps(cat,indent=2))
 emit('scanned',frameRate=Timing.from_plan(data).resolve_rate+' '+Timing.from_plan(data).display,root=str(root),output=str(out),cameras=len(plan['camera_names']),clips=len(data['media']),audioISOs=sum(x['kind']=='audio_iso' for x in cat['inventory']),sessions=len(plan['sessions']),cuts=sum(c['angle'] not in (0,None) for c in plan['cuts']),choices=[dict(id=c['id'],label=c['label']) for c in cat['candidates'] if c['selectable']],warnings=data['warnings']+cat['warnings'])

def create(out,name,primary):
 from resolve_project import connect,apply
 from verify_project import verify
 out=Path(out).resolve();package=json.loads((out/'scan.json').read_text());data=package['data'];cat=package['catalog']
 if snapshot(package['snapshot'])!=package['snapshot']:raise ValueError('The recording files changed after scanning. Choose the folder again to rescan before creating the project.')
 if not name.strip() or '/' in name or '\\' in name or name in ('.','..'):raise ValueError('Enter a project name without path separators.')
 chosen=next((c for c in cat['candidates'] if c['id']==primary and c['selectable']),None)
 if not chosen:raise ValueError('Select a primary audio source before creating the project.')
 emit('progress',message='Connecting to DaVinci Resolve…')
 r=None
 for attempt in range(30):
  try:r=connect();break
  except RuntimeError:
   if attempt==29:raise RuntimeError('Could not connect to Resolve. Finish opening Resolve and select a local project library. Resolve Studio must allow local scripting in Preferences → System → General → External scripting using Local. Then retry Create Project.')
   time.sleep(2)
 if r.GetVersionString()!='21.0.0.48':raise RuntimeError(f'This build is validated on Resolve Studio 21.0.0.48; found {r.GetVersionString()}. No project was changed.')
 xml,plan=build(data,name);fingerprint=hashlib.sha256(xml+json.dumps(chosen,sort_keys=True).encode()+json.dumps(package['snapshot'],sort_keys=True).encode()).hexdigest()
 plan.update(name=name,input=data['input'],input_sha256=data['sha256'],media_root=package['root'],fingerprint=fingerprint,media=[{k:v for k,v in m.items() if k!='probe'} for m in data['media']],warnings=data['warnings']+cat['warnings'],audio=dict(selected=chosen['id'],label=chosen['label'],files=chosen['files']),audio_inventory=cat['inventory'])
 manifest=out/'conversion.json'
 if manifest.exists() and json.loads(manifest.read_text())['fingerprint']!=fingerprint:raise ValueError('This output folder already contains a different conversion or audio selection. Choose another output folder to preserve it.')
 pm=r.GetProjectManager();existing=pm.GetProjectListInCurrentFolder()
 if name in existing and not (out/'resolve-state.json').exists():raise ValueError(f'A Resolve project named {name} already exists. Choose a different project name; it has not been changed.')
 manifest.write_text(json.dumps(plan,indent=2));(out/(name+'.fcpxml')).write_bytes(xml)
 if pm.GetCurrentProject() and not pm.SaveProject():raise RuntimeError('Could not save the current Resolve project. Save it in Resolve, then retry.')
 emit('progress',message='Creating native multicam clips, reconstructing live cuts, and importing all audio ISOs…')
 with contextlib.redirect_stdout(sys.stderr):apply(manifest)
 emit('progress',message='Reopening the exported project and verifying native multicam cuts, media and audio…')
 target=out/(name+'.drp');checkfile=out/'export-check-state.json';check=json.loads(checkfile.read_text()) if checkfile.exists() else {}
 checkname='ISOAssemble_Verify_'+fingerprint[:12]
 if checkname in pm.GetProjectListInCurrentFolder():
  if check.get('name')!=checkname:raise RuntimeError('Verification project name collision. Existing project preserved.')
 else:
  if not pm.ImportProject(str(target),checkname):raise RuntimeError('Resolve could not reimport the exported project.')
  check=dict(name=checkname);checkfile.write_text(json.dumps(check))
 p=pm.LoadProject(checkname)
 if not p:raise RuntimeError('Could not open the export verification project.')
 if check.get('project_id') and p.GetUniqueId()!=check['project_id']:raise RuntimeError('Verification project identity changed; existing project preserved.')
 check['project_id']=p.GetUniqueId();checkfile.write_text(json.dumps(check))
 report=verify(manifest);report['export']=str(target);report['export_sha256']=hashlib.sha256(target.read_bytes()).hexdigest();report['verification']='Automatic Resolve API checks after native export and reimport. No UI angle-switch check performed by this run.'
 (out/'validation.json').write_text(json.dumps(report,indent=2))
 p=pm.LoadProject(name);t=next(p.GetTimelineByIndex(i) for i in range(1,p.GetTimelineCount()+1) if p.GetTimelineByIndex(i).GetName()==name+'_Edit');p.SetCurrentTimeline(t);r.OpenPage('edit');pm.SaveProject()
 emit('complete',export=str(target),project=name,cuts=report['cuts_verified'],audio=chosen['label'],message='Project created, exported and reopened successfully. Ready to edit in Resolve.')

def premiere_create(out,name,primary):
 from premiere import generate
 from verify_premiere import verify as verify_native
 out=Path(out).resolve();package=json.loads((out/'scan.json').read_text())
 if snapshot(package['snapshot'])!=package['snapshot']:raise ValueError('Media changed after scanning. Scan again.')
 if not name.strip() or '/' in name or '\\' in name or name in ('.','..'):raise ValueError('Enter a project name without path separators.')
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

def main():
 ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='command',required=True)
 s=sub.add_parser('scan');s.add_argument('--root',required=True);s.add_argument('--output',required=True);s.add_argument('--project')
 c=sub.add_parser('create');c.add_argument('--output',required=True);c.add_argument('--name',required=True);c.add_argument('--audio',required=True)
 p=sub.add_parser('premiere');p.add_argument('--output',required=True);p.add_argument('--name',required=True);p.add_argument('--audio',required=True)
 v=sub.add_parser('verify-premiere');v.add_argument('--output',required=True);v.add_argument('--name',required=True)
 a=ap.parse_args()
 try:
  if a.command=='scan':scan(a.root,a.output,a.project)
  elif a.command=='premiere':premiere_create(a.output,a.name,a.audio)
  elif a.command=='verify-premiere':premiere_verify(a.output,a.name)
  else:create(a.output,a.name,a.audio)
 except Exception as e:
  traceback.print_exc(file=sys.stderr);emit('error',message=str(e));sys.exit(1)
if __name__=='__main__':main()
