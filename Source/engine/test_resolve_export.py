"""Presentation upgrades preserve prior DRP bytes and remain safely retryable."""
import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import resolve_project as module
from timing import Timing


class Media:
    def __init__(self, path): self.path = path
    def GetClipProperty(self, key): return {'File Path': self.path, 'Frames': '60'}[key]


class Audio:
    def __init__(self, media): self.media = media
    def GetStart(self): return 0
    def GetEnd(self): return 60
    def GetMediaPoolItem(self): return self.media


class Timeline:
    def __init__(self, name, media): self.name, self.media = name, media
    def GetName(self): return self.name
    def GetItemListInTrack(self, kind, track): return [Audio(self.media)]
    def SetTrackName(self, kind, track, name): return True


class Pool:
    def __init__(self): self.imports = []; self.on_import = None
    def ImportMedia(self, paths):
        self.imports.append(list(paths))
        return self.on_import(paths) if self.on_import else []
    def GetRootFolder(self): return object()


class Project:
    def __init__(self, media):
        self.timelines = [Timeline('Fixture_Edit', media), Timeline('Fixture_Live_Program_Reference', media)]
        self.pool = Pool()
    def GetUniqueId(self): return 'owned-project-id'
    def GetMediaPool(self): return self.pool
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]
    def SetCurrentTimeline(self, timeline): return True


class Manager:
    def __init__(self, project):
        self.project = project; self.fail_save = self.fail_export = False
        self.export_bytes = b'new valid-looking DRP bytes'; self.exports = []
    def GetProjectListInCurrentFolder(self): return ['Fixture']
    def LoadProject(self, name): return self.project
    def SaveProject(self): return not self.fail_save
    def ExportProject(self, name, path):
        self.exports.append(path)
        if self.fail_export: return False
        Path(path).write_bytes(self.export_bytes)
        return True


class Resolve:
    def __init__(self, manager): self.manager = manager
    def GetProjectManager(self): return self.manager
    def GetVersionString(self): return '21.2.0.6'


class ResolveExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.manifest = self.root / 'conversion.json'; self.target = self.root / 'Fixture.drp'
        self.statefile = self.root / 'resolve-state.json'
        self.original = self.root / 'Original.drp'; self.original.write_bytes(b'original ATEM input')
        self.old = b'previously verified DRP bytes'; self.target.write_bytes(self.old)
        self.old_hash = hashlib.sha256(self.old).hexdigest()
        self.media = Media(str(self.root / 'Program.mp4'))
        self.plan = dict(name='Fixture', input=str(self.original), fingerprint='f' * 64,
                         timing=Timing().data(), media_root=str(self.root),
                         sessions=[dict(start=0, end=60)], audio_inventory=[])
        self.manifest.write_text(json.dumps(self.plan))
        self.state = dict(fingerprint=self.plan['fingerprint'], project_id='owned-project-id',
                          name='Fixture', complete=True, export=str(self.target),
                          export_sha256=self.old_hash, presentation_revision=0)
        self.statefile.write_text(json.dumps(self.state))
        self.pm = Manager(Project(self.media)); self.resolve = Resolve(self.pm)
        self.pool_media = [self.media]
        self.patches = ExitStack()
        patches = dict(connect=lambda: self.resolve, validate=lambda *args: 2,
                       apply_transitions=lambda *args: 0,
                       programs=lambda *args: [dict(path=self.media.path, start=0, frames=60)],
                       clips=lambda *args: iter(self.pool_media),
                       organize_project=lambda *args: {'bins': {}},
                       select_edit_session=lambda *args: {'timeline': 'Fixture_Edit'})
        for name, replacement in patches.items():
            self.patches.enter_context(patch.object(module, name, replacement))
    def tearDown(self): self.patches.close(); self.temp.cleanup()
    def apply(self):
        with redirect_stdout(StringIO()): module.apply(self.manifest)
    @property
    def backup(self): return self.root / ('Fixture.before-edit-layout-' + self.old_hash[:12] + '.drp')
    @property
    def pending(self): return self.root / 'Fixture.layout-update.drp'
    def assert_original_preserved(self): self.assertEqual(self.original.read_bytes(), b'original ATEM input')
    def test_upgrade_retains_previous_bytes_and_current_revision_rerun_does_not_export(self):
        self.apply()
        self.assertEqual(self.backup.read_bytes(), self.old)
        self.assertEqual(self.target.read_bytes(), self.pm.export_bytes)
        state = json.loads(self.statefile.read_text())
        self.assertTrue(state['complete'])
        self.assertEqual(state['presentation_revision'], module.PRESENTATION_REVISION)
        self.assertEqual(state['export_sha256'], hashlib.sha256(self.pm.export_bytes).hexdigest())
        self.apply(); self.assertEqual(len(self.pm.exports), 1)
        self.assert_original_preserved()
    def test_old_version_hash_from_validation_report_allows_owned_upgrade(self):
        self.state.pop('export_sha256'); self.statefile.write_text(json.dumps(self.state))
        (self.root / 'validation.json').write_text(json.dumps(dict(export=str(self.target), export_sha256=self.old_hash)))
        self.apply(); self.assertEqual(self.backup.read_bytes(), self.old)
        self.assertEqual(self.target.read_bytes(), self.pm.export_bytes)
    def test_failed_save_preserves_prior_export_ownership_for_retry(self):
        self.pm.fail_save = True
        with self.assertRaisesRegex(RuntimeError, 'save failed'): self.apply()
        self.assertEqual(self.target.read_bytes(), self.old)
        self.pm.fail_save = False; self.apply()
        self.assertEqual(self.backup.read_bytes(), self.old)
        self.assertEqual(self.target.read_bytes(), self.pm.export_bytes)
    def test_failed_export_preserves_prior_export_ownership_for_retry(self):
        self.pm.fail_export = True
        with self.assertRaisesRegex(RuntimeError, 'export failed'): self.apply()
        self.assertEqual(self.target.read_bytes(), self.old)
        self.pm.fail_export = False; self.apply()
        self.assertEqual(self.backup.read_bytes(), self.old)
        self.assertEqual(self.target.read_bytes(), self.pm.export_bytes)
    def test_unverified_or_tampered_existing_export_is_never_replaced(self):
        self.target.write_bytes(b'user replacement')
        with self.assertRaisesRegex(RuntimeError, 'differs from the verified export'): self.apply()
        self.assertEqual(self.target.read_bytes(), b'user replacement')
        self.assertEqual(self.pm.exports, []); self.assert_original_preserved()
    def test_backup_collision_preserves_both_existing_files(self):
        self.backup.write_bytes(b'unrelated backup')
        with self.assertRaisesRegex(RuntimeError, 'backup collision'): self.apply()
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(self.backup.read_bytes(), b'unrelated backup')
        self.assertEqual(self.pm.exports, [])
    def test_empty_successful_export_does_not_replace_last_good_export(self):
        self.pm.export_bytes = b''
        with self.assertRaises(RuntimeError): self.apply()
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(self.backup.read_bytes(), self.old)
    def test_dangling_pending_symlink_is_rejected_before_export(self):
        outside = self.root / 'untouched-outside.drp'; self.pending.symlink_to(outside)
        with self.assertRaises(RuntimeError): self.apply()
        self.assertFalse(outside.exists()); self.assertEqual(self.pm.exports, [])
        self.assertEqual(self.target.read_bytes(), self.old)
    def test_backup_symlink_is_rejected_even_when_it_points_to_matching_bytes(self):
        outside = self.root / 'outside-old.drp'; outside.write_bytes(self.old); self.backup.symlink_to(outside)
        with self.assertRaises(RuntimeError): self.apply()
        self.assertEqual(outside.read_bytes(), self.old); self.assertEqual(self.pm.exports, [])
        self.assertEqual(self.target.read_bytes(), self.old)
    def test_known_program_and_audio_in_other_bins_are_not_imported_again(self):
        wav = str(self.root / 'Existing.wav')
        self.plan['audio_inventory'] = [dict(path=wav, kind='audio_iso')]
        self.manifest.write_text(json.dumps(self.plan)); self.pool_media.append(Media(wav))
        self.apply(); self.apply()
        self.assertEqual(self.pm.project.pool.imports, [])
    def test_only_missing_audio_path_is_imported_once_and_read_back(self):
        wav = str(self.root / 'Missing.wav')
        self.plan['audio_inventory'] = [dict(path=wav, kind='audio_iso')] * 2
        self.manifest.write_text(json.dumps(self.plan))
        def imported(paths):
            media = [Media(path) for path in paths]; self.pool_media.extend(media); return media
        self.pm.project.pool.on_import = imported
        self.apply(); self.apply()
        self.assertEqual(self.pm.project.pool.imports, [[wav]])
        self.assertEqual([item.path for item in self.pool_media], [self.media.path, wav])
    def test_missing_import_readback_stops_without_exporting(self):
        wav = str(self.root / 'Missing.wav')
        self.plan['audio_inventory'] = [dict(path=wav, kind='audio_iso')]
        self.manifest.write_text(json.dumps(self.plan))
        with self.assertRaisesRegex(RuntimeError, 'did not import.*Missing.wav'): self.apply()
        self.assertEqual(self.pm.project.pool.imports, [[wav]])
        self.assertEqual(self.pm.exports, []); self.assertEqual(self.target.read_bytes(), self.old)


if __name__ == '__main__': unittest.main()
