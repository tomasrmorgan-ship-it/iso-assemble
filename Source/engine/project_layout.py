"""Organize conversion-owned Resolve media and select the finished cut edit.

Only documented Resolve scripting methods are used. Ownership is limited to
exact manifest media paths, session multicam names, and generated timeline
names; unrelated items are never moved, renamed, or deleted.
"""
import os
from collections import defaultdict

from timing import Timing


BINS = ('01 Edit', '02 Multicam', '03 Camera Originals',
        '04 Audio ISOs', '05 Program Reference')


def _id(obj, label):
    value = obj.GetUniqueId() if obj else None
    if not value:
        raise RuntimeError(f'Resolve did not provide the identity of {label}')
    return str(value)


def _path(value):
    return os.path.normpath(os.path.abspath(os.path.expanduser(str(value))))


def _inventory(root):
    items, folders = {}, {}

    def visit(folder, path):
        if path in folders:
            raise RuntimeError(f'Duplicate media bin {path!r}; existing bins preserved')
        folders[path] = folder
        _id(folder, f'bin {path or "Master"}')
        for clip in folder.GetClipList() or []:
            uid = _id(clip, 'media pool item')
            if uid in items:
                raise RuntimeError('A media item appears in multiple bins; cannot move it safely')
            items[uid] = dict(item=clip, folder=path)
        # Duplicate sibling names are ambiguous even when no clips are present.
        for child in folder.GetSubFolderList() or []:
            visit(child, f'{path}/{child.GetName()}' if path else child.GetName())

    visit(root, '')
    return items, folders


