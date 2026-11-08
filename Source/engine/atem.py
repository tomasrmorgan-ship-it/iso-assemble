"""Local ATEM NDJSON preflight. All edit positions are integer frames at the verified project rate."""
import argparse, copy, hashlib, json, re, subprocess, sys
from pathlib import Path
from fractions import Fraction
from bisect import bisect_right

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

def _source_file_metadata(record):
    """Only the ATEM's delayed file-rollover descriptor is safe to reposition.

    Color/source configuration, switcher controls and recording headers are
    deliberately excluded. File descriptors must declare the same effective
    timecode as their containing record; still-player descriptors may lack a file.
    """
    if set(record)!={'masterTimecode','sources'}: return False
    values=record['sources']
    if not isinstance(values,list) or not values: return False
    allowed={'_index_','file','startTimecode','volume','projectPath'}
    indices=set(); files=0
    for value in values:
        if not isinstance(value,dict) or set(value)-allowed: return False
        index=value.get('_index_')
        if type(index) is not int or index in indices: return False
        indices.add(index)
        if 'file' in value:
            if not isinstance(value['file'],str) or not value['file'] or value.get('startTimecode')!=record['masterTimecode']: return False
            files+=1
    return files>0

def parse(path):
    records=[]; last=None; last_line=None; day=0; session=-1; recording=None; timing=None
    session_start=None; session_index=0
    for line,text in enumerate(Path(path).read_text().splitlines(),1):
        if not text.strip(): continue
        try: r=json.loads(text)
        except Exception as e: raise ValueError(f'Invalid JSON at line {line}: {e}')
        if not isinstance(r,dict) or 'masterTimecode' not in r: raise ValueError(f'Missing timecode at line {line}')
        if timing is None: timing=Timing.from_mode(r.get('videoMode'),r['masterTimecode'])
        if 'videoMode' in r and Timing.from_mode(r['videoMode'],r['masterTimecode']).data()!=timing.data(): raise ValueError('Project frame rate or timecode mode changed mid-recording')
        f=timing.frames(r['masterTimecode'])+day
        metadata=_source_file_metadata(r); previous_day=False
        # A descriptor delivered just after midnight can refer to a rollover
        # just before midnight. Keep the control-event day cursor unchanged.
        if metadata and day and last is not None and f-last>timing.day//2 and session_start is not None and f-timing.day>=session_start:
            f-=timing.day;previous_day=True
        normalization=None
        if last is not None and f<last:
            if last-f>timing.day//2 and not previous_day: day+=timing.day;f+=timing.day
            elif metadata and session>=0 and session_start is not None and f>=session_start:
                warning=(f'Line {line}: late source-file metadata logged after line {last_line} was restored to its declared effective timecode '
                         f'{r["masterTimecode"]} ({last-f} frame(s) earlier), within recording session {session+1}; switcher control order was preserved')
                normalization=dict(kind='late_source_file_metadata',line=line,logged_after_line=last_line,
                                   frame=f,timecode=r['masterTimecode'],delay_frames=last-f,warning=warning)
            else: raise ValueError(f'Nonmonotonic event at line {line}')
        if 'recordingId'in r and r['recordingId']!=recording:
            session+=1;recording=r['recordingId'];session_start=f;session_index=len(records)
        event=dict(line=line,frame=f,session=session,update=r)
        if normalization:
            event['normalization']=normalization
            # Stable insertion moves this descriptor only. Same-frame control
            # records retain their original file order, including partial updates.
            index=session_index+bisect_right([e['frame'] for e in records[session_index:]],f)
            records.insert(index,event)
        else:
            records.append(event);last=f;last_line=line
    # Merge state only after restoring late descriptors. Sorting already-merged
    # snapshots would leak later M/E states backward into earlier partial events.
    state={}; events=[]; sources={}; previous_session=None
    for event in records:
        if event['session']!=previous_session: state={};previous_session=event['session']
        state=merge(state,event['update'])
        for s in state.get('sources',[]):
            if s.get('file'): sources[s['file']]=copy.deepcopy(s)
        events.append({**event,'state':copy.deepcopy(state)})
    return events,sources

