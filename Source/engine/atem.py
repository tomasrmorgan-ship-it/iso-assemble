"""Local ATEM NDJSON preflight. All edit positions are integer 29.97 DF frames."""
import argparse, copy, hashlib, json, re, subprocess, sys
from pathlib import Path
from fractions import Fraction

DAY = 2589408

def frames(tc):
    m = re.fullmatch(r'(\d{2}):(\d{2}):(\d{2})([:;])(\d{2})', tc)
    if not m: raise ValueError(f'Invalid timecode: {tc}')
    h, mi, s, f = map(int, (m[1],m[2],m[3],m[5]))
    if h>23 or mi>59 or s>59 or f>29: raise ValueError(f'Invalid timecode: {tc}')
    if m[4]==';' and mi%10 and s==0 and f<2: raise ValueError(f'Nonexistent drop-frame label: {tc}')
    return ((h*60+mi)*60+s)*30+f-(2*(h*60+mi-(h*60+mi)//10) if m[4]==';' else 0)

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
    state={}; events=[]; sources={}; last=None; day=0; session=-1; recording=None
    for line,text in enumerate(Path(path).read_text().splitlines(),1):
        if not text.strip(): continue
        try: r=json.loads(text)
        except Exception as e: raise ValueError(f'Invalid JSON at line {line}: {e}')
        if not isinstance(r,dict) or 'masterTimecode' not in r: raise ValueError(f'Missing timecode at line {line}')
        if r.get('videoMode', '1080p29.97')!='1080p29.97': raise ValueError('Only verified 1080p29.97 mode is supported')
        f=frames(r['masterTimecode'])+day
        if last is not None and f<last:
            if last-f>DAY//2: day+=DAY;f+=DAY
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
    for n,(file,s) in enumerate(sources.items(),1):
        rel=file.replace(*repair) if repair else file
        p=(Path(root)/rel).resolve()
        if not p.is_relative_to(Path(root).resolve()): raise ValueError(f'Media escapes root: {file}')
        if not p.is_file(): raise ValueError(f'Missing media: {p}')
        print(f'[{n}/{len(sources)}] Probe {p.name}',file=sys.stderr)
        d=probe(p);v=next(x for x in d['streams'] if x['codec_type']=='video')
        if Fraction(v['avg_frame_rate'])!=Fraction(30000,1001): raise ValueError(f'Unsupported frame rate: {p}')
        if (v['width'],v['height'])!=(1920,1080): raise ValueError(f'Unexpected raster: {p}')
        tc=v.get('tags',{}).get('timecode')
        if not tc or ';' not in tc: raise ValueError(f'Missing verified drop-frame media timecode: {p}')
        start=frames(tc);duration=int(v['nb_frames'])
        if Fraction(v['duration_ts'])*Fraction(v['time_base'])*Fraction(30000,1001)!=duration: raise ValueError(f'Noninteger duration: {p}')
        delta=start-frames(s['startTimecode'])
        if delta:warnings.append(f'{p.name}: media minus ATEM source start = {delta} frame(s); use media timing, retain event timing')
        media.append(dict(path=str(p),camera=s['_index_'],name=s['name'],start=start,end=start+duration,frames=duration,timecode=tc,atem_timecode=s['startTimecode'],probe=d))
    boundaries=[]
    for camera in sorted({x['camera'] for x in media}):
        clips=sorted((x for x in media if x['camera']==camera),key=lambda x:x['start'])
        for a,b in zip(clips,clips[1:]): boundaries.append(dict(camera=camera,previous=a['path'],next=b['path'],gap_frames=b['start']-a['end']))
    return dict(input=str(Path(project).resolve()),sha256=hashlib.sha256(Path(project).read_bytes()).hexdigest(),record_count=len(events),media=media,events=events,boundaries=boundaries,warnings=warnings)

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
