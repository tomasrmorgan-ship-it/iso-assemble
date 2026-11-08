"""Embed verified primary audio into a native multicam FCPXML cut timeline.

This only assembles already inspected sources. It does not probe, copy, trim,
mix or transcode media. Each selected physical file is used once in full.
"""
import copy
from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET

from timing import Timing


def _integer(value, label):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be an integer')
    try:
        number = Fraction(value)
    except (TypeError, ValueError, ZeroDivisionError) as error:
        raise ValueError(f'{label} must be an integer') from error
    if number.denominator != 1:
        raise ValueError(f'{label} must be an integer')
    return int(number)


def _xml_frames(value, timing, label):
    if not isinstance(value, str) or not value.endswith('s'):
        raise ValueError(f'Missing or invalid FCPXML {label}')
    try:
        return _integer(Fraction(value[:-1]) * timing.fps, f'FCPXML {label}')
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f'Invalid FCPXML {label}: {value!r}') from error


def _file_path(value):
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ValueError('Primary audio requires an absolute, verified media path')
    return str(Path(value))


def _assembly(plan, chosen):
    sessions = plan.get('sessions', [])
    if not sessions:
        raise ValueError('Primary audio has no recording sessions to cover')
    bounds = []
    for index, session in enumerate(sessions):
        start = _integer(session.get('start'), 'Session start')
        end = _integer(session.get('end'), 'Session end')
        if start < 0 or end <= start or (bounds and start < bounds[-1][1]):
            raise ValueError('Recording sessions are invalid or overlap')
        bounds.append((start, end))
    if (bounds[0][0], bounds[-1][1]) != (plan['origin'], plan['end']):
        raise ValueError('Recording sessions differ from the edit timeline range')
    inventory = {row['path']: row for row in plan.get('audio_inventory', []) if row.get('path')}
    rows, seen = [], set()
    for source in chosen.get('files', []):
        path = _file_path(source.get('path'))
        if path in seen:
            raise ValueError(f'Primary audio file is listed more than once: {path}')
        seen.add(path)
        start = _integer(source.get('start'), 'Audio start')
        frames = _integer(source.get('frames'), 'Audio duration')
        end = _integer(source.get('end', start + frames), 'Audio end')
        if frames <= 0 or end != start + frames:
            raise ValueError(f'Primary audio has inconsistent frame coverage: {path}')
        verified = inventory.get(path, {})
        channels = _integer(source.get('channels', verified.get('channels')), 'Audio channels')
        rate = _integer(source.get('sample_rate', verified.get('sample_rate')), 'Audio sample rate')
        if channels != 2 or rate != 48000:
            raise ValueError(f'Primary audio must be verified 48 kHz stereo: {path}')
        containing = [index for index, (a, b) in enumerate(bounds) if a <= start < end <= b]
        if len(containing) != 1:
            raise ValueError(f'Primary audio falls outside a recording session or crosses a recording gap: {path}')
        rows.append(dict(path=path, start=start, end=end, frames=frames,
                         source_start=0, channels=channels, sample_rate=rate,
                         session=containing[0]))
    rows.sort(key=lambda row: (row['start'], row['end'], row['path']))
    for index, (start, end) in enumerate(bounds):
        cursor = start
        for row in (row for row in rows if row['session'] == index):
            if row['start'] != cursor:
                raise ValueError(f'Primary audio has a gap or overlap in recording session {index + 1}')
            cursor = row['end']
        if cursor != end:
            raise ValueError(f'Primary audio does not completely cover recording session {index + 1}')
    return rows


