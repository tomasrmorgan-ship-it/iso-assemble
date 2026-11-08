"""Reject empty, displaced, disabled or incorrectly mapped primary audio."""
import copy
import json
import unittest

from audio_validation import verify_primary_audio


def stereo_mapping():
    return dict(embedded_audio_channels=2, linked_audio={},
                track_mapping={'1': dict(channel_idx=[1, 2], mute=False, type='stereo')})


class Media:
    def __init__(self, path): self.path = path
    def GetClipProperty(self, key): return self.path if key == 'File Path' else None


class Item:
    def __init__(self, row):
        self.start, self.end, self.offset = row['start'], row['end'], row['source_start']
        self.media = Media(row['path']); self.enabled = True
        self.mapping = stereo_mapping(); self.links = []
    def GetStart(self): return self.start
    def GetEnd(self): return self.end
    def GetLeftOffset(self): return self.offset
    def GetMediaPoolItem(self): return self.media
    def GetClipEnabled(self): return self.enabled
    def GetSourceAudioChannelMapping(self):
        return self.mapping if isinstance(self.mapping, str) else json.dumps(self.mapping)
    def GetLinkedItems(self): return self.links


class Timeline:
    def __init__(self, rows): self.items = [Item(row) for row in rows]; self.count = 1; self.enabled = True
    def GetTrackCount(self, kind):
        if kind != 'audio': raise AssertionError('Expected audio track query')
        return self.count
    def GetItemListInTrack(self, kind, index):
        if (kind, index) != ('audio', 1): raise AssertionError('Expected A1 query')
        return self.items
    def GetIsTrackEnabled(self, kind, index): return self.enabled


def fixture():
    rows = [dict(path=f'/footage/CAM 8 {i:02d}.wav', start=start, end=end,
                 source_start=0, channels=2, sample_rate=48000)
            for i, (start, end) in enumerate(((100, 130), (130, 160), (1000, 1100)), 1)]
    plan = dict(name='Example', audio=dict(selected='cam8', label='CAM 8 ISO',
                     files=[dict(path=row['path'], start=row['start'], frames=row['end']-row['start']) for row in rows]),
                sessions=[dict(start=100, end=160), dict(start=1000, end=1100)], audio_assembly=rows)
    return Timeline(rows), plan


