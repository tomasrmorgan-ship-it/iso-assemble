"""Allocate an isolated Resolve conversion without reading prior run state."""
import json
import re
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path


def _safe_label(name):
    label = re.sub(r'[^\w .-]+', '-', unicodedata.normalize('NFC', name))
    label = label.strip(' .-') or 'Project'
    # Leave room for the date/token suffix under common filesystem name limits.
    return label.encode('utf-8')[:120].decode('utf-8', errors='ignore').rstrip(' .-') or 'Project'


def allocate_fresh_run(scan_output, requested_name, existing_project_names):
    """Return ``(new_output_path, new_project_name)`` for this Create action.

    ``existing_project_names`` is a fresh project-manager inventory. Allocation
    never loads projects or reads old conversion, compatibility or export state.
    Resolve's eventual CreateProject must still reject a concurrent name race.
    """
    if (not isinstance(requested_name, str) or not requested_name.strip() or
            requested_name in ('.', '..') or any(c in requested_name for c in '/\\') or
            any(unicodedata.category(c) == 'Cc' for c in requested_name)):
        raise ValueError('Enter a project name without path separators or control characters.')
    if existing_project_names is None or isinstance(existing_project_names, str):
        raise ValueError('Could not read existing Resolve project names for a fresh conversion.')
    try:
        existing_project_names = list(existing_project_names)
    except TypeError as error:
        raise ValueError('Could not read existing Resolve project names for a fresh conversion.') from error
    if not all(isinstance(name, str) for name in existing_project_names):
        raise ValueError('Could not read existing Resolve project names for a fresh conversion.')
    existing = {name.casefold() for name in existing_project_names}
    scan_output = Path(scan_output).resolve()
    if not scan_output.is_dir():
        raise ValueError('Scan the recording into an existing results folder before creating a project.')
    parent = scan_output / 'Projects'
    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
        raise ValueError('The Projects output path is occupied by another file or link. Choose another results folder.')
    parent.mkdir(exist_ok=True)
    label = _safe_label(requested_name)
    now = datetime.now().astimezone()
    folder_time = now.strftime('%Y-%m-%d %H.%M.%S')
    project_time = now.strftime('%Y%m%d_%H%M%S')
    for _ in range(64):
        token = uuid.uuid4().hex[:6]
        name = (requested_name if requested_name.casefold() not in existing
                else f'{requested_name}_{project_time}_{token}')
        if name.casefold() in existing:
            continue
        out = parent / f'{label} {folder_time} {token}'
        try:
            out.mkdir(exist_ok=False)
        except FileExistsError:
            continue  # Files and dangling links are collisions too.
        report = dict(schema=1, requested_name=requested_name, project_name=name,
                      scan_output=str(scan_output), output=str(out),
                      created_at=now.isoformat(), run_id=token, fresh_run=True)
        with (out / 'run.json').open('x', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2)
            handle.write('\n')
        return out, name
    raise RuntimeError('Could not allocate a unique project output. Retry Create Project; existing files were preserved.')


def cleanup_test_projects(pm, owned_name_id_map, keep_name):
    """Remove only this run's known test project identities and reopen its edit.

    Cleanup failures are reported without deleting unowned projects. Failure to
    restore the finished editing project is an error, not a successful cleanup.
    """
    if not isinstance(owned_name_id_map, dict):
        raise ValueError('Test project cleanup requires recorded project identities.')
    keep = pm.LoadProject(keep_name)
    keep_id = keep.GetUniqueId() if keep else None
    if not keep_id:
        raise RuntimeError('Could not open the finished project before cleaning up temporary tests; no projects were deleted.')
    removed, warnings = [], []
    try:
        for name, expected_id in owned_name_id_map.items():
            if name == keep_name:
                continue
            if not isinstance(name, str) or not isinstance(expected_id, str) or not expected_id:
                warnings.append(f'Temporary project {name!r} has no valid ownership ID and was preserved.')
                continue
            try:
                names = pm.GetProjectListInCurrentFolder()
                if names is None:
                    raise RuntimeError('Resolve could not list existing projects')
                if name not in names:
                    continue
                project = pm.LoadProject(name)
                if not project or project.GetUniqueId() != expected_id:
                    warnings.append(f'Temporary project {name!r} has a different identity and was preserved.')
                    continue
                if not pm.CloseProject(project):
                    warnings.append(f'Temporary project {name!r} could not be closed and was preserved.')
                    continue
                if not pm.DeleteProject(name):
                    warnings.append(f'Temporary project {name!r} could not be deleted and was preserved.')
                    continue
                removed.append(name)
            except Exception as error:
                warnings.append(f'Temporary project {name!r} was not cleaned up: {error}')
    finally:
        restored = pm.LoadProject(keep_name)
        if not restored or restored.GetUniqueId() != keep_id:
            raise RuntimeError('Could not return to the finished editing project after cleaning up temporary tests. '
                               'Open the finished project in Resolve; your project export is preserved.')
    return dict(removed=removed, warnings=warnings)