def probe(path):
    p=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True)
    if p.returncode: raise ValueError(f'ffprobe failed for {path}: {p.stderr.strip()}')
    return json.loads(p.stdout)

def preflight(project,root,repair=None):
    events,sources=parse(project);media=[];warnings=[e['normalization']['warning'] for e in events if 'normalization' in e]
    if not events: raise ValueError('Empty ATEM project')
    timing=Timing.from_mode(events[0]['state'].get('videoMode'),events[0]['state']['masterTimecode'])
    reference_mapping={};relinked=[];part_groups={};resolved_targets=set()
    if isinstance(repair,dict) and set(repair)-set(sources):raise ValueError('Media relink mapping contains unknown ATEM references')
    for n,(file,s) in enumerate(sources.items(),1):
        rel=repair.get(file,file) if isinstance(repair,dict) else file.replace(*repair) if repair else file
        if not isinstance(rel,str):raise ValueError(f'Invalid media relink target for {file}')
        p=(Path(root)/rel).resolve()
        if not p.is_relative_to(Path(root).resolve()): raise ValueError(f'Media escapes root: {file}')
        if not p.is_file(): raise ValueError(f'Missing media: {p}')
        if p in resolved_targets:raise ValueError(f'Multiple ATEM references resolve to one media file: {p}')
        resolved_targets.add(p);reference_mapping[file]=rel
        is_mov_relink=rel!=file and Path(file).suffix.lower()=='.mp4' and p.suffix.lower()=='.mov'
        if isinstance(repair,dict) and rel!=file:
            original=(Path(root)/file).resolve()
            if original.is_relative_to(Path(root).resolve()) and original.is_file():raise ValueError(f'Original media is present and must be preferred over relinking: {file}')
        original_match=re.fullmatch(r'(.+) CAM (\d+) (\d+)\.mp4',Path(file).name,re.I)
        if is_mov_relink:
            replacement_match=re.fullmatch(r'(.+) CAM (\d+) (\d+)\.mov',p.name,re.I)
            if not original_match or not replacement_match or (int(original_match[2]),int(original_match[3]))!=(int(replacement_match[2]),int(replacement_match[3])) or int(original_match[2])!=s['_index_']:
                raise ValueError(f'MOV replacement camera/part identity does not match its ATEM reference: {file} -> {rel}')
        print(f'[{n}/{len(sources)}] Probe {p.name}',file=sys.stderr)
        d=probe(p);v=next(x for x in d['streams'] if x['codec_type']=='video')
        average=Fraction(v['avg_frame_rate'])
        if average!=timing.fps:
            try: declared=Fraction(v.get('r_frame_rate','0'))
            except (ValueError,TypeError,ZeroDivisionError): declared=None
            if declared==timing.fps:
                raise ValueError(f'{p.name}: declared nominal frame rate is {timing.fps} fps, but average frame rate is '
                                 f'{float(average):.6f} fps ({v["avg_frame_rate"]}). Gapped timestamps or variable-rate media require review; no retiming was performed')
            raise ValueError(f'Unsupported frame rate: {p} (expected {timing.fps} fps; average {v["avg_frame_rate"]})')
        if (v['width'],v['height'])!=(1920,1080): raise ValueError(f'Unexpected raster: {p}')
        tc=v.get('tags',{}).get('timecode')
        if not tc: raise ValueError(f'Missing media timecode: {p}')
        start=timing.frames(tc);duration=int(v['nb_frames'])
        if duration<=0:raise ValueError(f'Invalid video frame count: {p}')
        if Fraction(v['duration_ts'])*Fraction(v['time_base'])*timing.fps!=duration: raise ValueError(f'Noninteger duration: {p}')
        delta=start-timing.frames(s['startTimecode'])
        if is_mov_relink:
            if 'r_frame_rate' in v and Fraction(v['r_frame_rate'])!=timing.fps:raise ValueError(f'MOV replacement declared frame rate differs from the project: {p}')
            if 'start_pts' in v and int(v['start_pts'])!=0:raise ValueError(f'MOV replacement has a nonzero video start timestamp: {p}; no offset was assumed')
            relinked.append(dict(original=file,replacement=rel,camera=s['_index_'],frames=duration,timecode=tc,source_start_delta_frames=delta))
        if delta and not is_mov_relink:warnings.append(f'{p.name}: media minus ATEM source start = {delta} frame(s); use media timing, retain event timing')
        item=dict(path=str(p),camera=s['_index_'],name=s['name'],start=start,end=start+duration,frames=duration,timecode=tc,atem_timecode=s['startTimecode'],probe=d)
        media.append(item)
        if original_match:part_groups.setdefault((original_match[1],int(original_match[3])),[]).append(item)
    if relinked:
        for group in part_groups.values():
            if len({(m['frames'],m['timecode']) for m in group})!=1:
                raise ValueError('Camera part frame count/timecode mismatch while verifying MOV relinks: '+', '.join(Path(m['path']).name for m in group))
        confirmed={};camera_set={m['camera'] for m in media}
        for link in relinked:
            delta=link['source_start_delta_frames']
            if delta:
                original_match=re.fullmatch(r'(.+) CAM (\d+) (\d+)\.mp4',Path(link['original']).name,re.I)
                item=next(m for m in media if m['path']==str((Path(root)/link['replacement']).resolve()))
                key=(original_match[1],int(original_match[3]));group=part_groups[key]
                if delta!=-1 or {m['camera'] for m in group}!=camera_set or len(group)<2:
                    raise ValueError(f'MOV replacement timecode differs from the ATEM source start by {delta} frame(s): {link["original"]} -> {link["replacement"]}; no corroborated rollover was found')
                if key not in confirmed:
                    if any(len([prior for prior in media if prior['camera']==m['camera'] and prior['end']==m['start']])!=1 for m in group):
                        raise ValueError('One-frame MOV/ATEM rollover difference is not contiguous with every previous camera part; no timing was assumed')
                    program_pattern=re.compile(re.escape(original_match[1])+r' (\d+)\.(mp4|mov)',re.I)
                    programs=[p for p in Path(root).iterdir() if p.is_file() and program_pattern.fullmatch(p.name) and int(program_pattern.fullmatch(p.name)[1])==key[1]]
                    if len(programs)!=1 or not programs[0].resolve().is_relative_to(Path(root).resolve()):
                        raise ValueError('One-frame MOV/ATEM rollover difference needs one matching program recording for independent verification')
                    program=programs[0];pd=probe(program);pv=next(v for v in pd['streams'] if v['codec_type']=='video')
                    if (Fraction(pv['avg_frame_rate'])!=timing.fps or int(pv['nb_frames'])!=item['frames'] or pv.get('tags',{}).get('timecode')!=item['timecode'] or
                        Fraction(pv['duration_ts'])*Fraction(pv['time_base'])*timing.fps!=item['frames']):
                        raise ValueError(f'Program recording does not corroborate the one-frame MOV rollover timing: {program.name}')
                    confirmed[key]=program.name
                    warnings.append(f'Confirmed one-frame-late ATEM file-rollover metadata for part {key[1]}: all {len(group)} camera parts agree, follow their preceding parts without gaps, and match {program.name} timecode/frame count. Media timing is retained; live event timing is unchanged')
                link['timing_basis']='contiguous camera parts plus matching program recording'
            else:link['timing_basis']='exact ATEM source timecode'
            warnings.append(f'Relinked MP4 reference -> MOV: {link["original"]} -> {link["replacement"]}; verified project frame rate, exact frame duration, camera/part identity and {link["timing_basis"]}. Original DRP unchanged; original MP4 bytes were unavailable for comparison')
    boundaries=[]
    for camera in sorted({x['camera'] for x in media}):
        clips=sorted((x for x in media if x['camera']==camera),key=lambda x:x['start'])
        for a,b in zip(clips,clips[1:]): boundaries.append(dict(camera=camera,previous=a['path'],next=b['path'],gap_frames=b['start']-a['end']))
    return dict(timing=timing.data(),input=str(Path(project).resolve()),sha256=hashlib.sha256(Path(project).read_bytes()).hexdigest(),record_count=len(events),media=media,events=events,boundaries=boundaries,warnings=warnings,reference_mapping=reference_mapping,media_relinks=relinked)

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
