"""Public bridge opt-in, policy persistence and pre-mutation editor gates."""
import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app_engine
from test_mix_transitions import fixture


class MixBridgeTests(unittest.TestCase):
    def data(self, root, active=True):
        rows = [(30, dict(transitionActive=True, transitionPosition=0)),
                (60, dict(transitionActive=False, transitionPosition=1, source=2))] if active else [(60, dict(source=2))]
        data = fixture(rows)
        project = root / 'test.drp';project.write_text('untouched original')
        data.update(input=str(project), sha256='test-input', record_count=len(data['events']))
        data['warnings']=['Original warning']
        return data, project

    def catalog(self):
        return dict(candidates=[dict(id='program', label='Program', selectable=True,
                                     files=[dict(path='/tmp/program.mp4', start=1000, end=1300, frames=300)])],
                    inventory=[], warnings=['Audio warning'])

    def scan_with_fixture(self, root, out, data, project, **kwargs):
        with patch('app_engine.discover_project', return_value=project), \
                patch('app_engine.repair_for', return_value=None), \
                patch('app_engine.parse', return_value=(data['events'], {})), \
                patch('app_engine.preflight', return_value=copy.deepcopy(data)), \
                patch('app_engine.audio_catalog', return_value=self.catalog()), \
                patch('app_engine.emit') as emit:
            app_engine.scan(root, out, selected=str(project), **kwargs)
        return emit

    def test_scan_requires_explicit_opt_in_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=root/'results';data,project=self.data(root)
            with self.assertRaisesRegex(ValueError,'Unsupported active transition'):
                self.scan_with_fixture(root,out,data,project)
            self.assertFalse((out/'scan.json').exists())
            self.assertEqual(json.loads((out/'ATEM Review.json').read_text())['scan_status'],'blocked')
            self.assertEqual(project.read_text(),'untouched original')

    def test_scan_persists_mix_mode_and_emits_review_counts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=root/'results';data,project=self.data(root)
            emit=self.scan_with_fixture(root,out,data,project,mix_policy='linear-review')
            package=json.loads((out/'scan.json').read_text())
            self.assertEqual(package['mix_policy'],'linear-review')
            event=next(call.kwargs for call in emit.call_args_list if call.args[0]=='scanned')
            self.assertEqual((event['transitions'],event['linearTransitions'],event['unresolvedTransitions']),(1,1,0))
            self.assertTrue(event['requiresReview'])
            self.assertEqual(event['transitionStatus'],'planned-review-required')
            self.assertIn('Original warning',event['warnings']);self.assertIn('Audio warning',event['warnings'])
            self.assertTrue(any('manual fader curve' in warning for warning in event['warnings']))
            review=json.loads((out/'ATEM Review.json').read_text())
            self.assertEqual(review['transition_plan'][0]['cut_frame'],1060)
            text=(out/'ATEM Review.txt').read_text()
            self.assertIn('Linear Cross Dissolves planned for Resolve: 1',text)
            self.assertNotIn('This build cannot reconstruct',text)
            self.assertIn('have not happened during this scan',text)

    def package(self, root, active=True, policy='linear-review'):
        data,_=self.data(root,active=active)
        package=dict(root=str(root),data=data,catalog=self.catalog(),snapshot={},mix_policy=policy)
        (root/'scan.json').write_text(json.dumps(package))
        return package

    def test_older_resolve_rejects_review_mode_before_project_access(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.package(root)
            resolve=Mock();resolve.GetVersionString.return_value='21.0.0.48'
            with patch('resolve_project.connect',return_value=resolve):
                with self.assertRaisesRegex(ValueError,'21.1'):
                    app_engine.create(root,'Test','program')
            resolve.GetProjectManager.assert_not_called()
            self.assertFalse((root/'conversion.json').exists())

    def test_older_resolve_is_rejected_before_project_access(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.package(root,active=False,policy='strict')
            resolve=Mock();resolve.GetVersionString.return_value='20.3.0.1'
            with patch('resolve_project.connect',return_value=resolve):
                with self.assertRaisesRegex(ValueError,'21'):
                    app_engine.create(root,'Test','program')
            resolve.GetProjectManager.assert_not_called()

    def test_create_uses_saved_policy_and_preserves_warnings(self):
        for version,active,policy in [('21.1.1.10',True,'linear-review'),
                                     ('21.1.1.10',False,'strict'),('21.0.0.48',False,'strict'),
                                     ('21.2.0.6',True,'linear-review')]:
            with self.subTest(version=version,policy=policy),tempfile.TemporaryDirectory() as d:
                root=Path(d);self.package(root,active=active,policy=policy)
                resolve=Mock();resolve.GetVersionString.return_value=version
                pm=resolve.GetProjectManager.return_value
                pm.GetProjectListInCurrentFolder.return_value=[];pm.GetCurrentProject.return_value=None
                with patch('resolve_project.connect',return_value=resolve), \
                        patch('resolve_compatibility.ensure_compatible',return_value={'passed':True}) as proof, \
                        patch('resolve_project.apply',side_effect=ValueError('test stops after owned manifest')) as apply:
                    with self.assertRaisesRegex(ValueError,'test stops'):
                        app_engine.create(root,'Test','program')
                apply.assert_called_once()
                proof.assert_called_once()
                plan=json.loads((root/'conversion.json').read_text())
                self.assertEqual(plan['mix_policy'],policy)
                self.assertIn('Original warning',plan['warnings']);self.assertIn('Audio warning',plan['warnings'])
                self.assertEqual(len(plan['transitions']),1 if active else 0)
                if active:self.assertTrue(any('manual fader curve' in warning for warning in plan['warnings']))

    def test_failed_runtime_proof_stops_before_real_project_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.package(root)
            resolve=Mock();resolve.GetVersionString.return_value='21.2.0.6'
            pm=resolve.GetProjectManager.return_value
            pm.GetProjectListInCurrentFolder.return_value=[];pm.GetCurrentProject.return_value=None
            with patch('resolve_project.connect',return_value=resolve), \
                    patch('resolve_compatibility.ensure_compatible',side_effect=ValueError('Compatibility test failed')), \
                    patch('resolve_project.apply') as apply:
                with self.assertRaisesRegex(ValueError,'Compatibility test failed'):
                    app_engine.create(root,'Test','program')
            apply.assert_not_called()
            self.assertFalse((root/'conversion.json').exists())

    def test_review_semantics_change_fingerprint_but_legacy_strict_hash_survives(self):
        xml=b'<xml/>';chosen={'id':'program'};files={};strict={'mix_policy':'strict','transitions':[]}
        old=hashlib.sha256(xml+json.dumps(chosen,sort_keys=True).encode()+json.dumps(files,sort_keys=True).encode()).hexdigest()
        self.assertEqual(app_engine.conversion_fingerprint(xml,chosen,files,strict),old)
        plan={'mix_policy':'linear-review','transitions':[{'start':30,'end':60}]}
        first=app_engine.conversion_fingerprint(xml,chosen,files,plan)
        self.assertNotEqual(first,old)
        plan['transitions'][0]['end']=61
        self.assertNotEqual(app_engine.conversion_fingerprint(xml,chosen,files,plan),first)

    def test_premiere_refuses_mix_before_writing_any_interchange(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.package(root)
            with patch('premiere.generate') as generate:
                with self.assertRaisesRegex(ValueError,'Premiere export cannot reconstruct'):
                    app_engine.premiere_create(root,'Test','program')
            generate.assert_not_called()
            self.assertFalse((root/'Test.xml').exists());self.assertFalse((root/'premiere-manifest.json').exists())

    def test_scan_cli_requires_named_review_choice(self):
        with patch.object(sys,'argv',['app_engine.py','scan','--root','/recording','--output','/results','--mix-policy','linear-review']), \
                patch('app_engine.scan') as scan:
            app_engine.main()
        scan.assert_called_once_with('/recording','/results',None,mix_policy='linear-review')


if __name__=='__main__':unittest.main()
