"""Check actual Resolve multicam behavior before converting a production project.

The proof imports two existing camera files read-only, selects both native angles,
optionally adds a short dissolve, then saves/exports/reimports. It does not claim
a UI angle-switch test. All temporary projects have persistent ownership IDs.
"""
import hashlib
import json
import re
import uuid
import xml.etree.ElementTree as E
from pathlib import Path

from timing import Timing
from resolve_project import (apply_transitions, clips, transition_inventory,
                             validate, video_items)

SCHEMA = 1


def _version_fields(version):
    if isinstance(version, (list, tuple)) and len(version) >= 4:
        try:
            fields = tuple(int(x) for x in version[:4])
        except (TypeError, ValueError):
            raise ValueError('Resolve returned an unreadable version. Reopen Resolve and try again.')
        if any(x < 0 for x in fields):
            raise ValueError('Resolve returned an invalid version.')
        return fields
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)[^.]*\.(\d+)', str(version))
    if not match:
        raise ValueError(f'Cannot read Resolve version {version!r}. Reopen Resolve and try again.')
    return tuple(int(x) for x in match.groups())


def check_version(version, needs_mix=False):
    fields = _version_fields(version)
    minimum = (21, 1) if needs_mix else (21, 0)
    if fields[:2] < minimum:
        if needs_mix:
            raise ValueError('Rebuilding Mix transitions needs Resolve Studio 21.1 or newer. '
                             'Use a current Resolve version, or leave Mix reconstruction off for cut-only projects.')
        raise ValueError('Multicam project creation needs Resolve Studio 21 or newer. '
                         'Camera files with shared audio remains available without an editor.')


def _write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def _proof_sources(data):
    media = sorted(data.get('media', []), key=lambda m: (m['start'], m['camera'], m['path']))
    for i, left in enumerate(media):
        for right in media[i+1:]:
            if left['camera'] == right['camera'] or Path(left['path']).resolve() == Path(right['path']).resolve():
                continue
            start, end = max(left['start'], right['start']), min(left['end'], right['end'])
            if end-start >= 12:
                return [left, right], start, min(24, end-start)
    raise ValueError('Compatibility check needs two different camera clips with at least 12 overlapping frames. '
                     'No production project was changed.')


def _proof_xml(sources, start, duration, timing, name, needs_mix):
    def el(parent, tag, **attrs):
        return E.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    tm = timing.xml_time
    r = E.Element('fcpxml', version='1.8'); res = el(r, 'resources')
    el(res, 'format', id='f1', name='ISO Assemble Compatibility', frameDuration=tm(1), width=1920, height=1080)
    for i, source in enumerate(sources, 1):
        el(res, 'asset', id=f'a{i}', name=Path(source['path']).name,
           src=Path(source['path']).resolve().as_uri(), start=tm(source['start']),
           duration=tm(source['frames']), hasVideo=1, format='f1')
    mc_name = name + '_Multicam'
    mc = el(el(res, 'media', id='mc1', name=mc_name), 'multicam', format='f1',
            tcStart='0s', tcFormat=timing.display, duration=tm(duration))
    for i in (1, 2):
        angle = el(mc, 'mc-angle', name=f'{i} Camera {i}', angleID=f'angle{i}')
        clip = el(angle, 'clip', name=f'Camera {i}', offset='0s', start=tm(start),
                  duration=tm(duration), format='f1', tcFormat=timing.display)
        el(clip, 'video', ref=f'a{i}', offset=tm(start), start=tm(start), duration=tm(duration))
    project = el(el(el(r, 'library'), 'event', name=name), 'project', name=name+'_Edit')
    seq = el(project, 'sequence', format='f1', tcStart=tm(start), duration=tm(duration), tcFormat=timing.display)
    spine = el(seq, 'spine'); split = duration // 2
    cuts = []
    for angle, a, b in ((1, 0, split), (2, split, duration)):
        clip = el(spine, 'mc-clip', name=mc_name, ref='mc1', offset=tm(start+a),
                  start=tm(a), duration=tm(b-a), srcEnable='video')
        el(clip, 'mc-source', angleID=f'angle{angle}', srcEnable='video')
        cuts.append(dict(start=start+a, end=start+b, angle=angle, session=0))
    transitions = []
    if needs_mix:
        count = min(4, split)
        transitions.append(dict(start=start+split-count, end=start+split, duration_frames=count,
            cut_frame=start+split, from_cut_index=0, to_cut_index=1, from_angle=1, to_angle=2,
            unresolved=False, resolve_options=dict(type='Cross Dissolve', category='simple',
                                                   position='end', alignment='left', duration=count)))
    plan = dict(timing=timing.data(), origin=start, end=start+duration, cuts=cuts,
                camera_names={'1': 'Camera 1', '2': 'Camera 2'},
                sessions=[dict(start=start, end=start+duration, multicam_name=mc_name)],
                transitions=transitions, review_markers=[])
    E.indent(r)
    return E.tostring(r, encoding='utf-8', xml_declaration=True), plan


