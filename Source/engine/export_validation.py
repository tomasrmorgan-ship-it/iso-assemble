"""Load the exact exported DRP for validation without reusing stale imports.

This helper establishes import provenance. The caller must still validate the
returned project's timelines, media and edit state on every invocation.
"""
import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path


SCHEMA = 1


def _digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Export verification requires a regular DRP file: {path}')
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        before = os.fstat(handle.fileno())
        while block := handle.read(1024 * 1024):
            digest.update(block)
        after = os.fstat(handle.fileno())
    current = path.stat()
    fields = lambda stat: (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    if not before.st_size:
        raise ValueError(f'The exported DRP is empty: {path}')
    if fields(before) != fields(after) or fields(after) != fields(current):
        raise ValueError('The exported DRP changed while it was being checked. Retry verification.')
    return digest.hexdigest()


def _write(path, state):
    if path.is_symlink():
        raise ValueError('Export verification state must not be a symbolic link.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         prefix='.' + path.name + '.', suffix='.tmp',
                                         dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(state, handle, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _state(path):
    if path.is_symlink():
        raise ValueError('Export verification state must not be a symbolic link.')
    if not path.exists():
        return dict(schema=SCHEMA, owner=uuid.uuid4().hex, records={})
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError('Export verification state cannot be read; choose a new output folder.') from error
    if not isinstance(state, dict):
        raise ValueError('Invalid export verification state; choose a new output folder.')
    # Previous releases recorded an imported name/ID without identifying bytes.
    # Retain that ownership history, but never count it as verification of a DRP.
    if 'schema' not in state and set(state) <= {'name', 'project_id'} and isinstance(state.get('name'), str):
        if 'project_id' in state and not isinstance(state['project_id'], str):
            raise ValueError('Invalid legacy export verification state.')
        return dict(schema=SCHEMA, owner=uuid.uuid4().hex, records={}, legacy=state)
    if (state.get('schema') != SCHEMA or
            not isinstance(state.get('owner'), str) or
            not re.fullmatch(r'[0-9a-f]{32}', state['owner']) or
            not isinstance(state.get('records'), dict)):
        raise ValueError('Export verification state has no valid ownership record; choose a new output folder.')
    return state


def load_export_for_verification(pm, target, checkfile, fingerprint):
    """Return ``(project, metadata)`` for an import of the current DRP bytes.

    Changed bytes get a new project. Existing names are reused only when this
    state file records their exact export, fingerprint and Resolve project ID.
    No projects are deleted, including legacy verification projects.
    """
    if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        raise ValueError('Export verification requires the full conversion fingerprint.')
    target = Path(target).absolute()
    if target.is_symlink():
        raise ValueError('The exported DRP must not be a symbolic link.')
    target = target.resolve()
    checkfile = Path(checkfile).absolute()
    if checkfile.is_symlink():
        raise ValueError('Export verification state must not be a symbolic link.')
    checkfile = checkfile.resolve()
    if checkfile == target:
        raise ValueError('Export verification state cannot replace the exported DRP.')
    digest = _digest(target)
    state = _state(checkfile)
    name = f'ISOAssemble_Verify_{fingerprint[:8]}_{digest[:8]}'
    expected = dict(name=name, fingerprint=fingerprint, export=str(target),
                    export_sha256=digest, owner=state['owner'])
    record = state['records'].get(name)
    if record is not None:
        if (not isinstance(record, dict) or
                any(record.get(key) != value for key, value in expected.items()) or
                not isinstance(record.get('project_id'), str) or not record['project_id']):
            raise RuntimeError('Verification project ownership or export identity differs; existing projects were preserved.')
    names = pm.GetProjectListInCurrentFolder()
    if names is None:
        raise RuntimeError('Could not list Resolve projects for safe export verification.')
    reused = name in names
    if reused and record is None:
        raise RuntimeError('Verification project name collision without ownership of these DRP bytes; existing project was preserved.')
    if not reused:
        if not pm.ImportProject(str(target), name):
            raise RuntimeError('Resolve could not reimport the exported project for verification.')
    project = pm.LoadProject(name)
    if not project:
        raise RuntimeError('Could not open the exported verification project; it was preserved.')
    project_id = project.GetUniqueId()
    if not isinstance(project_id, str) or not project_id:
        raise RuntimeError('Resolve did not return a verification project identity; project was preserved.')
    if reused and project_id != record['project_id']:
        raise RuntimeError('Verification project identity changed; existing project was preserved.')
    # A changed export during import must never produce a reusable cache entry.
    if _digest(target) != digest:
        raise RuntimeError('The exported DRP changed during verification import; no reusable verification state was recorded.')
    metadata = {**expected, 'project_id': project_id}
    state['records'][name] = metadata
    state['current'] = name
    _write(checkfile, state)
    return project, {**metadata, 'reused': reused}
