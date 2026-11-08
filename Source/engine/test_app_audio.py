"""Exercise the public audio CLI boundary without media or an installed editor."""
import contextlib
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

import app_engine


class SharedAudioBridgeTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.audio = types.ModuleType('attach_audio')
        for name in ('discover', 'make_plan', 'build'):
            setattr(self.audio, name, Mock(name='attach_audio.' + name))
        self.stack.enter_context(patch.dict(sys.modules, {'attach_audio': self.audio}))
        # These entry points would cross into ATEM parsing or editor conversion.
        # A regression must fail even if its call would otherwise be harmless.
        self.blocked = {}
        for name in ('scan', 'parse', 'preflight', 'discover_project',
                     'project_candidates', 'repair_for', 'audio_catalog',
                     'build', 'create', 'premiere_create', 'premiere_verify'):
            self.blocked[name] = self.stack.enter_context(patch.object(
                app_engine, name,
                side_effect=AssertionError('Audio mode called project path: ' + name)))

    def invoke(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = 0
        with patch.object(sys, 'argv', ['app_engine.py', *arguments]), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                app_engine.main()
            except SystemExit as error:
                code = error.code
        events = [json.loads(line) for line in stdout.getvalue().splitlines()]
        for function in self.blocked.values():
            function.assert_not_called()
        return code, events, stderr.getvalue()

    def test_discovery_needs_no_atem_project_or_editor(self):
        self.audio.discover.return_value = {
            'root': '/recording with spaces', 'cameras': 8, 'clips': 24,
            'audioISOs': 20,
            'choices': [{'id': 'CAM 8', 'label': 'CAM 8'}],
            'warnings': ['BWF clocks are not used for alignment.'],
        }
        code, events, errors = self.invoke(
            'audio-scan', '--root', '/recording with spaces', '--output', 'results with spaces')
        self.assertEqual(code, 0, errors)
        self.audio.discover.assert_called_once_with('/recording with spaces')
        scanned = next(e for e in events if e['event'] == 'audio_scanned')
        self.assertEqual(scanned['output'], str(Path('results with spaces').resolve()))
        self.assertEqual((scanned['cameras'], scanned['clips'], scanned['audioISOs']), (8, 24, 20))
        self.assertEqual(scanned['choices'], [{'id': 'CAM 8', 'label': 'CAM 8'}])
        self.audio.make_plan.assert_not_called()
        self.audio.build.assert_not_called()
        self.assertFalse(any(e['event'] in ('scanned', 'audio_plan', 'complete') for e in events))

    def test_plan_keeps_selected_source_and_exact_sample_ranges(self):
        def make_plan(root, source, output, progress):
            self.assertEqual((root, source, output), ('/Show Files', 'CAM 8', '/Results Folder'))
            progress('Checking timecode…\nReading the selected WAV.')
            return {
                'source': source,
                'output': '/Results Folder/Attached Audio',
                'report': '/Results Folder/Attached Audio/Attach Audio Plan.txt',
                'estimated_output_bytes': 5_123_456_789,
                'mapping': [
                    {'part': 2, 'wav': '/Show Files/Audio Source Files/Show CAM 8 02.wav',
                     'start_sample': 0, 'end_sample': 498_642_144},
                    {'part': 3, 'wav': '/Show Files/Audio Source Files/Show CAM 8 02.wav',
                     'start_sample': 498_642_144, 'end_sample': 517_573_056},
                ],
                'outputs': [{'camera': 1, 'part': 2}, {'camera': 1, 'part': 3}],
            }
        self.audio.make_plan.side_effect = make_plan
        code, events, errors = self.invoke(
            'audio-plan', '--root', '/Show Files', '--output', '/Results Folder', '--audio', 'CAM 8')
        self.assertEqual(code, 0, errors)
        ready = [e for e in events if e['event'] == 'audio_plan']
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]['source'], 'CAM 8')
        self.assertIn('[498642144, 517573056)', ready[0]['details'])
        self.assertIn('CAM 8', ready[0]['summary'])
        self.assertEqual(ready[0]['output'], '/Results Folder/Attached Audio')
        self.assertTrue(any(e['event'] == 'progress' and '\n' in e['message'] for e in events))
        self.audio.build.assert_not_called()
        self.assertFalse(any(e['event'] == 'complete' for e in events))

    def test_plan_requires_an_explicit_audio_choice(self):
        code, events, errors = self.invoke(
            'audio-plan', '--root', '/Show', '--output', '/Results')
        self.assertEqual(code, 2)
        self.assertEqual(events, [])
        self.assertIn('--audio', errors)
        self.audio.make_plan.assert_not_called()
        self.audio.build.assert_not_called()

    def test_mapping_failure_emits_error_without_ready_or_complete(self):
        self.audio.make_plan.side_effect = ValueError('Part 03 runs past the selected WAV boundary.')
        code, events, errors = self.invoke(
            'audio-plan', '--root', '/Show', '--output', '/Results', '--audio', 'MIC 1')
        self.assertEqual(code, 1)
        self.assertEqual(events, [{'event': 'error', 'message': 'Part 03 runs past the selected WAV boundary.'}])
        self.assertNotIn('Traceback', errors)
        self.audio.build.assert_not_called()

    def test_build_reports_only_verified_camera_files_and_job_folder(self):
        def build(output, progress):
            self.assertEqual(output, '/Results')
            progress('Verifying audio sample hashes…')
            return {'output': '/Results/Attached Audio', 'verified_count': 24, 'resumed_count': 8}
        self.audio.build.side_effect = build
        code, events, errors = self.invoke('audio-build', '--output', '/Results')
        self.assertEqual(code, 0, errors)
        complete = [e for e in events if e['event'] == 'complete']
        self.assertEqual(len(complete), 1)
        self.assertEqual(complete[0]['export'], '/Results/Attached Audio')
        self.assertIn('24 camera files verified', complete[0]['message'])
        self.assertIn('original ATEM project', complete[0]['message'])
        self.audio.discover.assert_not_called()
        self.audio.make_plan.assert_not_called()

    def test_failed_verification_never_emits_completion(self):
        self.audio.build.side_effect = ValueError('Audio sample hash mismatch; output was not verified.')
        code, events, errors = self.invoke('audio-build', '--output', '/Results')
        self.assertEqual(code, 1)
        self.assertEqual([e['event'] for e in events], ['error'])
        self.assertIn('hash mismatch', events[0]['message'])
        self.assertNotIn('Traceback', errors)


if __name__ == '__main__':
    unittest.main()
