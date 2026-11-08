"""Validate independent primary audio in the actual Resolve edit timeline."""
import json
import os
from fractions import Fraction


def _path(value):
    return os.path.normpath(os.path.abspath(str(value)))


def verify_primary_audio(timeline, plan):
    """Require exactly the planned physical audio files on one audible A1.

    Optional playback/mapping APIs are inspected when the installed Resolve
    exposes them. This checks timeline structure and channel assignments, not
    the recorded signal's loudness or the user's monitoring device.
    """
    choice = plan.get('audio', {})
    label = choice.get('label') or choice.get('selected') or 'selected primary audio'
    target = plan.get('name', 'Project') + '_Edit'

    def fail(message):
        raise RuntimeError(f'Primary audio {label!r} in {target!r}: {message}')

    rows = plan.get('audio_assembly')
    if not isinstance(rows, list) or not rows:
        fail('the verified audio assembly plan is missing; create a fresh conversion.')
    expected = []
    for row in rows:
        try:
            start, end = int(row['start']), int(row['end'])
            source = Fraction(str(row['source_start']))
            channels, sample_rate = int(row['channels']), int(row['sample_rate'])
            path = _path(row['path'])
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
            fail(f'invalid audio assembly row: {error}')
        if (start != row['start'] or end != row['end'] or end <= start or
                source.denominator != 1 or source < 0 or channels != 2 or sample_rate != 48000):
            fail('the audio assembly has invalid frame boundaries, source offset, or stereo/48 kHz format.')
        expected.append(dict(path=path, start=start, end=end, source_start=int(source)))
    expected.sort(key=lambda row: (row['start'], row['end'], row['path']))
    if len({row['path'] for row in expected}) != len(expected):
        fail('the same physical source audio file appears more than once in the assembly plan.')
    selected_paths = {_path(row['path']) for row in choice.get('files', [])}
    if selected_paths and {row['path'] for row in expected} != selected_paths:
        fail('the planned source files differ from the selected primary audio.')
    sessions = plan.get('sessions', [])
    if not sessions:
        fail('recording-session coverage is missing from the plan.')
    consumed = 0
    for session in sessions:
        cursor = session['start']
        for row in expected:
            if session['start'] <= row['start'] < session['end']:
                if row['start'] != cursor or row['end'] > session['end']:
                    fail('the planned audio has a gap, overlap, or crosses a recording boundary.')
                cursor = row['end']; consumed += 1
        if cursor != session['end']:
            fail('the planned audio does not cover the complete recording session.')
    if consumed != len(expected):
        fail('the planned audio contains clips outside the recording sessions.')
    tracks = timeline.GetTrackCount('audio')
    if tracks != 1:
        fail(f'expected one independent stereo audio track A1, found {tracks}.')
    actual = timeline.GetItemListInTrack('audio', 1) or []
    if not actual:
        fail('audio track A1 is empty; the selected sound was not added beneath the multicam edit.')
    if len(actual) != len(expected):
        fail(f'A1 has {len(actual)} clips; expected {len(expected)} selected physical audio files.')
    actual = sorted(actual, key=lambda item: (item.GetStart(), item.GetEnd()))
    track_check = getattr(timeline, 'GetIsTrackEnabled', None)
    track_enabled_checked = callable(track_check)
    if track_enabled_checked and track_check('audio', 1) is not True:
        fail('audio track A1 is disabled.')
    mapping_checks = clip_enabled_checks = linked_items_checked = 0
    mappings = []; linked_item_counts = []
    for index, (item, row) in enumerate(zip(actual, expected), 1):
        media = item.GetMediaPoolItem()
        path = media.GetClipProperty('File Path') if media else None
        if not path or _path(path) != row['path']:
            fail(f'A1 clip {index} uses a different source file than {row["path"]!r}.')
        if (item.GetStart(), item.GetEnd()) != (row['start'], row['end']):
            fail(f'A1 clip {index} does not match its planned start/end frames.')
        if item.GetLeftOffset() != row['source_start']:
            fail(f'A1 clip {index} starts at the wrong position inside its source audio.')
        enabled = getattr(item, 'GetClipEnabled', None)
        if callable(enabled):
            clip_enabled_checks += 1
            if enabled() is not True:
                fail(f'A1 clip {index} is disabled.')
        mapping_api = getattr(item, 'GetSourceAudioChannelMapping', None)
        if callable(mapping_api):
            mapping_checks += 1
            try:
                mapping = json.loads(mapping_api())
            except (TypeError, ValueError) as error:
                fail(f'A1 clip {index} returned invalid audio channel mapping: {error}')
            tracks = mapping.get('track_mapping') if isinstance(mapping, dict) else None
            track = tracks.get('1') if isinstance(tracks, dict) else None
            embedded = mapping.get('embedded_audio_channels') if isinstance(mapping, dict) else None
            if (type(embedded) is not int or embedded < 2 or
                    not isinstance(track, dict) or set(tracks) != {'1'} or
                    track.get('channel_idx') != [1, 2] or track.get('mute') is not False or
                    track.get('type') != 'stereo'):
                fail(f'A1 clip {index} must map unmuted stereo source channels 1 and 2; '
                     'a missing/zero channel or different mapping was found.')
            mappings.append(mapping)
        linked_api = getattr(item, 'GetLinkedItems', None)
        if callable(linked_api):
            linked_items_checked += 1
            linked_item_counts.append(len(linked_api() or []))
    return dict(count=len(actual), clips_verified=len(actual), coverage=[[row['start'], row['end']] for row in expected],
                source_paths=[row['path'] for row in expected],
                source_offsets=[row['source_start'] for row in expected],
                track_enabled_checked=track_enabled_checked,
                clip_enabled_checks=clip_enabled_checks, mapping_checks=mapping_checks,
                channel_mappings=mappings, linked_items_checked=linked_items_checked,
                linked_item_counts=linked_item_counts,
                selected_audio=choice.get('selected'), selected_audio_label=label,
                timeline=target)
