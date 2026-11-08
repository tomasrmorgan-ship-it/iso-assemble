"""Native transition safety checks using small Resolve API stand-ins."""
import copy
import unittest

from resolve_project import (apply_transitions, item_type, review_marker_data,
                             transition_inventory, validate,
                             validate_review_markers, video_items)
from timing import Timing


class Media:
    def GetClipProperty(self, key):
        if key != 'Type':
            raise AssertionError(key)
        return 'Multicam'


class LegacyVideo:
    """Old supported Resolve objects do not expose GetType or AddTransition."""
    def __init__(self, timeline, cut, plan):
        self.timeline = timeline
        self.start, self.end = cut['start'], cut['end']
        session = plan['sessions'][cut['session']]
        self.name = (f"{session['multicam_name']} - {cut['angle']} "
                     f"{plan['camera_names'][str(cut['angle'])]}")
        self.left = self.start - session['start']
        self.add_calls = []

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetName(self):
        return self.name

    def GetLeftOffset(self):
        return self.left

    def GetMediaPoolItem(self):
        return Media()


class Video(LegacyVideo):
    def GetType(self):
        return 'video'

    def AddTransition(self, options):
        self.add_calls.append(copy.deepcopy(options))
        self.timeline.add_calls.append((self, copy.deepcopy(options)))
        if self.timeline.fail_add:
            return None
        item = Transition(self.end - options['duration'], self.end)
        if self.timeline.shift_new_transition:
            item.start += 1
            item.end += 1
        self.timeline.transitions.append(item)
        return item


class Transition:
    def __init__(self, start, end, name='Cross Dissolve', duration=None):
        self.start, self.end, self.name = start, end, name
        self.duration = end - start if duration is None else duration

    def GetType(self):
        return 'transition'

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetName(self):
        return self.name

    def GetDuration(self):
        return self.duration


class Timeline:
    def __init__(self, plan, legacy=False):
        self.plan = plan
        self.transitions, self.add_calls, self.marker_calls = [], [], []
        self.markers = {}
        self.fail_add = self.shift_new_transition = False
        clip_type = LegacyVideo if legacy else Video
        self.videos = [clip_type(self, cut, plan) for cut in plan['cuts']
                       if cut['angle'] not in (None, 0)]

    def GetSetting(self, key):
        if key != 'timelineFrameRate':
            raise AssertionError(key)
        return '29.97 DF'

    def GetStartTimecode(self):
        return Timing.from_plan(self.plan).timecode(self.plan['origin'])

    def GetItemListInTrack(self, kind, index):
        if (kind, index) != ('video', 1):
            raise AssertionError((kind, index))
        return sorted(self.videos + self.transitions, key=lambda item: item.GetStart())

    def GetMarkers(self):
        return copy.deepcopy(self.markers)

    def AddMarker(self, frame, color, name, note, duration, customData):
        self.marker_calls.append((frame, color, name, note, duration, customData))
        if frame in self.markers:
            return False
        self.markers[frame] = dict(color=color, name=name, note=note,
                                   duration=duration, customData=customData)
        return True


def fixture():
    timing = Timing('30000/1001', True)
    origin = timing.frames('01:00:00;00')
    cuts = [dict(start=origin+a, end=origin+b, angle=angle, session=0)
            for a, b, angle in ((0, 10, 0), (10, 30, 1), (30, 50, 2), (50, 80, 1))]
    transitions = []
    for start, end, left, right, first, last in ((20, 30, 1, 2, 1, 2),
                                               (40, 50, 2, 3, 2, 1)):
        transitions.append(dict(
            start=origin+start, end=origin+end, duration_frames=end-start,
            from_cut_index=left, to_cut_index=right,
            from_angle=first, to_angle=last, unresolved=False,
            resolve_options=dict(type='Cross Dissolve', category='simple',
                                 position='end', alignment='left', duration=end-start)))
    marker = dict(frame=origin+60, end=origin+65, duration_frames=5,
                  line=100, end_line=101, name='Unresolved ATEM Mix',
                  note='Same-angle endpoints; inspect the program reference.')
    transitions.append(dict(start=origin+60, end=origin+65, duration_frames=5,
                            unresolved=True, from_angle=1, to_angle=1))
    return dict(timing=timing.data(), origin=origin, cuts=cuts,
                sessions=[dict(start=origin, end=origin+80,
                               multicam_name='Fixture_Session_01')],
                camera_names={'1': 'CAM 1', '2': 'CAM 2'},
                mix_policy='linear-review', transitions=transitions,
                review_markers=[marker])


