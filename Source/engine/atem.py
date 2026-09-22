"""Local ATEM NDJSON preflight. All edit positions are integer frames at the verified project rate."""
import argparse, copy, hashlib, json, re, subprocess, sys
from pathlib import Path
from fractions import Fraction

from timing import Timing
DAY = Timing().day

def frames(tc,rate='30000/1001'):
    return Timing(rate,';' in tc).frames(tc)

def merge(old, update):
    if isinstance(update, dict):
        result=copy.deepcopy(old) if isinstance(old,dict) else {}
        for k,v in update.items(): result[k]=merge(result.get(k),v)
        return result
    if isinstance(update,list) and all(isinstance(v,dict) and '_index_' in v for v in update):
        result={v['_index_']:copy.deepcopy(v) for v in (old or [])}
        for v in update: result[v['_index_']]=merge(result.get(v['_index_']),v)
        return [result[k] for k in sorted(result)]
    return copy.deepcopy(update)

def parse(path):
    state={}; events=[]; sources={}; last=None; day=0; session=-1; recording=None; timing=None
    for line,text in enumerate(Path(path).read_text().splitlines(),1):
        if not text.strip(): continue
        try: r=json.loads(text)
        except Exception as e: raise ValueError(f'Invalid JSON at line {line}: {e}')
        if not isinstance(r,dict) or 'masterTimecode' not in r: raise ValueError(f'Missing timecode at line {line}')
        if timing is None: timing=Timing.from_mode(r.get('videoMode'),r['masterTimecode'])
        if 'videoMode' in r and Timing.from_mode(r['videoMode'],r['masterTimecode']).data()!=timing.data(): raise ValueError('Project frame rate or timecode mode changed mid-recording')
        f=timing.frames(r['masterTimecode'])+day
        if last is not None and f<last:
            if last-f>timing.day//2: day+=timing.day;f+=timing.day
            else: raise ValueError(f'Nonmonotonic event at line {line}')
        if 'recordingId'in r and r['recordingId']!=recording:
            session+=1;recording=r['recordingId'];state={}
        state=merge(state,r)
        for s in state.get('sources',[]):
            if s.get('file'): sources[s['file']]=copy.deepcopy(s)
        events.append(dict(line=line,frame=f,session=session,state=copy.deepcopy(state),update=r))
        last=f
    return events,sources

def probe(path):
    p=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True)
    if p.returncode: raise ValueError(f'ffprobe failed for {path}: {p.stderr.strip()}')
    return json.loads(p.stdout)

def preflight(project,root,repair=None):
    events,sources=parse(project);media=[];warnings=[]
    if not events: raise ValueError('Empty ATEM project')
    timing=Timing.from_mode(events[0]['state'].get('videoMode'),events[0]['state']['masterTimecode'])
    for n,(file,s) in enumerate(sources.items(),1):
        rel=file.replace(*repair) if repair else file
        p=(Path(root)/rel).resolve()
        if not p.is_relative_to(Path(root).resolve()): raise ValueError(f'Media escapes root: {file}')
        if not p.is_file(): raise ValueError(f'Missing media: {p}')
        print(f'[{n}/{len(sources)}] Probe {p.name}',file=sys.stderr)
        d=probe(p);v=next(x for x in d['streams'] if x['codec_type']=='video')
        if Fraction(v['avg_frame_rate'])!=timing.fps: raise ValueError(f'Unsupported frame rate: {p}')
        if (v['width'],v['height'])!=(1920,1080): raise ValueError(f'Unexpected raster: {p}')
        tc=v.get('tags',{}).get('timecode')
        if not tc: raise ValueError(f'Missing media timecode: {p}')
        start=timing.frames(tc);duration=int(v['nb_frames'])
        if Fraction(v['duration_ts'])*Fraction(v['time_base'])*timing.fps!=duration: raise ValueError(f'Noninteger duration: {p}')
        delta=start-timing.frames(s['startTimecode'])
        if delta:warnings.append(f'{p.name}: media minus ATEM source start = {delta} frame(s); use media timing, retain event timing')
        media.append(dict(path=str(p),camera=s['_index_'],name=s['name'],start=start,end=start+duration,frames=duration,timecode=tc,atem_timecode=s['startTimecode'],probe=d))
    boundaries=[]
    for camera in sorted({x['camera'] for x in media}):
        clips=sorted((x for x in media if x['camera']==camera),key=lambda x:x['start'])
        for a,b in zip(clips,clips[1:]): boundaries.append(dict(camera=camera,previous=a['path'],next=b['path'],gap_frames=b['start']-a['end']))
    return dict(timing=timing.data(),input=str(Path(project).resolve()),sha256=hashlib.sha256(Path(project).read_bytes()).hexdigest(),record_count=len(events),media=media,events=events,boundaries=boundaries,warnings=warnings)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True);p.add_argument('--media-root',required=True);p.add_argument('--output',required=True);p.add_argument('--repair-prefix',nargs=2);p.add_argument('--dry-run',action='store_true',help='Read-only preflight; only writes the report')
    a=p.parse_args()
    try:
        result=preflight(a.input,a.media_root,a.repair_prefix)
        out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
        if out.exists():
            if json.loads(out.read_text()).get('sha256')!=result['sha256']:raise ValueError('Report belongs to another input; choose a new output')
        out.write_text(json.dumps(result,indent=2));print(f'Preflight complete: {len(result["media"])} sources, {len(result["warnings"])} timing warnings. {out}')
    except (ValueError,OSError,KeyError,StopIteration) as e: p.exit(2,f'Preflight failed: {e}\n')
if __name__=='__main__':main()
