"""Every Create receives a new folder and cannot inherit old project identities."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fresh_run import allocate_fresh_run, cleanup_test_projects


class FixedClock:
    @classmethod
    def now(cls): return datetime(2026, 11, 7, 12, 34, 56)


class FreshRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
    def tearDown(self): self.temp.cleanup()
    def test_new_output_has_requested_name_report_and_no_cached_state(self):
        original = self.root / 'Original.drp'; original.write_bytes(b'original')
        (self.root / 'resolve-state.json').write_text('{obsolete invalid state')
        (self.root / 'conversion.json').write_text('{old conversion')
        out, name = allocate_fresh_run(self.root, 'Camera Edit', [])
        self.assertEqual(name, 'Camera Edit'); self.assertEqual(out.parent, self.root / 'Projects')
        self.assertRegex(out.name, r'^Camera Edit \d{4}-\d\d-\d\d \d\d\.\d\d\.\d\d [0-9a-f]{6}$')
        report = json.loads((out / 'run.json').read_text())
        self.assertEqual(report['requested_name'], 'Camera Edit'); self.assertEqual(report['project_name'], name)
        self.assertTrue(report['fresh_run']); self.assertEqual(set(p.name for p in out.iterdir()), {'run.json'})
        self.assertEqual(original.read_bytes(), b'original')
        self.assertEqual((self.root / 'resolve-state.json').read_text(), '{obsolete invalid state')
    def test_repeated_create_is_always_a_new_directory(self):
        first, _ = allocate_fresh_run(self.root, 'Camera Edit', [])
        (first / 'resolve-state.json').write_text('old identity')
        second, name = allocate_fresh_run(self.root, 'Camera Edit', ['Camera Edit'])
        self.assertNotEqual(first, second); self.assertNotEqual(name, 'Camera Edit')
        self.assertRegex(name, r'^Camera Edit_\d{8}_\d{6}_[0-9a-f]{6}$')
        self.assertFalse((second / 'resolve-state.json').exists())
        self.assertEqual((first / 'resolve-state.json').read_text(), 'old identity')
    def test_project_name_collision_retries_with_a_new_token(self):
        tokens = [SimpleNamespace(hex='aaaaaa' + '0' * 26), SimpleNamespace(hex='bbbbbb' + '0' * 26)]
        with patch('fresh_run.datetime', FixedClock), patch('fresh_run.uuid.uuid4', side_effect=tokens):
            out, name = allocate_fresh_run(self.root, 'Edit', ['Edit', 'Edit_20261107_123456_aaaaaa'])
        self.assertEqual(name, 'Edit_20261107_123456_bbbbbb'); self.assertTrue(out.name.endswith('bbbbbb'))
    def test_folder_collision_preserves_existing_contents_and_retries(self):
        parent = self.root / 'Projects'; parent.mkdir()
        occupied = parent / 'Edit 2026-11-07 12.34.56 aaaaaa'; occupied.mkdir()
        (occupied / 'keep.txt').write_text('keep')
        tokens = [SimpleNamespace(hex='aaaaaa' + '0' * 26), SimpleNamespace(hex='bbbbbb' + '0' * 26)]
        with patch('fresh_run.datetime', FixedClock), patch('fresh_run.uuid.uuid4', side_effect=tokens):
            out, _ = allocate_fresh_run(self.root, 'Edit', [])
        self.assertNotEqual(out, occupied); self.assertEqual((occupied / 'keep.txt').read_text(), 'keep')
    def test_projects_symlink_is_rejected_without_writing_outside(self):
        outside = self.root / 'Elsewhere'; outside.mkdir(); (self.root / 'Projects').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'file or link'): allocate_fresh_run(self.root, 'Edit', [])
        self.assertEqual(list(outside.iterdir()), [])
    def test_requested_name_cannot_escape_and_unicode_folder_label_is_bounded(self):
        for name in ('../Original', 'a/b', 'a\\b', '', '..', 'A\nB'):
            with self.subTest(name=name), self.assertRaises(ValueError): allocate_fresh_run(self.root, name, [])
        name = 'Camera: ' + '映像' * 100
        out, project_name = allocate_fresh_run(self.root, name, [])
        self.assertEqual(project_name, name); self.assertNotIn(':', out.name)
        self.assertLess(len(out.name.encode('utf-8')), 255)
    def test_case_variant_of_existing_project_receives_new_name(self):
        _, name = allocate_fresh_run(self.root, 'Edit', ['EDIT'])
        self.assertNotEqual(name, 'Edit')
    def test_project_inventory_iterator_is_checked_without_consuming_it_twice(self):
        _, name = allocate_fresh_run(self.root, 'Edit', iter(['Edit']))
        self.assertNotEqual(name, 'Edit')
    def test_unavailable_project_inventory_is_rejected(self):
        for names in (None, 'Edit', [None]):
            with self.subTest(names=names), self.assertRaises(ValueError): allocate_fresh_run(self.root, 'Edit', names)
        self.assertFalse((self.root / 'Projects').exists())


class Project:
    def __init__(self, name, uid): self.name, self.uid = name, uid
    def GetUniqueId(self): return self.uid


class Manager:
    def __init__(self):
        self.projects = {name: Project(name, name + '-id') for name in ('Finished', 'Proof', 'Reopen', 'Other')}
        self.current = self.projects['Finished']; self.deleted = []; self.closed = []
        self.fail_close = self.fail_delete = self.fail_restore = False; self.keep_loads = 0
    def GetProjectListInCurrentFolder(self): return list(self.projects)
    def LoadProject(self, name):
        if name == 'Finished':
            self.keep_loads += 1
            if self.fail_restore and self.keep_loads > 1: return None
        self.current = self.projects.get(name); return self.current
    def CloseProject(self, project):
        self.closed.append(project.name)
        if self.fail_close: return False
        self.current = None; return True
    def DeleteProject(self, name):
        if self.fail_delete: return False
        if self.current and self.current.name == name: raise AssertionError('Cannot delete an open project')
        self.deleted.append(name); del self.projects[name]; return True


class CleanupTests(unittest.TestCase):
    def test_only_owned_test_projects_are_removed_and_finished_is_restored(self):
        pm = Manager()
        report = cleanup_test_projects(pm, {'Proof':'Proof-id', 'Reopen':'Reopen-id', 'Finished':'Finished-id'}, 'Finished')
        self.assertEqual(report, {'removed':['Proof','Reopen'], 'warnings':[]})
        self.assertEqual(set(pm.projects), {'Finished','Other'})
        self.assertEqual(pm.current.name, 'Finished'); self.assertNotIn('Finished', pm.closed)
    def test_identity_mismatch_is_preserved_and_reported(self):
        pm = Manager()
        report = cleanup_test_projects(pm, {'Proof':'old-ID', 'Reopen':'Reopen-id'}, 'Finished')
        self.assertIn('Proof', pm.projects); self.assertEqual(report['removed'], ['Reopen'])
        self.assertIn('different identity', report['warnings'][0]); self.assertEqual(pm.current.name, 'Finished')
    def test_failed_close_or_delete_returns_warning_and_restores_finished(self):
        for failure in ('fail_close','fail_delete'):
            with self.subTest(failure=failure):
                pm = Manager(); setattr(pm, failure, True)
                report = cleanup_test_projects(pm, {'Proof':'Proof-id'}, 'Finished')
                self.assertEqual(report['removed'], []); self.assertTrue(report['warnings'])
                self.assertIn('Proof', pm.projects); self.assertEqual(pm.current.name, 'Finished')
    def test_restore_failure_is_an_error_even_after_owned_cleanup(self):
        pm = Manager(); pm.fail_restore = True
        with self.assertRaisesRegex(RuntimeError, 'Could not return'):
            cleanup_test_projects(pm, {'Proof':'Proof-id'}, 'Finished')
        self.assertEqual(pm.deleted, ['Proof']); self.assertIn('Finished', pm.projects)
    def test_unavailable_finished_project_prevents_all_deletion(self):
        pm = Manager(); del pm.projects['Finished']
        with self.assertRaisesRegex(RuntimeError, 'no projects were deleted'):
            cleanup_test_projects(pm, {'Proof':'Proof-id'}, 'Finished')
        self.assertEqual(pm.deleted, [])
    def test_absent_projects_and_invalid_ownership_never_delete_others(self):
        pm = Manager()
        report = cleanup_test_projects(pm, {'Missing':'missing-id', 'Proof':None}, 'Finished')
        self.assertEqual(pm.deleted, []); self.assertEqual(len(report['warnings']), 1)
        self.assertEqual(pm.current.name, 'Finished')


if __name__ == '__main__': unittest.main()