class ResolveTransitionTests(unittest.TestCase):
    def setUp(self):
        self.plan = fixture()
        self.timeline = Timeline(self.plan)

    def test_empty_transition_plan_makes_no_timeline_changes(self):
        self.plan['transitions'] = []
        self.plan['review_markers'] = []
        self.assertEqual(apply_transitions(self.timeline, self.plan), 0)
        self.assertEqual(self.timeline.add_calls, [])
        self.assertEqual(self.timeline.marker_calls, [])

    def test_cut_only_plan_rejects_new_unplanned_transition_on_resume(self):
        row = self.plan['transitions'][0]
        self.timeline.transitions.append(Transition(row['start'], row['end']))
        self.plan['transitions'] = []
        self.plan['review_markers'] = []
        with self.assertRaisesRegex(RuntimeError, 'Existing transition differs'):
            apply_transitions(self.timeline, self.plan)
        self.assertEqual(self.timeline.add_calls, [])
        self.assertEqual(self.timeline.marker_calls, [])

    def test_apply_preserves_cuts_and_handles_with_black_gap_index(self):
        before = [(x.GetStart(), x.GetEnd(), x.GetName(), x.GetLeftOffset())
                  for x in self.timeline.videos]
        self.assertEqual(apply_transitions(self.timeline, self.plan), 2)
        self.assertEqual(before, [(x.GetStart(), x.GetEnd(), x.GetName(), x.GetLeftOffset())
                                  for x in self.timeline.videos])
        self.assertEqual(validate(self.timeline, self.plan), 3)
        for (left, options), row in zip(self.timeline.add_calls, self.plan['transitions']):
            self.assertEqual(left.GetEnd(), row['end'])
            self.assertEqual(options, row['resolve_options'])
        self.assertEqual(set(transition_inventory(self.timeline, self.plan, complete=True)),
                         {(r['start'], r['end']) for r in self.plan['transitions'] if not r['unresolved']})
        self.assertEqual(set(self.timeline.markers), {60})
        self.assertEqual(self.timeline.marker_calls[0][1], 'Red')

    def test_complete_resume_adds_nothing_and_preserves_review_markers(self):
        apply_transitions(self.timeline, self.plan)
        first_markers = copy.deepcopy(self.timeline.markers)
        self.timeline.add_calls.clear()
        self.timeline.marker_calls.clear()
        self.assertEqual(apply_transitions(self.timeline, self.plan), 2)
        self.assertEqual(self.timeline.add_calls, [])
        self.assertEqual(self.timeline.marker_calls, [])
        self.assertEqual(self.timeline.markers, first_markers)

    def test_partial_resume_adds_only_missing_exact_transition(self):
        row = self.plan['transitions'][0]
        self.timeline.transitions.append(Transition(row['start'], row['end']))
        self.assertEqual(apply_transitions(self.timeline, self.plan), 2)
        self.assertEqual(len(self.timeline.add_calls), 1)
        self.assertEqual(self.timeline.add_calls[0][0], self.timeline.videos[1])

    def test_unexpected_or_changed_existing_transition_rejected_before_mutation(self):
        row = self.plan['transitions'][0]
        invalid = [Transition(row['start']+1, row['end']+1),
                   Transition(row['start'], row['end'], name='Dip To Color Dissolve'),
                   Transition(row['start'], row['end'], duration=9)]
        for item in invalid:
            with self.subTest(item=vars(item)):
                timeline = Timeline(self.plan)
                timeline.transitions.append(item)
                with self.assertRaisesRegex(RuntimeError, 'Existing transition differs'):
                    apply_transitions(timeline, self.plan)
                self.assertEqual(timeline.add_calls, [])
                self.assertEqual(timeline.marker_calls, [])

    def test_duplicate_existing_or_planned_intervals_rejected(self):
        row = self.plan['transitions'][0]
        self.timeline.transitions = [Transition(row['start'], row['end']) for _ in range(2)]
        with self.assertRaisesRegex(RuntimeError, 'Existing transition differs'):
            apply_transitions(self.timeline, self.plan)
        self.timeline.transitions.clear()
        self.plan['transitions'].append(copy.deepcopy(row))
        with self.assertRaisesRegex(RuntimeError, 'Duplicate planned'):
            apply_transitions(self.timeline, self.plan)
        self.assertEqual(self.timeline.add_calls, [])

    def test_changed_angle_fails_before_adding_dissolve(self):
        self.timeline.videos[1].name = 'Fixture_Session_01 - 1 CAM 1'
        with self.assertRaisesRegex(RuntimeError, 'timing/angle differs'):
            apply_transitions(self.timeline, self.plan)
        self.assertEqual(self.timeline.add_calls, [])

    def test_marker_collision_rejected_before_adding_any_transition(self):
        self.timeline.markers[60] = dict(name='Personal note', note='Keep this marker',
                                          duration=1, customData='')
        before = copy.deepcopy(self.timeline.markers)
        with self.assertRaisesRegex(RuntimeError, 'different marker'):
            apply_transitions(self.timeline, self.plan)
        self.assertEqual(self.timeline.markers, before)
        self.assertEqual(self.timeline.add_calls, [])
        self.assertEqual(self.timeline.marker_calls, [])

    def test_review_marker_only_and_unrelated_marker_are_preserved(self):
        self.plan['transitions'] = [self.plan['transitions'][-1]]
        self.timeline.markers[5] = dict(name='Personal note', note='Keep', duration=1)
        self.assertEqual(apply_transitions(self.timeline, self.plan), 0)
        self.assertEqual(set(self.timeline.markers), {5, 60})
        self.assertEqual(self.timeline.add_calls, [])
        self.assertEqual(validate_review_markers(self.timeline, self.plan), 1)

    def test_marker_content_and_ownership_are_checked_on_resume(self):
        apply_transitions(self.timeline, self.plan)
        original = copy.deepcopy(self.timeline.markers[60])
        for key, changed in [('name', 'Changed'), ('note', 'Changed'),
                             ('duration', 6), ('customData', 'unowned')]:
            with self.subTest(field=key):
                self.timeline.markers[60] = {**original, key: changed}
                with self.assertRaisesRegex(RuntimeError, 'review marker'):
                    validate_review_markers(self.timeline, self.plan)
        self.assertEqual(original['customData'], review_marker_data(self.plan, self.plan['review_markers'][0]))

    def test_missing_transition_and_marker_fail_final_validation(self):
        with self.assertRaisesRegex(RuntimeError, 'Missing reconstructed'):
            transition_inventory(self.timeline, self.plan, complete=True)
        with self.assertRaisesRegex(RuntimeError, 'Missing or changed'):
            validate_review_markers(self.timeline, self.plan)

    def test_wrong_returned_range_or_failed_api_never_claims_success(self):
        for flag in ('shift_new_transition', 'fail_add'):
            with self.subTest(failure=flag):
                timeline = Timeline(self.plan)
                setattr(timeline, flag, True)
                with self.assertRaisesRegex(RuntimeError, 'exact requested dissolve'):
                    apply_transitions(timeline, self.plan)
                self.assertEqual(timeline.marker_calls, [])

    def test_legacy_gettype_fallback_keeps_existing_cut_validation(self):
        timeline = Timeline(self.plan, legacy=True)
        self.assertEqual(item_type(timeline.videos[0]), 'video')
        self.assertEqual(video_items(timeline), timeline.videos)
        self.assertEqual(validate(timeline, self.plan), 3)
        with self.assertRaisesRegex(RuntimeError, 'cannot apply native multicam transitions'):
            apply_transitions(timeline, self.plan)
        self.assertEqual(timeline.marker_calls, [])


if __name__ == '__main__':
    unittest.main()