def _verify_project(project, plan, sources):
    timelines = [project.GetTimelineByIndex(i) for i in range(1, project.GetTimelineCount()+1)]
    target = [t for t in timelines if t.GetName().endswith('_Edit')]
    if len(target) != 1:
        raise RuntimeError('Small multicam test did not produce exactly one edit timeline')
    timeline = target[0]
    count = validate(timeline, plan)
    items = video_items(timeline)
    ids = {item.GetMediaPoolItem().GetUniqueId() for item in items}
    if len(ids) != 1:
        raise RuntimeError('Small test selections do not share one native multicam clip')
    mc = items[0].GetMediaPoolItem()
    if int(mc.GetClipProperty('Frames')) != plan['end']-plan['origin']:
        raise RuntimeError('Small native multicam duration changed')
    present = {str(Path(p).resolve()) for clip in clips(project.GetMediaPool().GetRootFolder())
               if (p := clip.GetClipProperty('File Path'))}
    expected = {str(Path(m['path']).resolve()) for m in sources}
    if not expected <= present:
        raise RuntimeError('Small test source media did not resolve after import')
    transition_count = len(transition_inventory(timeline, plan, complete=True))
    return dict(cuts_verified=count, native_multicam_clips=1, selected_angles=[1, 2],
                transitions_verified=transition_count, all_source_paths_present=True)


def _restore(pm, previous):
    current = pm.GetCurrentProject()
    if previous:
        if current and current.GetUniqueId() == previous['id']:
            return
        restored = pm.LoadProject(previous['name'])
        if not restored or restored.GetUniqueId() != previous['id']:
            raise RuntimeError('The compatibility check could not restore your previously open project. '
                               'Your production conversion was not started; reopen your project in Resolve.')
    elif current and not pm.CloseProject(current):
        raise RuntimeError('The compatibility check could not close its temporary project. Production conversion was not started.')


def prepare_current_project(resolve):
    """Save only an already named project; never open Resolve's Save-As modal."""
    pm = resolve.GetProjectManager()
    current = pm.GetCurrentProject()
    if not current:
        return None
    name = current.GetName()
    if name not in (pm.GetProjectListInCurrentFolder() or []):
        folder = current.GetMediaPool().GetRootFolder()
        empty = (current.GetTimelineCount() == 0 and not folder.GetClipList()
                 and not folder.GetSubFolderList())
        if empty:
            return None  # Resolve's empty, unsaved startup placeholder.
        raise ValueError('Your open Resolve project has not been saved yet and contains work. '
                         'Save it in Resolve, then retry. ISO Assemble has not changed it.')
    previous = dict(name=name, id=current.GetUniqueId())
    if not pm.SaveProject():
        raise ValueError('Could not save your currently open Resolve project. Save it in Resolve before retrying.')
    return previous


