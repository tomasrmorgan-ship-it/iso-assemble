"""Mix planning preserves integer edit positions and explicitly unresolved events."""
import copy
import unittest
import xml.etree.ElementTree as ET

from atem import merge
from convert import build
from timing import Timing


def fixture(changes, *, timing=None, origin=1000, count=300, extra_sources=None):
    timing = timing or Timing()
    header = dict(videoMode='1080p'+timing.resolve_rate, recordingId='test',
                  masterTimecode=timing.timecode(origin),
                  mixEffectBlocks=[dict(_index_=0, onAir=True, source=1,
                    transitionActive=False, transitionPosition=1.0,
                    transitionType='Mix', transitionBackground=True)])
    rows = [(0, header)]
    for offset, change in changes:
        rows.append((offset, dict(masterTimecode=timing.timecode(origin+offset),
                                  mixEffectBlocks=[dict(_index_=0, **change)])))
    rows.append((count, dict(masterTimecode=timing.timecode(origin+count),
                            mixEffectBlocks=[dict(_index_=0, onAir=False)])))
    state = {}; events = []
    for line, (offset, update) in enumerate(rows, 1):
        state = merge(state, update)
        events.append(dict(line=line, frame=origin+offset, session=0,
                           update=update, state=copy.deepcopy(state)))
    if extra_sources:
        for index, value in extra_sources.items():
            events[index]['update']['sources'] = value
    media = [dict(path=f'/tmp/mix-test-camera-{i}.mov', camera=i,
                  name=f'Camera {i}', start=origin, end=origin+count, frames=count)
             for i in range(1, 4)]
    return dict(timing=timing.data(), media=media, events=events, warnings=[])


def endpoints(plan):
    return [(c['start'], c['end'], c['angle']) for c in plan['cuts']]


