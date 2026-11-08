"""An export's bytes, not only its conversion plan, identify its verification import."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from export_validation import load_export_for_verification


class Project:
    def __init__(self, name, uid): self.name, self.uid = name, uid
    def GetUniqueId(self): return self.uid


class Manager:
    def __init__(self):
        self.projects = {}; self.imports = []; self.loads = []
        self.fail_import = self.fail_load = False
        self.on_import = None
    def GetProjectListInCurrentFolder(self): return list(self.projects)
    def ImportProject(self, path, name):
        self.imports.append((path, name))
        if self.fail_import or name in self.projects: return False
        self.projects[name] = Project(name, 'id-' + str(len(self.imports)))
        if self.on_import: self.on_import()
        return True
    def LoadProject(self, name):
        self.loads.append(name)
        return None if self.fail_load else self.projects.get(name)


class ExportValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = self.root / 'Project.drp'; self.target.write_bytes(b'first export')
        self.check = self.root / 'export-check-state.json'
        self.fingerprint = hashlib.sha256(b'conversion').hexdigest()
        self.pm = Manager()
    def tearDown(self): self.temp.cleanup()
    def load(self): return load_export_for_verification(self.pm, self.target, self.check, self.fingerprint)
    def name(self):
        digest = hashlib.sha256(self.target.read_bytes()).hexdigest()
        return f'ISOAssemble_Verify_{self.fingerprint[:8]}_{digest[:8]}'
    def test_matching_bytes_reuse_owned_import_and_record_exact_identity(self):
        project, first = self.load(); again, second = self.load()
        self.assertIs(project, again); self.assertEqual(len(self.pm.imports), 1)
        self.assertFalse(first['reused']); self.assertTrue(second['reused'])
        self.assertEqual(first['name'], self.name())
        self.assertEqual(first['export'], str(self.target.resolve()))
        self.assertEqual(first['export_sha256'], hashlib.sha256(self.target.read_bytes()).hexdigest())
        saved = json.loads(self.check.read_text())
        self.assertEqual(saved['records'][first['name']]['project_id'], project.GetUniqueId())
        self.assertEqual(saved['owner'], first['owner'])
    def test_changed_bytes_import_fresh_even_with_same_plan_and_size(self):
        old, before = self.load(); self.target.write_bytes(b'other export')
        new, after = self.load()
        self.assertIsNot(old, new); self.assertNotEqual(before['name'], after['name'])
        self.assertEqual(len(self.pm.imports), 2); self.assertFalse(after['reused'])
        self.assertEqual(len(self.pm.projects), 2)
        self.assertEqual(len(json.loads(self.check.read_text())['records']), 2)
        self.target.write_bytes(b'first export')
        reverted, metadata = self.load()
        self.assertIs(reverted, old); self.assertTrue(metadata['reused'])
    def test_legacy_state_is_preserved_without_reusing_unknown_export(self):
        old_name = 'ISOAssemble_Verify_' + self.fingerprint[:12]
        self.pm.projects[old_name] = Project(old_name, 'legacy-id')
        legacy = dict(name=old_name, project_id='legacy-id')
        self.check.write_text(json.dumps(legacy))
        project, result = self.load()
        self.assertNotEqual(project.name, old_name); self.assertFalse(result['reused'])
        self.assertIn(old_name, self.pm.projects)
        self.assertEqual(json.loads(self.check.read_text())['legacy'], legacy)
    def test_unowned_exact_name_collision_is_preserved(self):
        name = self.name(); existing = Project(name, 'someone-else')
        self.pm.projects[name] = existing
        with self.assertRaisesRegex(RuntimeError, 'collision'): self.load()
        self.assertIs(self.pm.projects[name], existing)
        self.assertEqual(self.pm.imports, []); self.assertFalse(self.check.exists())
    def test_replaced_project_id_is_not_reused(self):
        _, metadata = self.load(); before = self.check.read_bytes()
        self.pm.projects[metadata['name']].uid = 'replacement-project'
        with self.assertRaisesRegex(RuntimeError, 'identity changed'): self.load()
        self.assertEqual(self.check.read_bytes(), before); self.assertEqual(len(self.pm.imports), 1)
    def test_missing_owned_import_can_be_recreated(self):
        _, before = self.load(); del self.pm.projects[before['name']]
        _, after = self.load()
        self.assertFalse(after['reused']); self.assertNotEqual(before['project_id'], after['project_id'])
    def test_full_hash_guards_short_name_hash_collision(self):
        _, record = self.load(); state = json.loads(self.check.read_text())
        state['records'][record['name']]['export_sha256'] = record['export_sha256'][:8] + '0' * 56
        self.check.write_text(json.dumps(state))
        with self.assertRaisesRegex(RuntimeError, 'export identity differs'): self.load()
        self.assertEqual(len(self.pm.imports), 1)
    def test_failed_import_records_no_success(self):
        self.pm.fail_import = True
        with self.assertRaisesRegex(RuntimeError, 'reimport'): self.load()
        self.assertFalse(self.check.exists())
    def test_failed_load_leaves_project_unclaimed(self):
        self.pm.fail_load = True
        with self.assertRaisesRegex(RuntimeError, 'Could not open'): self.load()
        self.assertFalse(self.check.exists()); self.assertIn(self.name(), self.pm.projects)
        self.pm.fail_load = False
        with self.assertRaisesRegex(RuntimeError, 'collision'): self.load()
    def test_export_changing_during_import_never_records_cache_entry(self):
        self.pm.on_import = lambda: self.target.write_bytes(b'changed during import')
        with self.assertRaisesRegex(RuntimeError, 'changed during'): self.load()
        self.assertFalse(self.check.exists())
    def test_corrupt_state_is_not_replaced(self):
        self.check.write_text('{broken')
        with self.assertRaisesRegex(ValueError, 'cannot be read'): self.load()
        self.assertEqual(self.check.read_text(), '{broken'); self.assertEqual(self.pm.imports, [])
    def test_state_and_export_symlinks_are_rejected(self):
        outside = self.root / 'outside.json'; outside.write_text('untouched')
        self.check.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symbolic link'): self.load()
        self.assertEqual(outside.read_text(), 'untouched'); self.check.unlink()
        original = self.root / 'Original.drp'; self.target.rename(original); self.target.symlink_to(original)
        with self.assertRaisesRegex(ValueError, 'symbolic link'): self.load()
        self.assertEqual(self.pm.imports, [])
    def test_empty_export_and_state_target_alias_are_rejected(self):
        self.target.write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'empty'): self.load()
        self.target.write_bytes(b'valid')
        with self.assertRaisesRegex(ValueError, 'cannot replace'):
            load_export_for_verification(self.pm, self.target, self.target, self.fingerprint)
        self.assertEqual(self.target.read_bytes(), b'valid')


if __name__ == '__main__': unittest.main()