class AudioValidationTests(unittest.TestCase):
    def test_multiple_contiguous_files_and_real_session_gap_are_preserved(self):
        timeline, plan = fixture(); timeline.items.reverse()
        report = verify_primary_audio(timeline, plan)
        self.assertEqual(report['clips_verified'], 3)
        self.assertEqual(report['coverage'], [[100, 130], [130, 160], [1000, 1100]])
        self.assertEqual(report['mapping_checks'], 3); self.assertEqual(report['clip_enabled_checks'], 3)
        self.assertTrue(report['track_enabled_checked']); self.assertEqual(report['source_offsets'], [0, 0, 0])
        self.assertEqual(report['linked_item_counts'], [0, 0, 0])
        self.assertEqual(report['selected_audio'], 'cam8')
    def test_empty_a1_explicitly_names_source_and_target_edit(self):
        timeline, plan = fixture(); timeline.items = []
        with self.assertRaisesRegex(RuntimeError, "CAM 8 ISO.*Example_Edit.*A1 is empty"):
            verify_primary_audio(timeline, plan)
    def test_missing_or_duplicate_audio_track_is_rejected(self):
        for count in (0, 2):
            timeline, plan = fixture(); timeline.count = count
            with self.subTest(count=count), self.assertRaisesRegex(RuntimeError, 'expected one.*A1'):
                verify_primary_audio(timeline, plan)
    def test_wrong_physical_file_or_missing_pool_item_is_rejected(self):
        for missing in (False, True):
            timeline, plan = fixture()
            if missing: timeline.items[0].media = None
            else: timeline.items[0].media.path = '/footage/CAM 7 01.wav'
            with self.subTest(missing=missing), self.assertRaisesRegex(RuntimeError, 'different source'):
                verify_primary_audio(timeline, plan)
    def test_missing_audio_item_does_not_pass_session_coverage(self):
        timeline, plan = fixture(); timeline.items.pop()
        with self.assertRaisesRegex(RuntimeError, 'expected 3'):
            verify_primary_audio(timeline, plan)
    def test_same_duration_at_wrong_record_position_is_rejected(self):
        timeline, plan = fixture(); timeline.items[0].start += 1; timeline.items[0].end += 1
        with self.assertRaisesRegex(RuntimeError, 'start/end'):
            verify_primary_audio(timeline, plan)
    def test_wrong_source_offset_is_rejected(self):
        timeline, plan = fixture(); timeline.items[0].offset = 1
        with self.assertRaisesRegex(RuntimeError, 'wrong position inside'):
            verify_primary_audio(timeline, plan)
    def test_disabled_track_or_clip_is_rejected(self):
        for track in (True, False):
            timeline, plan = fixture()
            if track: timeline.enabled = False
            else: timeline.items[0].enabled = False
            with self.subTest(track=track), self.assertRaisesRegex(RuntimeError, 'disabled'):
                verify_primary_audio(timeline, plan)
    def test_zero_based_channel_bug_muting_and_wrong_type_are_rejected(self):
        faults = [dict(channel_idx=[0, 2]), dict(channel_idx=[2, 1]), dict(mute=True),
                  dict(type='mono'), dict(channel_idx=[1])]
        for changes in faults:
            timeline, plan = fixture(); timeline.items[0].mapping['track_mapping']['1'].update(changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(RuntimeError, 'unmuted stereo source channels 1 and 2'):
                verify_primary_audio(timeline, plan)
    def test_mapping_requires_actual_embedded_channels_and_only_one_stereo_track(self):
        for channels in (None, 0, 1, '2'):
            timeline, plan = fixture(); timeline.items[0].mapping['embedded_audio_channels'] = channels
            with self.subTest(channels=channels), self.assertRaisesRegex(RuntimeError, 'stereo source channels'):
                verify_primary_audio(timeline, plan)
        timeline, plan = fixture()
        timeline.items[0].mapping['track_mapping']['2'] = dict(channel_idx=[1, 2], mute=False, type='stereo')
        with self.assertRaisesRegex(RuntimeError, 'stereo source channels'):
            verify_primary_audio(timeline, plan)
    def test_invalid_mapping_json_is_not_treated_as_optional(self):
        timeline, plan = fixture(); timeline.items[0].mapping = '{broken'
        with self.assertRaisesRegex(RuntimeError, 'invalid audio channel mapping'):
            verify_primary_audio(timeline, plan)
    def test_absent_optional_apis_are_reported_as_unchecked(self):
        timeline, plan = fixture(); timeline.GetIsTrackEnabled = None
        for item in timeline.items:
            item.GetClipEnabled = item.GetSourceAudioChannelMapping = item.GetLinkedItems = None
        report = verify_primary_audio(timeline, plan)
        self.assertFalse(report['track_enabled_checked']); self.assertEqual(report['mapping_checks'], 0)
        self.assertEqual(report['clip_enabled_checks'], 0); self.assertEqual(report['linked_items_checked'], 0)
        self.assertEqual(report['clips_verified'], 3)
    def test_linked_items_are_observed_without_claiming_a_viewer_check(self):
        timeline, plan = fixture(); timeline.items[0].links = [object()]
        report = verify_primary_audio(timeline, plan)
        self.assertEqual(report['linked_item_counts'], [1, 0, 0])
    def test_invalid_plan_gap_overlap_boundary_and_extra_file_are_rejected(self):
        for fault in ('gap', 'overlap', 'crosses', 'outside'):
            timeline, plan = fixture()
            if fault == 'gap': plan['audio_assembly'][1]['start'] += 1
            elif fault == 'overlap': plan['audio_assembly'][1]['start'] -= 1
            elif fault == 'crosses': plan['audio_assembly'][1]['end'] += 1
            else: plan['audio_assembly'][2].update(start=900, end=1000)
            with self.subTest(fault=fault), self.assertRaisesRegex(RuntimeError, 'planned audio'):
                verify_primary_audio(timeline, plan)
    def test_assembly_cannot_substitute_another_selected_mix(self):
        timeline, plan = fixture(); plan['audio']['files'][0]['path'] = '/footage/MIC 1 01.wav'
        with self.assertRaisesRegex(RuntimeError, 'differ from the selected'):
            verify_primary_audio(timeline, plan)
    def test_missing_plan_or_invalid_source_format_is_rejected(self):
        timeline, plan = fixture(); del plan['audio_assembly']
        with self.assertRaisesRegex(RuntimeError, 'assembly plan is missing'):
            verify_primary_audio(timeline, plan)
        for key, value in (('channels', 1), ('sample_rate', 44100), ('source_start', .5)):
            timeline, plan = fixture(); plan['audio_assembly'][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'invalid frame boundaries'):
                verify_primary_audio(timeline, plan)
    def test_validation_does_not_modify_plan(self):
        timeline, plan = fixture(); before = copy.deepcopy(plan)
        verify_primary_audio(timeline, plan)
        self.assertEqual(plan, before)


if __name__ == '__main__': unittest.main()