def ensure_compatible(resolve, data, out, needs_mix, progress=lambda message: None):
    version = resolve.GetVersionString()
    getter = getattr(resolve, 'GetVersion', None)
    version_fields = getter() if callable(getter) else version
    check_version(version_fields, needs_mix)
    timing = Timing.from_plan(data)
    sources, start, duration = _proof_sources(data)
    identity = []
    for m in data['media']:
        path = Path(m['path']).resolve(); stat = path.stat()
        identity.append(dict(path=str(path), size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                             camera=m['camera'], start=m['start'], end=m['end'], frames=m['frames']))
    behavior = Path(__file__).read_bytes() + b'\0' + Path(__file__).with_name('resolve_project.py').read_bytes()
    key = dict(schema=SCHEMA, behavior_sha256=hashlib.sha256(behavior).hexdigest(),
               resolve_version=version, resolve_version_fields=version_fields,
               timing=timing.data(), needs_mix=bool(needs_mix), sources=sorted(identity, key=lambda m:m['path']))
    fingerprint = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
    folder = Path(out).resolve() / 'Resolve Compatibility'
    if folder.is_symlink():
        raise ValueError('Compatibility check folder is a symbolic link. Choose another output folder.')
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / 'state.json'; report_path = folder / 'Compatibility Report.json'
    xml_path = folder / 'Proof.fcpxml'; export_path = folder / 'Proof.drp'
    for path in (state_path, report_path, xml_path, export_path):
        if path.is_symlink() or path.with_suffix(path.suffix+'.tmp').is_symlink():
            raise ValueError('A compatibility output is a symbolic link and was preserved. Choose another output folder.')
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state.get('schema') != SCHEMA or not re.fullmatch(r'[0-9a-f]{32}', state.get('owner', '')):
            raise ValueError('Compatibility check folder has no valid ownership record. Choose another output folder.')
    else:
        if any(folder.iterdir()):
            raise ValueError('Compatibility check folder already contains unowned files. Choose another output folder.')
        state = dict(schema=SCHEMA, owner=uuid.uuid4().hex, project_ids={}, complete=False)
        _write(state_path, state)
    pm = resolve.GetProjectManager()
    previous = prepare_current_project(resolve)
    if state.get('complete') and state.get('fingerprint') == fingerprint and report_path.is_file():
        report = json.loads(report_path.read_text())
        if report.get('fingerprint') == fingerprint and report.get('status') == 'passed' and report.get('previous_project_restored'):
            progress('Using the completed small multicam compatibility check for this Resolve version and recording.')
            return {**report, 'cached': True}
    base = 'ISOAssemble_Compat_' + state['owner'][:12]
    names = [base, base + '_Reopen']
    if previous and previous['name'] in names:
        raise ValueError('The earlier ISO Assemble compatibility test is currently open. '
                         'Select your working project in Resolve and retry so it can be restored safely.')
    state.update(complete=False, fingerprint=fingerprint, resolve_version=version)
    _write(state_path, state)
    error = None; result = None
    try:
        progress(f'Checking native multicam compatibility in Resolve {version} with two short camera selections…')
        existing = set(pm.GetProjectListInCurrentFolder() or [])
        # Validate both ownership records before replacing either proof project.
        for name in names:
            if name in existing:
                expected_id = state['project_ids'].get(name)
                project = pm.LoadProject(name)
                if not expected_id or not project or project.GetUniqueId() != expected_id:
                    raise RuntimeError('A compatibility project name is already used by an unowned or changed project; it was preserved')
        for name in names:
            if name in existing:
                project = pm.LoadProject(name)
                if not project or project.GetUniqueId() != state['project_ids'][name]:
                    raise RuntimeError('Compatibility project identity changed; existing project was preserved')
                if not pm.CloseProject(project) or not pm.DeleteProject(name):
                    raise RuntimeError('Could not replace the previous owned compatibility test project')
        xml, plan = _proof_xml(sources, start, duration, timing, base, needs_mix)
        xml_path.write_bytes(xml)
        if export_path.exists():
            export_path.unlink()  # Inside the ownership-checked compatibility folder only.
        project = pm.CreateProject(base)
        if not project:
            raise RuntimeError('Could not create the small compatibility test project')
        state['project_ids'][base] = project.GetUniqueId(); _write(state_path, state)
        if not project.SetSetting('timelineFrameRate', timing.resolve_rate+(' DF' if timing.drop else '')):
            raise RuntimeError('Resolve rejected the compatibility timeline frame rate')
        for setting, value in (('timelineResolutionWidth', '1920'), ('timelineResolutionHeight', '1080')):
            if not project.SetSetting(setting, value):
                raise RuntimeError('Resolve rejected the compatibility timeline raster')
        timeline = project.GetMediaPool().ImportTimelineFromFile(str(xml_path))
        if not timeline:
            raise RuntimeError('Resolve could not import the two-angle multicam test')
        if not project.SetCurrentTimeline(timeline):
            raise RuntimeError('Resolve could not activate the small multicam test timeline')
        validate(timeline, plan)
        apply_transitions(timeline, plan)
        before = _verify_project(project, plan, sources)
        if not pm.SaveProject():
            raise RuntimeError('Resolve could not save the small multicam test')
        if not pm.ExportProject(base, str(export_path)) or not export_path.is_file() or not export_path.stat().st_size:
            raise RuntimeError('Resolve could not export the small multicam test')
        progress('Reopening the small test to verify native angles, timing, media and transitions…')
        if not pm.ImportProject(str(export_path), names[1]):
            raise RuntimeError('Resolve could not reimport the small multicam test')
        reopened = pm.LoadProject(names[1])
        if not reopened:
            raise RuntimeError('Resolve could not open the reimported compatibility test')
        state['project_ids'][names[1]] = reopened.GetUniqueId(); _write(state_path, state)
        after = _verify_project(reopened, plan, sources)
        if before != after:
            raise RuntimeError('Native multicam test changed after export/reimport')
        result = dict(status='passed', cached=False, fingerprint=fingerprint, **key, **after,
                      proof_project_names=names, source_paths=[m['path'] for m in sources],
                      timeline_frames=duration, exported_project=str(export_path),
                      validation='Small native multicam API import/save/export/reimport proof; no UI angle-switch test. '
                                 'The complete production conversion still receives its own validation.')
    except Exception as exc:
        error = exc
    finally:
        try:
            _restore(pm, previous)
        except Exception as restore_error:
            error = RuntimeError((str(error)+'; ' if error else '')+str(restore_error))
    if error is not None:
        state.update(complete=False, error=str(error)); _write(state_path, state)
        raise ValueError(f'Resolve {version} did not pass the small multicam compatibility check: {error}. '
                         'The production project was not started. See '+str(state_path)) from error
    result['previous_project_restored'] = True
    _write(report_path, result)
    state.update(complete=True, error=None); _write(state_path, state)
    progress('Small native multicam compatibility check passed. Continuing with the production conversion…')
    return result
