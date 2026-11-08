"""Account for Resolve auto-spanning only with exact verified program timing."""
from pathlib import Path


def _frames(value, label):
    try:
        frames = int(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError(f'Invalid {label} while checking imported program spans') from error
    if isinstance(value, bool) or frames <= 0 or str(frames) != str(value):
        raise RuntimeError(f'Invalid {label} while checking imported program spans')
    return frames


def verified_program_spans(programs, pool, timing):
    """Return missing program paths proven covered by an imported source span.

    ``programs`` contains preflight-verified path/start/frames rows; ``pool`` maps
    source paths to native media-pool items. Only program files are considered.
    Callers may excuse ``covered_missing_paths`` from their missing-media guard;
    all audio ISO paths and ``unresolved_program_paths`` remain mandatory.
    """
    rows = sorted(programs, key=lambda row: (row['start'], row['path']))
    paths = [row['path'] for row in rows]
    if len(set(paths)) != len(paths):
        raise RuntimeError('Duplicate verified program paths prevent safe span validation')
    missing = {path for path in paths if path not in pool}
    covered = set(); spans = []
    for index, row in enumerate(rows):
        media = pool.get(row['path'])
        if media is None:
            continue
        count = _frames(media.GetClipProperty('Frames'), 'native frame count')
        first_count = _frames(row['frames'], 'preflight frame count')
        if count == first_count:
            continue
        if count < first_count:
            raise RuntimeError(f'Imported program is shorter than its verified physical file: {row["path"]}')
        native_path = media.GetClipProperty('File Path')
        if not native_path or Path(native_path) != Path(row['path']):
            raise RuntimeError('Imported program span source path does not match its verified first file')
        timecode = media.GetClipProperty('Start TC')
        try:
            native_start = timing.frames(timecode)
        except (TypeError, ValueError) as error:
            raise RuntimeError(f'Imported program span has no valid source start timecode: {row["path"]}') from error
        if native_start != row['start'] % timing.day:
            raise RuntimeError(f'Imported program span starts at a different timecode: {row["path"]}')
        end = row['start'] + count; cursor = row['start']; members = []
        for candidate in rows[index:]:
            if cursor == end:
                break
            duration = _frames(candidate['frames'], 'preflight frame count')
            if candidate['start'] != cursor or cursor + duration > end:
                raise RuntimeError(f'Imported program span cannot be tiled exactly by verified contiguous files: {row["path"]}')
            members.append(candidate['path']); cursor += duration
        if cursor != end or len(members) < 2:
            raise RuntimeError(f'Imported program span extends beyond its verified physical files: {row["path"]}')
        covered.update(path for path in members if path in missing)
        spans.append(dict(source_path=row['path'], start=row['start'], end=end,
                          frames=count, native_start_timecode=timecode, files=members))
    return dict(covered_missing_paths=[path for path in paths if path in covered],
                unresolved_program_paths=[path for path in paths if path in missing-covered],
                spans=spans)
