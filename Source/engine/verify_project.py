#!/usr/bin/env python3
"""Verify an already-open, exported/reimported conversion inside Resolve."""
import argparse,json
from pathlib import Path
from resolve_project import connect,clips,validate

def verify(manifest):
 plan=json.loads(Path(manifest).read_text());r=connect();p=r.GetProjectManager().GetCurrentProject()
 timelines={p.GetTimelineByIndex(i).GetName():p.GetTimelineByIndex(i) for i in range(1,p.GetTimelineCount()+1)}
 t=timelines[plan['name']+'_Edit'];count=validate(t,plan)
 pool=list(clips(p.GetMediaPool().GetRootFolder()));paths={c.GetClipProperty('File Path') for c in pool}
 expected_paths=[m['path'] for m in plan['media']]+[m['path'] for m in plan.get('audio_inventory',[]) if m['kind']=='audio_iso']
 missing=[x for x in expected_paths if x not in paths]
 if missing:raise RuntimeError(f'Missing source paths in reopened project: {missing}')
 native={c.GetName():c for c in pool if c.GetClipProperty('Type')=='Multicam'}
 for s in plan['sessions']:
  if s['multicam_name'] not in native or int(native[s['multicam_name']].GetClipProperty('Frames'))!=s['end']-s['start']:raise RuntimeError('Missing or wrong-duration native multicam')
 audio=t.GetItemListInTrack('audio',1);coverage=[(a.GetStart(),a.GetEnd()) for a in audio]
 if coverage!=[(s['start'],s['end']) for s in plan['sessions']]:raise RuntimeError(f'Audio coverage differs: {coverage}')
 if plan.get('audio'):
  wanted={x['path'] for x in plan['audio']['files']}
  if any(a.GetMediaPoolItem().GetClipProperty('File Path') not in wanted for a in audio):raise RuntimeError('Wrong primary audio source')
 if t.GetTrackCount('audio')!=1:raise RuntimeError('Unexpected additional audio tracks')
 return dict(resolve=r.GetVersionString(),project=p.GetName(),cuts_verified=count,camera_source_count=len(plan['media']),audio_iso_count=sum(x['kind']=='audio_iso' for x in plan.get('audio_inventory',[])),primary_audio=plan.get('audio',{}).get('selected','program'),all_source_paths_present=True,multicam_names=list(native),audio_coverage=coverage,timelines=list(timelines),note='API checks; independently confirm viewer and angle switching in the UI. Existing media files were verified during preflight.')
if __name__=='__main__':
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--manifest',required=True);ap.add_argument('--report',required=True);a=ap.parse_args()
 try:
  report=verify(a.manifest);Path(a.report).write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
 except Exception as e:ap.exit(2,f'Verification failed: {e}\n')