class MixTests(unittest.TestCase):
    def simple(self, **kwargs):
        return fixture([(30, dict(transitionActive=True, transitionPosition=0)),
                        (60, dict(transitionActive=False, transitionPosition=1, source=2))], **kwargs)

    def test_strict_default_still_stops_before_active_transition(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported active transition'):
            build(self.simple(), 'Test')
        with self.assertRaisesRegex(ValueError, 'Unknown Mix policy'):
            build(self.simple(), 'Test', mix_policy='automatic')

    def test_linear_review_preserves_end_cut_and_native_multicam_xml(self):
        data = self.simple(); before = copy.deepcopy(data['events'])
        xml, plan = build(data, 'Test', mix_policy='linear-review')
        self.assertEqual(endpoints(plan), [(1000, 1060, 1), (1060, 1300, 2)])
        t = plan['transitions'][0]
        self.assertEqual((t['start'], t['end'], t['cut_frame'], t['duration_frames']), (1030, 1060, 1060, 30))
        self.assertEqual(t['resolve_options'], dict(type='Cross Dissolve', category='simple',
                         position='end', alignment='left', duration=30))
        self.assertEqual((t['incoming_source_start_frame'], t['incoming_handle_start_frame']), (60, 30))
        self.assertFalse(t['unresolved']); self.assertFalse(t['applied']); self.assertTrue(t['requires_review'])
        self.assertEqual(t['status'], 'pending_resolve_application')
        self.assertIn('manual fader curve', plan['transition_warnings'][0])
        tree = ET.fromstring(xml)
        self.assertEqual(len(tree.findall('.//multicam/mc-angle')), 3)
        self.assertEqual(len(tree.findall('.//spine/mc-clip')), 2)
        self.assertEqual(tree.findall('.//transition'), [])
        self.assertEqual(data['events'], before)

    def test_partial_updates_do_not_duplicate_interval_or_cut(self):
        data = fixture([(30, dict(transitionActive=True, transitionPosition=0)),
                        (40, dict(transitionPosition=0)),
                        (50, dict(transitionPosition=.4)),
                        (60, dict(transitionActive=False, transitionPosition=1, source=2))])
        _, plan = build(data, 'Test', mix_policy='linear-review')
        self.assertEqual(len(plan['transitions']), 1)
        self.assertEqual(len(plan['cuts']), 2)
        self.assertTrue(plan['transitions'][0]['intermediate_fader_positions_logged'])
        self.assertTrue(plan['transitions'][0]['requires_review'])

    def test_same_angle_is_marked_without_invented_dissolve_or_cut(self):
        data = fixture([(30, dict(transitionActive=True, transitionPosition=0)),
                        (60, dict(transitionActive=False, transitionPosition=1, source=1))])
        _, plan = build(data, 'Test', mix_policy='linear-review')
        self.assertEqual(endpoints(plan), [(1000, 1300, 1)])
        t = plan['transitions'][0]
        self.assertTrue(t['same_angle_endpoints']); self.assertTrue(t['unresolved'])
        self.assertNotIn('resolve_options', t)
        marker = plan['review_markers'][0]
        self.assertEqual((marker['frame'], marker['end'], marker['duration_frames']), (1030, 1060, 30))
        self.assertIn('intermediate transition target is unknown', marker['note'])

    def test_same_angle_with_internal_switch_retains_the_nine_frame_selection(self):
        data = fixture([(30, dict(transitionActive=True, transitionPosition=0)),
                        (219, dict(source=2)),
                        (228, dict(transitionActive=False, transitionPosition=1, source=1))])
        _, plan = build(data, 'Test', mix_policy='linear-review')
        self.assertEqual(endpoints(plan), [(1000, 1219, 1), (1219, 1228, 2), (1228, 1300, 1)])
        t = plan['transitions'][0]
        self.assertEqual(t['duration_frames'], 198)
        self.assertEqual(t['internal_source_changes'], [dict(frame=1219, line=3, from_angle=1, to_angle=2)])
        self.assertTrue(t['unresolved']); self.assertEqual(len(plan['review_markers']), 1)

    def test_different_endpoints_with_third_angle_are_also_unresolved(self):
        data = fixture([(30, dict(transitionActive=True, transitionPosition=0)),
                        (58, dict(source=3)),
                        (61, dict(transitionActive=False, transitionPosition=1, source=2))])
        _, plan = build(data, 'Test', mix_policy='linear-review')
        self.assertEqual(endpoints(plan), [(1000, 1058, 1), (1058, 1061, 3), (1061, 1300, 2)])
        self.assertFalse(plan['transitions'][0]['same_angle_endpoints'])
        self.assertTrue(plan['transitions'][0]['unresolved'])
        self.assertNotIn('resolve_options', plan['transitions'][0])

    def test_dissolve_geometry_does_not_erase_source_file_boundary(self):
        data = fixture([(30, dict(transitionActive=True, transitionPosition=0)),
                        (45, dict(transitionPosition=0)),
                        (60, dict(transitionActive=False, transitionPosition=1, source=2))],
                       extra_sources={2: [dict(_index_=1, file='part02.mov')]})
        _, plan = build(data, 'Test', mix_policy='linear-review')
        self.assertEqual(endpoints(plan), [(1000, 1045, 1), (1045, 1060, 1), (1060, 1300, 2)])
        self.assertTrue(plan['transitions'][0]['unresolved'])
        self.assertTrue(any('boundary' in x for x in plan['transitions'][0]['review_reasons']))

    def test_hard_cuts_outside_mix_remain_exact(self):
        data = fixture([(10, dict(source=3)),
                        (30, dict(transitionActive=True, transitionPosition=0)),
                        (60, dict(transitionActive=False, transitionPosition=1, source=2)),
                        (80, dict(source=1)), (100, dict(source=0)), (120, dict(source=3))])
        _, plan = build(data, 'Test', mix_policy='linear-review')
        self.assertEqual(endpoints(plan), [(1000, 1010, 1), (1010, 1060, 3), (1060, 1080, 2),
                                          (1080, 1100, 1), (1100, 1120, 0), (1120, 1300, 3)])
        self.assertFalse(plan['transitions'][0]['unresolved'])

    def test_drop_frame_minute_and_midnight_are_integer_intervals(self):
        timing = Timing()
        for origin in (timing.frames('00:00:59;15'), timing.day-45):
            with self.subTest(origin=origin):
                _, plan = build(self.simple(timing=timing, origin=origin), 'Test', mix_policy='linear-review')
                t = plan['transitions'][0]
                self.assertEqual((t['start'], t['end'], t['duration_frames']), (origin+30, origin+60, 30))
                self.assertEqual(plan['cuts'][1]['start'], origin+60)
                self.assertEqual(timing.frames(t['end_timecode']), (origin+60) % timing.day)

    def test_other_transition_types_fades_and_keys_still_stop(self):
        for values in (dict(transitionType='Wipe'), dict(fadeToBlack='Active'),
                       dict(upstreamKeys=[dict(_index_=0, onAir=True)]), dict(transitionBackground=False)):
            with self.subTest(values=values):
                data = self.simple()
                for ev in data['events'][1:]:
                    ev['state']['mixEffectBlocks'][0].update(values)
                with self.assertRaises(ValueError):build(data, 'Test', mix_policy='linear-review')
        data = self.simple();data['events'][1]['state']['downstreamKeys']=[dict(_index_=0,onAir=True)]
        with self.assertRaisesRegex(ValueError, 'downstream key'):build(data, 'Test', mix_policy='linear-review')

    def test_incomplete_mix_does_not_cross_session_or_stop(self):
        data = fixture([(30, dict(transitionActive=True, transitionPosition=0))])
        with self.assertRaisesRegex(ValueError, 'active background|Incomplete Mix'):
            build(data, 'Test', mix_policy='linear-review')
        data = self.simple();data['events'][2]['session']=1
        data['events'][2]['state']['recordingId']='second'
        data['events'][3]['session']=1;data['events'][3]['state']['recordingId']='second'
        with self.assertRaisesRegex(ValueError, 'Incomplete Mix'):
            build(data, 'Test', mix_policy='linear-review')

    def test_recording_start_mid_mix_has_no_invented_start(self):
        data = self.simple();data['events'][0]['state']['mixEffectBlocks'][0]['transitionActive']=True
        with self.assertRaisesRegex(ValueError, 'start is unknown'):
            build(data, 'Test', mix_policy='linear-review')

    def test_incomplete_fader_travel_stays_unresolved(self):
        data = fixture([(30, dict(transitionActive=True, transitionPosition=.2)),
                        (60, dict(transitionActive=False, transitionPosition=.8, source=2))])
        _, plan = build(data, 'Test', mix_policy='linear-review')
        self.assertTrue(plan['transitions'][0]['unresolved'])
        self.assertTrue(any('0-to-1' in reason for reason in plan['transitions'][0]['review_reasons']))

    def test_transition_type_change_at_closing_edge_is_rejected(self):
        data = self.simple()
        data['events'][2]['state']['mixEffectBlocks'][0]['transitionType'] = 'Wipe'
        with self.assertRaisesRegex(ValueError, 'type changed'):
            build(data, 'Test', mix_policy='linear-review')

    def test_invalid_fader_samples_have_useful_errors(self):
        for value in ('half', -1, 2, float('nan')):
            with self.subTest(value=value):
                data = self.simple()
                data['events'][1]['state']['mixEffectBlocks'][0]['transitionPosition'] = value
                with self.assertRaisesRegex(ValueError, 'Invalid Mix fader position'):
                    build(data, 'Test', mix_policy='linear-review')

    def test_no_mix_has_identical_cut_plan_under_both_policies(self):
        data = fixture([(40, dict(source=2)), (80, dict(source=3))])
        xml1, plan1 = build(copy.deepcopy(data), 'Test')
        xml2, plan2 = build(copy.deepcopy(data), 'Test', mix_policy='linear-review')
        self.assertEqual(xml1, xml2);self.assertEqual(plan1['cuts'], plan2['cuts'])
        self.assertEqual(plan2['transitions'], [])
        self.assertEqual(plan2['transition_warnings'], [])


if __name__ == '__main__':
    unittest.main()
