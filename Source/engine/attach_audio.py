"""Attach a chosen ATEM WAV source to camera video without retiming or encoding picture.

No ATEM project parser, BWF clock assumption, waveform matching or source writes.
Every mapping boundary is an exact integer sample and every video packet is
checked against its declared constant-rate presentation grid before building.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from fractions import Fraction
from contextlib import contextmanager

from timing import Timing

JOB = 'Attached Audio'
PLAN = 'Attach Audio Plan.json'
OWNER = '.attach-audio-owner.json'
STATE = '.attach-audio-state.json'
OWNER_ID = 'ISO Assemble attach audio v1'
VIDEO = re.compile(r'^(.+) CAM (\d+) (\d+)\.(mp4|mov)$', re.I)
AUDIO = re.compile(r'^(.+) (CAM|MIC) (\d+) (\d+)\.wav$', re.I)
_active = None


@contextmanager
def _cancellation():
    def stop(signum, frame):
        if _active is not None and _active.poll() is None: _active.terminate()
        raise SystemExit(130)
    try: previous=signal.signal(signal.SIGTERM,stop)
    except ValueError: previous=None  # Library callers may use a worker thread.
    try: yield
    finally:
        if previous is not None:signal.signal(signal.SIGTERM,previous)


def _progress(callback, message):
    if callback:
        callback(message)


def _regular(path):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f'Expected a regular file, not a symlink: {path}')


def _snapshot(path):
    path = Path(path); _regular(path); s = path.stat()
    return [s.st_size, s.st_mtime_ns, s.st_dev, s.st_ino]


def _safe_directory(path):
    path = Path(os.path.abspath(path))
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ValueError(f'Symlink directories are not supported for this job: {part}')
        if part.exists() and not part.is_dir():
            raise ValueError(f'Expected a directory: {part}')
    return path


def _read_json(path):
    _regular(path)
    try:
        return json.loads(path.read_text())
    except (ValueError, UnicodeError) as error:
        raise ValueError(f'Invalid job file {path.name}: {error}') from error


def _write_json(path, data):
    if path.exists() or path.is_symlink():
        _regular(path)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.write-', delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(data, handle, indent=2); handle.write('\n')
        handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def _fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _run(arguments, progress=None):
    global _active
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _active = process
    try:
        started=time.monotonic()
        while True:
            try:
                output, error = process.communicate(timeout=15); break
            except subprocess.TimeoutExpired:
                name=Path(arguments[arguments.index('-i')+1]).name if '-i' in arguments else Path(arguments[0]).name
                _progress(progress, f'Still processing {name} ({int(time.monotonic()-started)} seconds)…')
    except BaseException:
        process.kill(); process.communicate(); raise
    finally:
        _active = None
    if process.returncode:
        raise ValueError(f'{Path(arguments[0]).name} failed: {error.decode(errors="replace")[-1600:]}')
    return output


def _probe(path):
    return json.loads(_run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))


def discover(root):
    root = _safe_directory(root)
    if not root.is_dir():
        raise ValueError(f'Recording folder is unavailable: {root}')
    video_dir = _safe_directory(root/'Video ISO Files')
    audio_dir = _safe_directory(root/'Audio Source Files')
    if not video_dir.is_dir() or not audio_dir.is_dir():
        raise ValueError('Choose the recording root containing Video ISO Files and Audio Source Files.')
    cameras, audio, prefixes, warnings = {}, {}, set(), []
    for file in sorted(video_dir.iterdir()):
        if file.name.startswith('.') or file.suffix.lower() not in ('.mp4', '.mov'):
            continue
        _regular(file); match = VIDEO.fullmatch(file.name)
        if not match:
            raise ValueError(f'Cannot identify camera and part number: {file.name}')
        prefix, camera, part = match[1], int(match[2]), int(match[3])
        if camera < 1 or part < 1:
            raise ValueError(f'Camera and part numbers must be positive: {file.name}')
        group = cameras.setdefault(camera, {})
        if part in group:
            raise ValueError(f'Duplicate camera {camera}, part {part}: {group[part]["name"]} and {file.name}; select one version.')
        prefixes.add(prefix)
        group[part] = dict(path=str(file), name=file.name, camera=camera, part=part)
    if not cameras:
        raise ValueError('No camera MP4/MOV files found in Video ISO Files.')
    if len(prefixes) != 1:
        raise ValueError('Camera files have different recording prefixes; select a single recording folder.')
    prefix = next(iter(prefixes))
    for file in sorted(audio_dir.iterdir()):
        if file.name.startswith('.') or file.suffix.lower() != '.wav':
            continue
        _regular(file); match = AUDIO.fullmatch(file.name)
        if not match:
            warnings.append(f'Unrecognized WAV name was not offered as a source: {file.name}'); continue
        source = f'{match[2].upper()} {int(match[3])}'; part = int(match[4])
        if int(match[3]) < 1 or part < 1:
            raise ValueError(f'Audio source and part numbers must be positive: {file.name}')
        group = audio.setdefault(source, {})
        if part in group:
            raise ValueError(f'Duplicate {source} audio part {part}: {file.name}')
        group[part] = dict(path=str(file), name=file.name, part=part, prefix=match[1])
    if not audio:
        raise ValueError('No CAM N or MIC N WAV sources found in Audio Source Files.')
    groups = [dict(camera=camera, clips=[parts[n] for n in sorted(parts)]) for camera, parts in sorted(cameras.items())]
    sources = [dict(id=source, files=[parts[n] for n in sorted(parts)])
               for source, parts in sorted(audio.items(), key=lambda item:(item[0].split()[0], int(item[0].split()[1])))]
    return dict(root=str(root), cameras=len(cameras), clips=sum(len(g['clips']) for g in groups),
                audioISOs=sum(len(g['files']) for g in sources), camera_groups=groups, audio_sources=sources,
                choices=[dict(id=g['id'], label=f'{g["id"]} ({len(g["files"])} WAV part(s))') for g in sources],
                prefix=prefix, warnings=warnings)


def _timecode(probe, fps, path):
    values = {str(v).strip() for record in [probe.get('format', {}), *probe['streams']]
              for k, v in record.get('tags', {}).items() if k.lower() == 'timecode' and v}
    if len(values) != 1:
        raise ValueError(f'{path.name}: missing or conflicting embedded timecode.')
    tc = next(iter(values)); timing = Timing(fps, ';' in tc)
    timing.frames(tc)  # Reject invalid frame numbers and nonexistent DF labels.
    return tc


def _video_info(path, probe):
    streams = [s for s in probe['streams'] if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')]
    if len(streams) != 1:
        raise ValueError(f'{path.name}: expected exactly one video stream.')
    stream = streams[0]
    if stream.get('codec_name') != 'h264':
        raise ValueError(f'{path.name}: this ATEM attachment workflow requires H.264 video.')
    if stream.get('field_order') not in (None, 'unknown', 'progressive'):
        raise ValueError(f'{path.name}: interlaced video is unsupported; no retiming was performed.')
    try:
        fps = Fraction(stream['r_frame_rate']); average = Fraction(stream['avg_frame_rate'])
        count = int(stream['nb_frames']); time_base = Fraction(stream['time_base'])
        duration = int(stream['duration_ts'])*time_base
        start = int(stream['start_pts'])
        Timing(fps, False)
    except (KeyError, ValueError, ZeroDivisionError) as error:
        raise ValueError(f'{path.name}: incomplete or unsupported video timing metadata: {error}') from error
    if count <= 0 or average != fps or duration != Fraction(count, 1)/fps:
        raise ValueError(f'{path.name}: gapped/variable-rate timing or frame-count mismatch (nominal {fps}, average {average}, {count} frames). No retiming was performed.')
    if start != 0:
        raise ValueError(f'{path.name}: nonzero video start_pts ({start}); an edit-list delay cannot be normalized without changing timing.')
    step = Fraction(1, 1)/(fps*time_base)
    if step.denominator != 1:
        raise ValueError(f'{path.name}: video timestamps do not have an exact frame grid.')
    return dict(fps=str(fps), frames=count, time_base=str(time_base), step=int(step), start_pts=start,
                width=int(stream['width']), height=int(stream['height']), timecode=_timecode(probe, fps, path))


def _check_packets(path, info, progress=None):
    """Check all presentation timestamps, including B-frame packet reordering.

    A matching average alone cannot catch an internal gap compensated elsewhere.
    Packet PTS must cover every declared presentation-frame index exactly once.
    """
    global _active
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_packets',
            '-show_entries', 'packet=pts,dts,duration', '-of', 'compact=p=0:nk=0', str(path)],
            stdout=subprocess.PIPE, stderr=errors, text=True)
        _active = process; seen = bytearray(info['frames']); count = 0; previous_dts = None; heartbeat=time.monotonic()
        try:
            for line in process.stdout:
                if not line.strip(): continue
                values = dict(p.split('=', 1) for p in line.strip().split('|') if '=' in p)
                if 'pts' not in values: continue  # Packet side-data continuation.
                try:
                    pts, dts, duration = (int(values[k]) for k in ('pts', 'dts', 'duration'))
                except (KeyError, ValueError) as error:
                    raise ValueError(f'{path.name}: missing packet timing; cannot prove continuous video.') from error
                index, remainder = divmod(pts-info['start_pts'], info['step'])
                if remainder or index < 0 or index >= info['frames'] or seen[index] or duration != info['step']:
                    raise ValueError(f'{path.name}: gapped/variable-rate or duplicate video packet timestamps. No retiming was performed.')
                if previous_dts is not None and dts-previous_dts != info['step']:
                    raise ValueError(f'{path.name}: discontinuous video decode timestamps. No retiming was performed.')
                seen[index] = 1; count += 1; previous_dts = dts
                if time.monotonic()-heartbeat>=15:
                    _progress(progress, f'Checking {path.name}: {count}/{info["frames"]} video packets…');heartbeat=time.monotonic()
            status = process.wait()
            if status or count != info['frames'] or not all(seen):
                errors.seek(0)
                raise ValueError(f'{path.name}: packet/frame count mismatch or unreadable media ({count}/{info["frames"]}): {errors.read().decode(errors="replace")[-500:]}')
        finally:
            if process.poll() is None: process.kill(); process.wait()
            process.stdout.close(); _active = None


def _audio_info(path, probe):
    streams = [s for s in probe['streams'] if s['codec_type'] == 'audio']
    if len(streams) != 1:
        raise ValueError(f'{path.name}: expected exactly one PCM audio stream.')
    stream = streams[0]
    if stream.get('codec_name') != 'pcm_s24le' or int(stream.get('sample_rate', 0)) != 48000 or int(stream.get('channels', 0)) != 2:
        raise ValueError(f'{path.name}: expected 48 kHz stereo 24-bit PCM WAV audio.')
    try:
        samples = int(stream['duration_ts'])*Fraction(stream['time_base'])*48000
    except (KeyError, ValueError, ZeroDivisionError) as error:
        raise ValueError(f'{path.name}: missing exact audio sample count.') from error
    if samples.denominator != 1 or samples <= 0:
        raise ValueError(f'{path.name}: audio length is not a positive integer number of samples.')
    return dict(samples=int(samples), sample_rate=48000, channels=2, codec='pcm_s24le',
                bwf_time_reference=probe.get('format', {}).get('tags', {}).get('time_reference'))


def _map_parts(reference, wavs):
    mapping = []; wi = 0; position = 0; day = 0; last_raw = None; previous_end = None
    for clip in reference:
        if wi >= len(wavs): raise ValueError('Selected audio ends before the video parts.')
        info = clip['media']; samples = Fraction(info['frames']*48000, 1)/Fraction(info['fps'])
        timing = Timing(info['fps'], ';' in info['timecode']); raw=timing.frames(info['timecode'])
        if last_raw is not None and raw<last_raw and last_raw-raw>timing.day//2:day+=timing.day
        absolute=day+raw
        if previous_end is not None and absolute<previous_end:
            raise ValueError(f'Video part {clip["part"]}: backwards or overlapping timecode across recording parts; no timing was guessed.')
        last_raw=raw; previous_end=absolute+info['frames']
        if samples.denominator != 1:
            raise ValueError(f'{Path(clip["path"]).name}: {info["frames"]} frames require {samples} audio samples; fractional sample boundaries are not rounded.')
        wav = wavs[wi]; end = position+int(samples)
        if end > wav['media']['samples']:
            raise ValueError(f'Video part {clip["part"]} crosses the end of {Path(wav["path"]).name}; WAV and video boundaries do not match exactly.')
        if position and mapping:
            previous = mapping[-1]
            expected = (timing.frames(previous['timecode'])+previous['frames'])%timing.day
            if timing.frames(info['timecode']) != expected:
                raise ValueError(f'Video part {clip["part"]}: timecode gap/overlap within one WAV group. No timing was guessed.')
        mapping.append(dict(part=clip['part'], wav=wav['path'], start_sample=position, end_sample=end,
                            samples=int(samples), frames=info['frames'], timecode=info['timecode']))
        position = end
        if position == wav['media']['samples']: wi += 1; position = 0
    if wi != len(wavs) or position:
        raise ValueError('Selected WAV lengths and video totals do not land on exactly the same boundaries.')
    return mapping


def _compute_plan(root, source, job, progress):
    inventory = discover(root)
    selected = next((s for s in inventory['audio_sources'] if s['id'] == source), None)
    if selected is None: raise ValueError(f'Choose an available audio source: {source}')
    if any(w['prefix'] != inventory['prefix'] for w in selected['files']):
        raise ValueError('Selected WAV prefix differs from the camera recording prefix; no matching was guessed.')
    reference_parts = [c['part'] for c in inventory['camera_groups'][0]['clips']]
    for group in inventory['camera_groups']:
        if [c['part'] for c in group['clips']] != reference_parts:
            raise ValueError(f'Camera {group["camera"]}: part numbers differ from the other cameras.')
    inputs = {}; reference = None
    for group in inventory['camera_groups']:
        for clip in group['clips']:
            path = Path(clip['path']); before = _snapshot(path)
            _progress(progress, f'Checking camera {group["camera"]}, part {clip["part"]}: {path.name}')
            info = _video_info(path, _probe(path)); _check_packets(path, info, progress)
            if before != _snapshot(path): raise ValueError(f'Media changed during preflight: {path.name}')
            clip['media'] = info; inputs[str(path)] = dict(snapshot=before, media=info)
        if reference is None:
            reference = group['clips']; fps = reference[0]['media']['fps']; drop = ';' in reference[0]['media']['timecode']
            for clip in reference:
                if clip['media']['fps'] != fps or (';' in clip['media']['timecode']) != drop:
                    raise ValueError('Video parts have different frame rates or DF/NDF modes.')
        else:
            for actual, expected in zip(group['clips'], reference):
                for key in ('frames', 'fps', 'timecode', 'width', 'height'):
                    if actual['media'][key] != expected['media'][key]:
                        raise ValueError(f'Camera {group["camera"]}, part {actual["part"]}: {key} differs from the reference camera.')
    for wav in selected['files']:
        path = Path(wav['path']); before = _snapshot(path)
        _progress(progress, f'Checking selected audio: {path.name}')
        wav['media'] = _audio_info(path, _probe(path))
        if before != _snapshot(path): raise ValueError(f'Media changed during preflight: {path.name}')
        inputs[str(path)] = dict(snapshot=before, media=wav['media'])
    mapping = _map_parts(reference, selected['files']); mapped = {m['part']:m for m in mapping}; outputs = []
    for group in inventory['camera_groups']:
        for clip in group['clips']:
            m = mapped[clip['part']]
            outputs.append(dict(camera=group['camera'], part=clip['part'], video=clip['path'], audio=m['wav'],
                start_sample=m['start_sample'], end_sample=m['end_sample'], frames=m['frames'], fps=fps,
                timecode=m['timecode'], output=str(job/(Path(clip['path']).stem+'.mov'))))
    estimated = sum(inputs[o['video']]['snapshot'][0]+(o['end_sample']-o['start_sample'])*6 for o in outputs)
    return dict(version=1, kind='attach-iso-audio', root=inventory['root'], source=source, output=str(job),
                path=str(job/PLAN), report=str(job/'Attach Audio Plan.txt'), fps=fps, sample_rate=48000, channels=2,
                mapping=mapping, outputs=outputs, inputs=inputs, estimated_output_bytes=estimated,
                warnings=inventory['warnings']+['BWF timestamps were ignored for matching; exact WAV lengths determined every audio slice.',
                'Output MOVs must be imported separately. The ATEM project still references the original camera files.'])


def _job(out):
    out = _safe_directory(out)
    return out if (out/OWNER).exists() else _safe_directory(out/JOB)


def make_plan(root, source, out, progress=None):
    with _cancellation():return _make_plan(root,source,out,progress)


def _make_plan(root, source, out, progress):
    job = _job(out); root = _safe_directory(root)
    if job == root or job.is_relative_to(root/'Video ISO Files') or job.is_relative_to(root/'Audio Source Files'):
        raise ValueError('Choose a results location outside the source media subfolders.')
    if job.exists() and not (job/OWNER).is_file():
        raise ValueError(f'Results folder is not owned by this workflow; choose a new destination: {job}')
    plan = _compute_plan(root, source, job, progress)
    signature = _fingerprint(plan)
    if job.exists():
        if not (job/OWNER).is_file(): raise ValueError(f'Results folder is not owned by this workflow; choose a new destination: {job}')
        owner = _read_json(job/OWNER)
        if owner != dict(owner=OWNER_ID, plan_hash=signature):
            raise ValueError('This results folder belongs to another plan or the inputs changed. Choose a new output folder.')
        if _fingerprint(_read_json(job/PLAN)) != signature: raise ValueError('Saved plan was changed; choose a new output folder.')
        return plan
    job.mkdir(parents=True, exist_ok=False)
    _write_json(job/OWNER, dict(owner=OWNER_ID, plan_hash=signature)); _write_json(job/PLAN, plan)
    lines = [f'Audio attachment dry run — {source}', f'Frame rate: {plan["fps"]}; audio: 48000 Hz, stereo PCM24',
             f'Outputs: {len(plan["outputs"])}; estimated bytes (excluding MOV overhead): {plan["estimated_output_bytes"]}',
             'No MOV files have been created.', '']
    lines += [f'Video part {m["part"]} → {Path(m["wav"]).name}: samples [{m["start_sample"]}, {m["end_sample"]}), {m["frames"]} frames, {m["timecode"]}' for m in plan['mapping']]
    lines += ['', *plan['warnings']]
    (job/'Attach Audio Plan.txt').write_text('\n'.join(lines)+'\n')
    return plan


def _md5(arguments, progress=None):
    value = _run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', *arguments, '-f', 'md5', '-'], progress).decode().strip()
    if not re.fullmatch(r'MD5=[0-9a-fA-F]{32}', value): raise ValueError('FFmpeg did not return a complete stream hash.')
    return value[4:].lower()


def _verify(item, output, source_video_hash, source_audio_hash, progress=None):
    probe = _probe(output); video = _video_info(output, probe); audio = _audio_info(output, probe)
    if video['frames'] != item['frames'] or video['fps'] != item['fps'] or video['timecode'] != item['timecode']:
        raise ValueError(f'{output.name}: output video length/rate/timecode verification failed.')
    if not any(s.get('codec_tag_string') == 'tmcd' for s in probe['streams']):
        raise ValueError(f'{output.name}: proper MOV tmcd track is missing.')
    if audio['samples'] != item['end_sample']-item['start_sample']:
        raise ValueError(f'{output.name}: output audio sample count does not match its exact planned slice.')
    _check_packets(output, video, progress)
    picture = _md5(['-i', str(output), '-map', '0:v:0', '-c', 'copy'], progress)
    sound = _md5(['-i', str(output), '-map', '0:a:0', '-c:a', 'pcm_s24le'], progress)
    if picture != source_video_hash: raise ValueError(f'{output.name}: picture packet hash differs from source; output rejected.')
    if sound != source_audio_hash: raise ValueError(f'{output.name}: PCM audio hash differs from the selected WAV slice; output rejected.')
    return dict(video_md5=picture, audio_md5=sound, frames=video['frames'], samples=audio['samples'],
                timecode=video['timecode'], tmcd=True, sample_rate=48000, channels=2, audio_codec='pcm_s24le')


def build(out, progress=None):
    with _cancellation():return _build(out,progress)


def _build(out, progress):
    job = _job(out)
    if not (job/OWNER).exists(): raise ValueError('Create a dry-run audio plan first.')
    owner = _read_json(job/OWNER); plan = _read_json(job/PLAN)
    if owner != dict(owner=OWNER_ID, plan_hash=_fingerprint(plan)):
        raise ValueError('Saved audio plan or ownership manifest was changed; no outputs were built.')
    if plan['output'] != str(job): raise ValueError('Plan output location changed; no outputs were built.')
    lock_path = job/'.attach-audio.lock'
    if lock_path.is_symlink(): raise ValueError('Unsafe job lock symlink.')
    descriptor = os.open(lock_path, os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
    try:
        try: fcntl.flock(descriptor, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error: raise ValueError('This audio job is already running.') from error
        return _build_locked(job, owner, plan, progress)
    finally:
        os.close(descriptor)


def _build_locked(job, owner, plan, progress):
    for name in ('Attach Audio Verification.json','Attach Audio Verification.txt'):
        if (job/name).exists() or (job/name).is_symlink():_regular(job/name)
    for path, data in plan['inputs'].items():
        if _snapshot(path) != data['snapshot']: raise ValueError(f'Input changed after planning: {Path(path).name}; create a new plan.')
    _progress(progress, 'Revalidating every source and exact packet timing before creating any MOV…')
    current = _compute_plan(plan['root'], plan['source'], job, progress)
    if _fingerprint(current) != owner['plan_hash']: raise ValueError('Media inventory or plan changed; no MOV was created.')
    state = _read_json(job/STATE) if (job/STATE).exists() else dict(version=1, plan_hash=owner['plan_hash'], outputs={})
    if state.get('plan_hash') != owner['plan_hash']: raise ValueError('Resume manifest belongs to a different plan.')
    # Reject all collisions before the first output, not halfway through a job.
    for item in plan['outputs']:
        output = Path(item['output'])
        if output.exists() or output.is_symlink():
            _regular(output)
            if state['outputs'].get(str(output), {}).get('status') not in ('complete', 'publishing'):
                raise ValueError(f'Unowned output collision: {output.name}; choose a new destination.')
    partial = _safe_directory(job/'.partial'); partial.mkdir(exist_ok=True)
    remaining=0; unfinished=0
    for item in plan['outputs']:
        output=Path(item['output']);entry=state['outputs'].get(str(output),{})
        if entry.get('status')=='complete' and output.exists():continue
        estimate=plan['inputs'][item['video']]['snapshot'][0]+(item['end_sample']-item['start_sample'])*6
        temporary=Path(entry['temporary']) if entry.get('temporary') else None
        if temporary is not None:
            if temporary.parent!=partial or not re.fullmatch(r'[0-9a-f]{32}\.mov',temporary.name):raise ValueError('Unsafe temporary filename in resume manifest.')
            if temporary.exists() or temporary.is_symlink():_regular(temporary);estimate=max(0,estimate-temporary.stat().st_size)
        remaining+=estimate;unfinished+=1
    required=remaining+remaining//50+(unfinished+1)*1024*1024
    free=shutil.disk_usage(job).free
    if free<required:raise ValueError(f'Insufficient output disk space: need approximately {required:,} additional bytes including MOV overhead; {free:,} bytes are free. No new MOV was created.')
    video_hashes = {}; audio_hashes = {}; verified = []; resumed = 0
    for number, item in enumerate(plan['outputs'], 1):
        output = Path(item['output']); key = str(output); entry = state['outputs'].get(key)
        _progress(progress, f'[{number}/{len(plan["outputs"])}] Hashing source and selected audio: {output.name}')
        if item['video'] not in video_hashes:
            video_hashes[item['video']] = _md5(['-i', item['video'], '-map', '0:v:0', '-c', 'copy'], progress)
        audio_key = (item['audio'], item['start_sample'], item['end_sample'])
        if audio_key not in audio_hashes:
            audio_hashes[audio_key] = _md5(['-i', item['audio'], '-map', '0:a:0', '-af',
                f'atrim=start_sample={item["start_sample"]}:end_sample={item["end_sample"]}', '-c:a', 'pcm_s24le'], progress)
        picture, sound = video_hashes[item['video']], audio_hashes[audio_key]
        if output.exists() and entry and entry.get('status')=='publishing' and entry.get('reservation')==_snapshot(output) and output.stat().st_size==0:
            output.unlink()  # Our saved empty reservation, interrupted before atomic publish.
        if output.exists():
            # Completed files are re-probed and re-hashed before being accepted.
            result = _verify(item, output, picture, sound, progress); resumed += 1
        else:
            if entry and entry.get('status') == 'complete': raise ValueError(f'Previously verified output is missing: {output.name}')
            if entry and entry.get('temporary'):
                temporary = Path(entry['temporary'])
                if temporary.parent != partial or not re.fullmatch(r'[0-9a-f]{32}\.mov', temporary.name):
                    raise ValueError('Unsafe temporary filename in resume manifest.')
                if temporary.exists() or temporary.is_symlink():
                    _regular(temporary)
                    try: result = _verify(item, temporary, picture, sound, progress)
                    except ValueError: temporary.unlink(); result = None
                else: result = None
            else:
                temporary = partial/(uuid.uuid4().hex+'.mov'); result = None
            entry = dict(status='building', temporary=str(temporary)); state['outputs'][key] = entry; _write_json(job/STATE, state)
            if result is None:
                _progress(progress, f'[{number}/{len(plan["outputs"])}] Copying video and attaching PCM24: {output.name}')
                _run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-n', '-i', item['video'], '-i', item['audio'],
                    '-filter_complex', f'[1:a:0]atrim=start_sample={item["start_sample"]}:end_sample={item["end_sample"]},asetpts=PTS-STARTPTS[a]',
                    '-map', '0:v:0', '-map', '[a]', '-c:v', 'copy', '-c:a', 'pcm_s24le', '-map_metadata', '0',
                    '-timecode', item['timecode'], '-video_track_timescale', str(Fraction(item['fps']).numerator), str(temporary)], progress)
                _progress(progress, f'[{number}/{len(plan["outputs"])}] Verifying all picture and audio bytes: {output.name}')
                result = _verify(item, temporary, picture, sound, progress)
            # Exclusive reservation prevents overwriting a destination. The
            # reserved file is ours; atomic replacement works on exFAT as well.
            fd = os.open(output, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
            os.close(fd); entry.update(status='publishing', reservation=_snapshot(output)); _write_json(job/STATE, state)
            if _snapshot(output) != entry['reservation']: raise ValueError('Output reservation changed unexpectedly.')
            os.replace(temporary, output)
        entry = dict(status='complete', verification=result, snapshot=_snapshot(output))
        state['outputs'][key] = entry; _write_json(job/STATE, state)
        verified.append(dict(path=key, **result))
    for path, data in plan['inputs'].items():
        if _snapshot(path) != data['snapshot']: raise ValueError(f'Input changed during building: {Path(path).name}; outputs are not approved.')
    report = dict(version=1, plan=str(job/PLAN), source=plan['source'], verified=verified,
                  verified_count=len(verified), resumed_count=resumed,
                  notes=['Picture packets were stream-copied and hashed against each source.',
                         'Every PCM24 output was hashed against its exact selected WAV sample slice.',
                         'Frame count, video packet timing, audio sample count and MOV tmcd were checked.',
                         'Import the new MOVs separately; the ATEM project was not modified.'])
    _write_json(job/'Attach Audio Verification.json', report)
    text = [f'Audio attachment verified: {len(verified)} MOV files; {resumed} revalidated from an earlier run.', *report['notes'], '']
    text += [f'{Path(v["path"]).name}: {v["frames"]} frames, {v["samples"]} samples, {v["timecode"]}; video MD5 {v["video_md5"]}; audio MD5 {v["audio_md5"]}' for v in verified]
    (job/'Attach Audio Verification.txt').write_text('\n'.join(text)+'\n')
    return dict(path=str(job), output=str(job), report=str(job/'Attach Audio Verification.txt'),
                outputs=[v['path'] for v in verified], verified_count=len(verified), resumed_count=resumed, plan=str(job/PLAN))
