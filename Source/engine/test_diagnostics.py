import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diagnostics import event_review, write_review
from timing import Timing


def event(line, frame, active, angle, position, session=0):
    return dict(line=line, frame=frame, session=session,
                update={'masterTimecode': Timing().timecode(frame)},
                state={'masterTimecode': Timing().timecode(frame), 'videoMode':'1080p29.97',
                       'mixEffectBlocks':[{'_index_':0, 'transitionActive':active,
                            'source':angle, 'transitionPosition':position, 'transitionType':'Mix'}]})


class DiagnosticTests(unittest.TestCase):
    def test_partial_state_records_do_not_duplicate_a_transition(self):
        rows=[event(1,100,False,1,1), event(2,110,True,1,0),
              event(3,115,True,1,0), event(4,120,False,2,1)]
        report=event_review(rows, 'test.drp', Timing())
        self.assertEqual(len(report['transitions']),1)
        transition=report['transitions'][0]
        self.assertEqual((transition['line'],transition['end_line'],transition['duration_frames']),(2,4,10))
        self.assertFalse(transition['intermediate_fader_positions_logged'])
        self.assertFalse(transition['same_angle_endpoints'])
        self.assertEqual(rows[2]['frame'],115)

    def test_same_angle_endpoints_and_sampled_curve_are_reported(self):
        rows=[event(1,100,False,1,1), event(2,110,True,1,0),
              event(3,115,True,1,.4),event(4,120,False,1,1)]
        t=event_review(rows,'test.drp',Timing())['transitions'][0]
        self.assertTrue(t['same_angle_endpoints'])
        self.assertTrue(t['intermediate_fader_positions_logged'])

    def test_incomplete_transition_does_not_cross_recording_boundary(self):
        rows=[event(1,100,True,1,0),event(2,200,False,2,1,session=1)]
        report=event_review(rows,'test.drp',Timing())
        self.assertTrue(report['transitions'][0]['incomplete'])
        self.assertNotIn('end',report['transitions'][0])

    def test_media_failure_still_writes_event_review(self):
        from app_engine import scan
        rows=[event(1,100,False,1,1),event(2,110,True,1,0),event(3,120,False,2,1)]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'test.drp';project.write_text('original')
            with patch('app_engine.project_candidates',return_value=[project]),patch('app_engine.discover_project',return_value=project),patch('app_engine.repair_for',return_value=None),patch('app_engine.parse',return_value=(rows,{})),patch('app_engine.preflight',side_effect=ValueError('Timestamp gaps in camera.mp4')):
                with self.assertRaisesRegex(ValueError,'ATEM Review.txt'):scan(root,root/'results')
            report=json.loads((root/'results/ATEM Review.json').read_text())
            self.assertEqual(report['scan_status'],'blocked')
            self.assertEqual(len(report['transitions']),1)
            self.assertIn('Timestamp gaps',(root/'results/ATEM Review.txt').read_text())
            self.assertEqual(project.read_text(),'original')
            self.assertFalse((root/'results/scan.json').exists())


if __name__=='__main__':unittest.main()