def _timelines(project):
    result = defaultdict(list)
    for index in range(1, project.GetTimelineCount() + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline:
            result[timeline.GetName()].append(timeline)
    return result


def _edit(project, plan):
    name = plan['name'] + '_Edit'
    matches = _timelines(project).get(name, [])
    if len(matches) != 1:
        raise RuntimeError(f'Expected one finished edit timeline named {name!r}; found {len(matches)}')
    return matches[0]


def _targets(project, plan, items):
    """Return owned item IDs -> destination, plus optional absent program paths."""
    desired_paths, destinations = {}, {}

    def add_path(path, destination):
        normalized = _path(path)
        previous = desired_paths.get(normalized)
        if previous and previous != destination:
            raise RuntimeError(f'Manifest assigns one source to different media bins: {path}')
        desired_paths[normalized] = destination

    for row in plan.get('media', []):
        camera = int(row['camera'])
        if camera < 1:
            raise RuntimeError('Camera originals require a positive camera number')
        add_path(row['path'], f'{BINS[2]}/Camera {camera}')
    for row in plan.get('audio_inventory', []):
        if row.get('kind') == 'audio_iso':
            add_path(row['path'], BINS[3])
        elif str(row.get('tags', {}).get('com.apple.proapps.cameraName', '')) == '0':
            add_path(row['path'], BINS[4])
    for row in plan.get('program_files', []):
        add_path(row['path'] if isinstance(row, dict) else row, BINS[4])
    if plan.get('audio', {}).get('selected') == 'program':
        for row in plan['audio'].get('files', []):
            add_path(row['path'], BINS[4])

    path_items, multicams = defaultdict(list), defaultdict(list)
    for uid, row in items.items():
        clip = row['item']
        path = clip.GetClipProperty('File Path')
        if path:
            path_items[_path(path)].append(uid)
        if clip.GetClipProperty('Type') == 'Multicam':
            multicams[clip.GetName()].append(uid)

    def assign(uid, destination):
        if uid not in items:
            raise RuntimeError('Generated timeline is absent from the media pool')
        previous = destinations.get(uid)
        if previous and previous != destination:
            raise RuntimeError('One media item matches different conversion roles; existing clips preserved')
        destinations[uid] = destination

    missing_program = []
    for path, destination in desired_paths.items():
        matches = path_items.get(path, [])
        if len(matches) > 1:
            raise RuntimeError(f'Multiple media pool items reference {path}; cannot identify the imported original safely')
        if not matches:
            # Resolve can span program recordings into a single media item.
            # Camera/audio paths are separately required by conversion validation.
            if destination == BINS[4]:
                missing_program.append(path)
                continue
            raise RuntimeError(f'Imported source is missing from the media pool: {path}')
        assign(matches[0], destination)

    for session in plan.get('sessions', []):
        name = session['multicam_name']
        matches = multicams.get(name, [])
        if len(matches) != 1:
            raise RuntimeError(f'Expected one native multicam named {name!r}; found {len(matches)}')
        assign(matches[0], BINS[1])

    edit = _edit(project, plan)
    assign(_id(edit.GetMediaPoolItem(), 'finished edit media item'), BINS[0])
    timelines = _timelines(project)
    for name in (plan['name'] + '_Live_Program_Reference',
                 plan['name'] + '_Original_ATEM_Reference'):
        matches = timelines.get(name, [])
        if len(matches) > 1:
            raise RuntimeError(f'Multiple generated reference timelines named {name!r}; preserved without changes')
        if matches:
            assign(_id(matches[0].GetMediaPoolItem(), 'program reference media item'), BINS[4])
    return destinations, missing_program


def _required_bins(plan):
    return list(BINS) + [f'{BINS[2]}/Camera {camera}' for camera in
                         sorted({int(row['camera']) for row in plan.get('media', [])})]


def _report(items, folders, targets, missing_program, required, moved=0):
    bins = {}
    for path in required:
        folder = folders.get(path)
        if not folder:
            raise RuntimeError(f'Missing organized media bin: {path}')
        owned = sorted((uid for uid, destination in targets.items() if destination == path))
        for uid in owned:
            if items[uid]['folder'] != path:
                raise RuntimeError(f'Conversion item {items[uid]["item"].GetName()!r} is outside its expected bin {path}')
        bins[path] = dict(id=_id(folder, f'bin {path}'), item_ids=owned,
                          item_names=[items[uid]['item'].GetName() for uid in owned],
                          count=len(owned))
    return dict(bins=bins, moved_items=moved,
                missing_program_paths=missing_program,
                unknown_items_preserved=len(items) - len(targets))


def organize_project(project, plan):
    """Idempotently move this conversion's items into numbered media bins.

    Call after all media and reference timelines have been imported. Optional
    ``program_files`` supplies verified program paths absent from the inventory.
    No source file is touched and unknown media pool items stay in place.
    """
    pool = project.GetMediaPool()
    items, folders = _inventory(pool.GetRootFolder())
    targets, missing_program = _targets(project, plan, items)
    required = _required_bins(plan)
    # Resolve ownership and ambiguity before creating or moving anything.
    for path in required:
        if path in folders:
            continue
        parent, _, name = path.rpartition('/')
        folder = pool.AddSubFolder(folders[parent], name)
        if not folder or folder.GetName() != name:
            raise RuntimeError(f'Resolve could not create media bin {path}')
        folders[path] = folder
    groups = defaultdict(list)
    for uid, destination in targets.items():
        if items[uid]['folder'] != destination:
            groups[destination].append(items[uid]['item'])
    moved = 0
    for destination, clips in groups.items():
        if not pool.MoveClips(clips, folders[destination]):
            raise RuntimeError(f'Resolve could not move converted media into {destination}; rerun safely to finish organizing')
        moved += len(clips)
    after_items, after_folders = _inventory(pool.GetRootFolder())
    if set(after_items) != set(items):
        raise RuntimeError('Media pool item identities changed while organizing; no deletion was requested')
    for uid in set(items) - set(targets):
        if after_items[uid]['folder'] != items[uid]['folder']:
            raise RuntimeError('An unrelated media pool item changed bins unexpectedly')
    return _report(after_items, after_folders, targets, missing_program, required, moved)


def inspect_project_layout(project, plan):
    """Read-only validation of the expected bin membership, including after reopen."""
    items, folders = _inventory(project.GetMediaPool().GetRootFolder())
    targets, missing_program = _targets(project, plan, items)
    return _report(items, folders, targets, missing_program, _required_bins(plan))


def inspect_edit_session(project, plan, require_first_cut=False):
    """Read back the active finished edit without changing project or UI state.

    Current timeline identity is mandatory. Bin selection and playhead position
    are observations by default because these UI details may not survive export.
    ``require_first_cut`` also requires the exact first native multicam cut.
    ``frame`` is absolute only when the observed video interval disambiguates
    midnight; ``timecode_frame`` always contains the clock's frame-of-day.
    """
    edit = _edit(project, plan)
    identity = _id(edit, 'finished edit timeline')
    if _id(project.GetCurrentTimeline(), 'current timeline') != identity:
        raise RuntimeError('The finished edit is not the current timeline')
    timing = Timing.from_plan(plan)
    timecode = edit.GetCurrentTimecode()
    clock_frame = timing.frames(timecode)
    current = edit.GetCurrentVideoItem()
    media = current.GetMediaPoolItem() if current else None
    native = bool(media and media.GetClipProperty('Type') == 'Multicam')
    frame = None
    if current:
        start, end = current.GetStart(), current.GetEnd()
        candidate = clock_frame + ((start - clock_frame + timing.day - 1) // timing.day) * timing.day
        if start <= candidate < end and candidate + timing.day >= end:
            frame = candidate
    result = dict(timeline=edit.GetName(), timeline_id=identity,
                  frame=frame, timecode=timecode, timecode_frame=clock_frame,
                  native_multicam_at_playhead=native, first_cut_verified=False)
    pool = project.GetMediaPool()
    folder = pool.GetCurrentFolder()
    edit_bins = [f for f in (pool.GetRootFolder().GetSubFolderList() or [])
                 if f.GetName() == BINS[0]]
    result.update(bin=folder.GetName() if folder else None,
                  bin_id=_id(folder, 'current media bin') if folder else None,
                  selected_edit_bin=bool(folder and len(edit_bins) == 1
                                         and _id(folder, 'current media bin')
                                         == _id(edit_bins[0], 'finished edit bin')))
    if require_first_cut:
        cuts = [cut for cut in plan.get('cuts', [])
                if cut.get('angle') not in (None, 0) and cut['end'] > cut['start']]
        if not cuts:
            raise RuntimeError('The conversion has no actual multicam cut to inspect')
        first = min(cuts, key=lambda cut: cut['start'])
        names = plan['camera_names']
        camera_name = names.get(str(first['angle']), names.get(first['angle']))
        expected = (f'{plan["sessions"][first["session"]]["multicam_name"]}'
                    f' - {first["angle"]} {camera_name}')
        if (frame != first['start'] or not native
                or current.GetStart() != first['start'] or current.GetEnd() != first['end']
                or current.GetName() != expected):
            raise RuntimeError('The playhead is not on the expected first native multicam cut')
        result.update(first_cut_verified=True, angle=first['angle'])
    return result


def select_edit_session(resolve, project, plan):
    """Open the finished edit at its first actual multicam cut, with readback.

    The multicam viewer and timeline zoom are UI controls, outside this helper.
    """
    edit = _edit(project, plan)
    identity = _id(edit, 'finished edit timeline')
    cuts = [cut for cut in plan.get('cuts', [])
            if cut.get('angle') not in (None, 0) and cut['end'] > cut['start']]
    if not cuts:
        raise RuntimeError('The conversion has no actual multicam cut to open')
    first = min(cuts, key=lambda cut: cut['start'])
    timing = Timing.from_plan(plan)
    timecode = timing.timecode(first['start'])
    pool = project.GetMediaPool()
    _, folders = _inventory(pool.GetRootFolder())
    folder = folders.get(BINS[0])
    if not folder:
        raise RuntimeError('The finished edit bin is missing; organize the project before opening it')
    if not project.SetCurrentTimeline(edit):
        raise RuntimeError('Resolve could not open the finished cut timeline')
    if _id(project.GetCurrentTimeline(), 'current timeline') != identity:
        raise RuntimeError('Resolve opened a different timeline instead of the finished edit')
    if not resolve.OpenPage('edit') or resolve.GetCurrentPage() != 'edit':
        raise RuntimeError('Resolve could not switch to the Edit page')
    if not edit.SetCurrentTimecode(timecode):
        raise RuntimeError('Resolve could not position the playhead at the first multicam cut')
    actual_timecode = edit.GetCurrentTimecode()
    if timing.frames(actual_timecode) != first['start'] % timing.day:
        raise RuntimeError('Resolve playhead timecode differs from the first multicam cut')
    current = edit.GetCurrentVideoItem()
    session = plan['sessions'][first['session']]
    camera_names = plan['camera_names']
    camera_name = camera_names.get(str(first['angle']), camera_names.get(first['angle']))
    expected_name = f'{session["multicam_name"]} - {first["angle"]} {camera_name}'
    media = current.GetMediaPoolItem() if current else None
    if (not current or not media or media.GetClipProperty('Type') != 'Multicam'
            or current.GetStart() != first['start'] or current.GetEnd() != first['end']
            or current.GetName() != expected_name):
        raise RuntimeError('The playhead is not on the expected first native multicam cut')
    if not pool.SetCurrentFolder(folder):
        raise RuntimeError('Resolve could not select the finished edit bin')
    if _id(pool.GetCurrentFolder(), 'current media bin') != _id(folder, 'finished edit bin'):
        raise RuntimeError('Resolve selected a different media bin')
    if _id(project.GetCurrentTimeline(), 'current timeline') != identity:
        raise RuntimeError('Resolve changed the current timeline while preparing the Edit page')
    return dict(timeline=edit.GetName(), timeline_id=identity, page='edit',
                frame=first['start'], timecode=actual_timecode,
                angle=first['angle'], bin=BINS[0], bin_id=_id(folder, 'finished edit bin'),
                native_multicam_at_playhead=True)