def _asset_start(row, inventory, timing, program):
    """Resolve source clock, separate from the verified timeline placement.

    BWF time_reference is a sample clock. The tested FCPXML uses its floored
    frame on both asset and audio component to address source offset zero.
    Resolve's displayed Start TC may round differently. Declaring zero for a
    nonzero BWF clock can leave valid WAV audio offline; a contradictory source
    clock never shifts the independently verified edit position.
    """
    if program:
        return row['start'] % timing.day
    reference = inventory.get(row['path'], {}).get('tags', {}).get('time_reference')
    if reference is None:
        return 0
    if isinstance(reference, bool) or not isinstance(reference, (str, int)):
        raise ValueError(f'BWF time_reference must be a nonnegative integer sample count: {row["path"]}')
    if isinstance(reference, str) and (not reference or not reference.isascii() or not reference.isdigit()):
        raise ValueError(f'BWF time_reference must be a nonnegative integer sample count: {row["path"]}')
    samples = int(reference)
    if samples < 0:
        raise ValueError(f'BWF time_reference must be a nonnegative integer sample count: {row["path"]}')
    source_frame = Fraction(samples, row['sample_rate']) * timing.fps
    return (source_frame.numerator // source_frame.denominator) % timing.day


def add_primary_audio(xml, plan, chosen):
    """Return new ``(xml_bytes, plan)`` containing one independent stereo mix.

    ``chosen`` is a verified audio-catalog selection with ``id`` (or ``selected``)
    and full-file ``files`` entries. Sources must tile every recording session
    exactly; real gaps remain silent. Existing embedded audio is rejected so
    retries cannot duplicate a mix or disguise a partial insertion.

    Resolve's tested FCPXML import uses connected ``clip/audio`` components.
    Deliberately omit ``srcCh``: Resolve 21.1 imported explicit ``1,2`` as a
    silent first channel, while default mapping preserves stereo channels 1/2.
    """
    if plan.get('audio_embedded') or plan.get('audio_assembly'):
        raise ValueError('Primary audio is already embedded; rebuild from the original multicam XML')
    if not isinstance(chosen, dict) or not chosen.get('id', chosen.get('selected')):
        raise ValueError('Select a verified primary audio source before assembling the timeline')
    timing = Timing.from_plan(plan)
    rows = _assembly(plan, chosen)
    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, TypeError) as error:
        raise ValueError('Cannot embed audio in invalid FCPXML') from error
    resources = root.find('resources')
    sequences = root.findall('./library/event/project/sequence')
    if root.tag != 'fcpxml' or resources is None or len(sequences) != 1:
        raise ValueError('Expected one generated multicam edit sequence')
    sequence = sequences[0]
    spine = sequence.find('spine')
    if spine is None:
        raise ValueError('The multicam edit has no primary spine')
    if (_xml_frames(sequence.get('tcStart'), timing, 'sequence start') != plan['origin']
            or _xml_frames(sequence.get('duration'), timing, 'sequence duration') != plan['end'] - plan['origin']):
        raise ValueError('FCPXML timeline timing differs from the verified plan')
    format_id = sequence.get('format')
    formats = [node for node in resources.findall('format') if node.get('id') == format_id]
    if len(formats) != 1 or _xml_frames(formats[0].get('frameDuration'), timing, 'frame duration') != 1:
        raise ValueError('FCPXML format differs from the verified audio timing')
    ids = [node.get('id') for node in root.iter() if node.get('id')]
    if len(ids) != len(set(ids)):
        raise ValueError('FCPXML has duplicate resource identities')
    used_ids = set(ids)
    anchors = []
    cursor = plan['origin']
    for node in spine:
        if node.tag not in ('mc-clip', 'gap'):
            raise ValueError('The edit already contains audio or unsupported primary-spine content')
        if any(child.tag != 'mc-source' for child in node):
            raise ValueError('The edit already contains connected content; refusing duplicate or partial audio insertion')
        if node.tag == 'mc-clip' and (node.get('srcEnable') != 'video'
                or any(child.get('srcEnable') != 'video' for child in node)):
            raise ValueError('Multicam camera audio must be disabled before adding the primary mix')
        start = _xml_frames(node.get('offset'), timing, 'clip offset')
        source_start = _xml_frames(node.get('start'), timing, 'clip source start')
        duration = _xml_frames(node.get('duration'), timing, 'clip duration')
        if start != cursor or duration <= 0:
            raise ValueError('FCPXML spine has a gap, overlap or nonpositive clip; cannot anchor primary audio safely')
        anchors.append((start, start + duration, source_start, node))
        cursor = start + duration
    if cursor != plan['end']:
        raise ValueError('FCPXML spine does not cover the verified edit range')
    if [(a, b) for a, b, _, _ in anchors] != [(cut['start'], cut['end']) for cut in plan.get('cuts', [])]:
        raise ValueError('FCPXML cut positions differ from the verified plan')
    prepared = []
    program = chosen.get('id', chosen.get('selected')) == 'program'
    inventory = {row['path']: row for row in plan.get('audio_inventory', []) if row.get('path')}
    for index, row in enumerate(rows):
        matches = [(a, source, node) for a, b, source, node in anchors if a <= row['start'] < b]
        if len(matches) != 1:
            raise ValueError(f'No unique timeline anchor for primary audio: {row["path"]}')
        parent_offset, parent_start, parent = matches[0]
        asset_id = f'primary_audio_{index}'
        while asset_id in used_ids:
            asset_id += '_'
        used_ids.add(asset_id)
        asset_start = _asset_start(row, inventory, timing, program)
        prepared.append((row, parent, parent_start + row['start'] - parent_offset,
                         asset_id, asset_start))
    # All checks finish before constructing any audio elements. Caller inputs
    # remain unchanged even if validation fails.
    for row, parent, offset, asset_id, asset_start in prepared:
        time = timing.xml_time
        name = Path(row['path']).name
        ET.SubElement(resources, 'asset', dict(id=asset_id, name=name,
                      src=Path(row['path']).as_uri(), start=time(asset_start),
                      duration=time(row['frames']), hasVideo='1' if program else '0',
                      hasAudio='1', audioSources='1', audioChannels='2',
                      audioRate='48000', format=format_id))
        clip = ET.SubElement(parent, 'clip', dict(name=name, lane='-1',
                             offset=time(offset), start=time(asset_start),
                             duration=time(row['frames']), format=format_id))
        ET.SubElement(clip, 'audio', dict(ref=asset_id, offset=time(asset_start),
                      start=time(asset_start), duration=time(row['frames']), role='dialogue'))
    result = copy.deepcopy(plan)
    result.update(audio_assembly=rows, audio_embedded=True)
    ET.indent(root)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True), result
