"""Independent primary-audio XML assembly across real recording boundaries."""
import copy
from fractions import Fraction
import unittest
import xml.etree.ElementTree as ET

from audio_timeline import add_primary_audio
from convert import build
from timing import Timing


def edit_fixture(timing=None, sessions=None):
    timing = timing or Timing()
    # Each tuple is absolute start, physical video part lengths, camera changes.
    sessions = sessions or [(1000, [180], [(0, 1), (30, 2), (90, 1)])]
    media, events = [], []
    part = 1
    for index, (start, lengths, changes) in enumerate(sessions):
        cursor = start
        for length in lengths:
            for camera in (1, 2):
                media.append(dict(path=f'/fixture/Video ISO Files/Show CAM {camera} {part:02d}.mov',
                                  camera=camera, name=f'Camera {camera}', start=cursor,
                                  end=cursor + length, frames=length))
            cursor += length
            part += 1
        for offset, camera in [*changes, (sum(lengths), None)]:
            state = dict(recordingId=f'recording-{index}', masterTimecode=timing.timecode(start + offset),
                         mixEffectBlocks=[dict(onAir=camera is not None, source=camera or 0,
                                               transitionActive=False)])
            events.append(dict(frame=start + offset, line=len(events) + 1,
                               session=index, state=state, update={}))
    data = dict(timing=timing.data(), media=media, events=events)
    return build(data, 'Audio Test')


def audio_file(start, frames, part=1, path=None):
    return dict(path=path or f'/fixture/Audio Source Files/Show CAM 8 {part:02d}.wav',
                start=start, end=start + frames, frames=frames, channels=2, sample_rate=48000)


def chosen(*files, source='cam8'):
    return dict(id=source, label='Primary audio', files=list(files))


def seconds(value):
    return Fraction(value[:-1])


def imported_audio_geometry(xml, timing):
    """Decode connection coordinates independently into timeline/source frames."""
    root = ET.fromstring(xml)
    resources = {node.get('id'): node for node in root.find('resources')}
    rows = []
    for parent in root.findall('./library/event/project/sequence/spine/*'):
        parent_absolute = seconds(parent.get('offset')) * timing.fps
        parent_source = seconds(parent.get('start')) * timing.fps
        for clip in parent.findall('clip'):
            component = clip.find('audio')
            asset = resources[component.get('ref')]
            absolute = parent_absolute + seconds(clip.get('offset')) * timing.fps - parent_source
            count = seconds(clip.get('duration')) * timing.fps
            source_start = (seconds(component.get('start')) - seconds(asset.get('start'))) * timing.fps
            rows.append((absolute, absolute + count, source_start))
    return rows


class AudioTimelineTests(unittest.TestCase):
    def test_one_wav_stays_continuous_across_all_camera_cuts(self):
        xml, plan = edit_fixture()
        before = copy.deepcopy(plan)
        result_xml, result = add_primary_audio(xml, plan, chosen(audio_file(1000, 180)))
        self.assertEqual(plan, before)
        self.assertIsNot(result, plan)
        self.assertTrue(result['audio_embedded'])
        self.assertEqual(result['audio_assembly'], [dict(path='/fixture/Audio Source Files/Show CAM 8 01.wav',
                         start=1000, end=1180, frames=180, source_start=0,
                         channels=2, sample_rate=48000, session=0)])
        root, original = ET.fromstring(result_xml), ET.fromstring(xml)
        self.assertEqual(len(root.findall('.//spine/mc-clip')), 3)
        self.assertEqual(len(root.findall('.//spine/mc-clip/clip/audio')), 1)
        self.assertEqual(root.findall('.//multicam//audio'), [])
        self.assertEqual(imported_audio_geometry(result_xml, Timing()), [(1000, 1180, 0)])
        parent = root.find('.//spine/mc-clip')
        self.assertLess(seconds(parent.get('duration')), seconds(parent.find('clip').get('duration')))
        for previous, current in zip(original.findall('.//spine/mc-clip'), root.findall('.//spine/mc-clip')):
            self.assertEqual(previous.attrib, current.attrib)
            self.assertEqual(previous.find('mc-source').attrib, current.find('mc-source').attrib)

    def test_stereo_default_mapping_omits_srcch_and_has_audio_only_component(self):
        xml, plan = edit_fixture()
        xml, _ = add_primary_audio(xml, plan, chosen(audio_file(1000, 180)))
        root = ET.fromstring(xml)
        audio = root.find('.//spine/mc-clip/clip/audio')
        clip = root.find('.//spine/mc-clip/clip')
        resource = next(node for node in root.findall('./resources/asset') if node.get('id') == audio.get('ref'))
        self.assertNotIn('srcCh', audio.attrib)
        self.assertEqual(clip.get('lane'), '-1')
        self.assertEqual([node.tag for node in clip], ['audio'])
        self.assertEqual((resource.get('hasVideo'), resource.get('hasAudio'), resource.get('audioSources'),
                          resource.get('audioChannels'), resource.get('audioRate')), ('0', '1', '1', '2', '48000'))
        self.assertEqual(seconds(resource.get('start')), 0)
        self.assertEqual(seconds(audio.get('start')), 0)
        self.assertIn('Audio%20Source%20Files', resource.get('src'))

    def test_contiguous_chunks_anchor_inside_nonzero_multicam_source_start(self):
        xml, plan = edit_fixture()
        xml, result = add_primary_audio(xml, plan, chosen(audio_file(1045, 135, 2), audio_file(1000, 45)))
        self.assertEqual(imported_audio_geometry(xml, Timing()), [(1000, 1045, 0), (1045, 1180, 0)])
        second_parent = ET.fromstring(xml).findall('.//spine/mc-clip')[1]
        self.assertEqual(seconds(second_parent.get('start')) * Timing().fps, 30)
        self.assertEqual(seconds(second_parent.find('clip').get('offset')) * Timing().fps, 45)
        self.assertEqual([row['start'] for row in result['audio_assembly']], [1000, 1045])

    def test_two_sessions_keep_gap_and_wav02_spans_video_parts02_and03(self):
        sessions = [(1000, [90], [(0, 1), (30, 2)]),
                    (1390, [60, 90], [(0, 2), (40, 1), (60, 2), (120, 1)])]
        xml, plan = edit_fixture(sessions=sessions)
        xml, result = add_primary_audio(xml, plan, chosen(audio_file(1000, 90), audio_file(1390, 150, 2)))
        self.assertEqual(imported_audio_geometry(xml, Timing()), [(1000, 1090, 0), (1390, 1540, 0)])
        self.assertEqual([row['session'] for row in result['audio_assembly']], [0, 1])
        gap = ET.fromstring(xml).find('.//spine/gap')
        self.assertEqual(gap.get('name'), 'Not recording')
        self.assertEqual(gap.findall('clip'), [])
        self.assertEqual(len(ET.fromstring(xml).findall('.//spine/*/clip/audio')), 2)
        session2 = ET.fromstring(xml).findall('./resources/media')[1]
        self.assertEqual(len(session2.findall('.//mc-angle/clip')), 4)

    def test_audio_can_anchor_to_switcher_black_without_hiding_it(self):
        xml, plan = edit_fixture(sessions=[(1000, [60], [(0, 0), (15, 1), (30, 2)])])
        xml, _ = add_primary_audio(xml, plan, chosen(audio_file(1000, 5), audio_file(1005, 55, 2)))
        root = ET.fromstring(xml)
        black = root.find('.//spine/gap')
        self.assertEqual(black.get('name'), 'Switcher black')
        self.assertEqual(len(black.findall('clip/audio')), 2)
        self.assertEqual(imported_audio_geometry(xml, Timing()), [(1000, 1005, 0), (1005, 1060, 0)])

    def test_drop_frame_minute_boundary_is_exact(self):
        timing = Timing()
        origin = timing.frames('00:00:59;28')
        xml, plan = edit_fixture(timing, [(origin, [60], [(0, 1), (2, 2), (32, 1)])])
        xml, result = add_primary_audio(xml, plan, chosen(audio_file(origin, 60)))
        self.assertEqual(timing.timecode(plan['cuts'][1]['start']), '00:01:00;02')
        self.assertEqual(imported_audio_geometry(xml, timing), [(origin, origin + 60, 0)])
        self.assertEqual(result['cuts'], plan['cuts'])

    def test_program_media_clock_wraps_at_midnight_but_edit_remains_absolute(self):
        timing = Timing()
        start = timing.day - 30
        sessions = [(start, [60], [(0, 1), (30, 2)]),
                    (timing.day + 330, [60], [(0, 2), (30, 1)])]
        xml, plan = edit_fixture(timing, sessions)
        files = [audio_file(start, 60, path='/fixture/program01.mp4'),
                 audio_file(timing.day + 330, 60, path='/fixture/program02.mp4')]
        xml, result = add_primary_audio(xml, plan, chosen(*files, source='program'))
        root = ET.fromstring(xml)
        assets = [node for node in root.findall('./resources/asset') if node.get('id').startswith('primary_audio_')]
        self.assertEqual([seconds(node.get('start')) * timing.fps for node in assets], [start, 330])
        self.assertTrue(all(node.get('hasVideo') == '1' for node in assets))
        self.assertEqual(root.findall('.//spine/*/clip/video'), [])
        self.assertEqual(root.findall('.//spine/asset-clip'), [])
        self.assertEqual(imported_audio_geometry(xml, timing), [(start, start + 60, 0), (timing.day + 330, timing.day + 390, 0)])
        self.assertEqual([row['source_start'] for row in result['audio_assembly']], [0, 0])

    def test_exact_rational_audio_geometry_at_all_supported_rates(self):
        for rate in ('24000/1001', '24', '25', '30000/1001', '30', '50', '60000/1001', '60'):
            for drop in ((False, True) if rate in ('30000/1001', '60000/1001') else (False,)):
                with self.subTest(rate=rate, drop=drop):
                    timing = Timing(rate, drop)
                    origin = timing.frames('01:00:00;00' if drop else '01:00:00:00')
                    xml, plan = edit_fixture(timing, [(origin, [60], [(0, 1), (25, 2)])])
                    xml, _ = add_primary_audio(xml, plan, chosen(audio_file(origin, 60)))
                    self.assertEqual(imported_audio_geometry(xml, timing), [(origin, origin + 60, 0)])

    def test_audio_inventory_can_supply_verified_channel_metadata(self):
        xml, plan = edit_fixture()
        source = audio_file(1000, 180)
        plan['audio_inventory'] = [copy.deepcopy(source)]
        del source['channels'], source['sample_rate']
        xml, result = add_primary_audio(xml, plan, dict(selected='cam8', files=[source]))
        self.assertEqual(result['audio_assembly'][0]['channels'], 2)

    def test_bwf_source_clocks_do_not_shift_verified_session_placement(self):
        timing = Timing()
        xml, plan = edit_fixture(sessions=[(109682, [60], [(0, 1), (30, 2)]),
                                          (111480, [60, 60], [(0, 1), (60, 2)])])
        files = [audio_file(109682, 60), audio_file(111480, 120, 2)]
        plan['audio_inventory'] = [dict(path=files[0]['path'], tags={'time_reference': '175666691'}),
                                   dict(path=files[1]['path'], tags={'time_reference': '178642464'})]
        xml, result = add_primary_audio(xml, plan, chosen(*files))
        root = ET.fromstring(xml)
        assets = [node for node in root.findall('./resources/asset') if node.get('id').startswith('primary_audio_')]
        # The first BWF value is just below an integer frame. Its FCPXML floor
        # is109681; Resolve's native displayed Start TC rounds to109682.
        self.assertEqual([seconds(node.get('start')) * timing.fps for node in assets], [109681, 111540])
        self.assertEqual(imported_audio_geometry(xml, timing), [(109682, 109742, 0), (111480, 111600, 0)])
        self.assertEqual([row['source_start'] for row in result['audio_assembly']], [0, 0])
        self.assertEqual([row['start'] for row in result['audio_assembly']], [109682, 111480])
        self.assertEqual(result['cuts'], plan['cuts'])

    def test_bwf_sample_clock_floor_at_every_supported_rate(self):
        expected = {'24000/1001': 87745, '24': 87833, '25': 91493, '30000/1001': 109681,
                    '30': 109791, '50': 182986, '60000/1001': 219363, '60': 219583}
        for rate, source_frame in expected.items():
            for drop in ((False, True) if rate in ('30000/1001', '60000/1001') else (False,)):
                with self.subTest(rate=rate, drop=drop):
                    timing = Timing(rate, drop)
                    xml, plan = edit_fixture(timing, [(1000, [60], [(0, 1), (30, 2)])])
                    source = audio_file(1000, 60)
                    plan['audio_inventory'] = [dict(path=source['path'], tags={'time_reference': 175666691})]
                    xml, _ = add_primary_audio(xml, plan, chosen(source))
                    asset = next(node for node in ET.fromstring(xml).findall('./resources/asset')
                                 if node.get('id').startswith('primary_audio_'))
                    self.assertEqual(seconds(asset.get('start')) * timing.fps, source_frame)
                    self.assertEqual(imported_audio_geometry(xml, timing), [(1000, 1060, 0)])

    def test_bwf_clock_wraps_at_timecode_day_without_moving_audio(self):
        timing = Timing('25', False)
        xml, plan = edit_fixture(timing, [(1000, [60], [(0, 1), (30, 2)])])
        source = audio_file(1000, 60)
        plan['audio_inventory'] = [dict(path=source['path'], tags={'time_reference': str((86400 * 2 + 1) * 48000)})]
        xml, _ = add_primary_audio(xml, plan, chosen(source))
        asset = next(node for node in ET.fromstring(xml).findall('./resources/asset')
                     if node.get('id').startswith('primary_audio_'))
        self.assertEqual(seconds(asset.get('start')) * timing.fps, 25)
        self.assertEqual(imported_audio_geometry(xml, timing), [(1000, 1060, 0)])

    def test_zero_bwf_reference_is_a_valid_zero_source_clock(self):
        for value in (0, '0'):
            with self.subTest(value=value):
                xml, plan = edit_fixture()
                source = audio_file(1000, 180)
                plan['audio_inventory'] = [dict(path=source['path'], tags={'time_reference': value})]
                xml, _ = add_primary_audio(xml, plan, chosen(source))
                asset = next(node for node in ET.fromstring(xml).findall('./resources/asset')
                             if node.get('id').startswith('primary_audio_'))
                self.assertEqual(seconds(asset.get('start')), 0)

    def test_invalid_bwf_reference_is_rejected_without_partial_insertion(self):
        for value in (-1, '-1', '1.5', 1.5, True, '', '1/2', 'NaN', {}, []):
            with self.subTest(value=value):
                xml, plan = edit_fixture()
                source = audio_file(1000, 180)
                plan['audio_inventory'] = [dict(path=source['path'], tags={'time_reference': value})]
                before = copy.deepcopy(plan)
                with self.assertRaisesRegex(ValueError, 'nonnegative integer sample count'):
                    add_primary_audio(xml, plan, chosen(source))
                self.assertEqual(plan, before)

    def test_resource_ids_are_unique_even_with_existing_prefix(self):
        xml, plan = edit_fixture()
        root = ET.fromstring(xml)
        ET.SubElement(root.find('resources'), 'format', id='primary_audio_0', frameDuration='1/25s')
        xml, _ = add_primary_audio(ET.tostring(root), plan, chosen(audio_file(1000, 180)))
        root = ET.fromstring(xml)
        ids = [node.get('id') for node in root.iter() if node.get('id')]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(root.find('.//spine/mc-clip/clip/audio').get('ref'), 'primary_audio_0_')

    def test_duplicate_insertion_and_partial_connected_content_are_rejected(self):
        xml, plan = edit_fixture()
        selection = chosen(audio_file(1000, 180))
        embedded, embedded_plan = add_primary_audio(xml, plan, selection)
        with self.assertRaisesRegex(ValueError, 'already embedded'):
            add_primary_audio(embedded, embedded_plan, selection)
        with self.assertRaisesRegex(ValueError, 'connected content'):
            add_primary_audio(embedded, plan, selection)
        root = ET.fromstring(xml)
        ET.SubElement(root.find('.//spine/mc-clip'), 'clip', lane='-1')
        with self.assertRaisesRegex(ValueError, 'connected content'):
            add_primary_audio(ET.tostring(root), plan, selection)

    def test_missing_gap_overlap_extra_and_duplicate_audio_are_rejected(self):
        xml, plan = edit_fixture()
        selections = [chosen(), chosen(audio_file(1000, 175)),
                      chosen(audio_file(1000, 60), audio_file(1065, 115, 2)),
                      chosen(audio_file(1000, 90), audio_file(1085, 95, 2)),
                      chosen(audio_file(1000, 180), audio_file(1200, 60, 2)),
                      chosen(audio_file(1000, 90), audio_file(1090, 90))]
        for selection in selections:
            with self.subTest(files=selection['files']):
                before = copy.deepcopy(plan)
                with self.assertRaises(ValueError): add_primary_audio(xml, plan, selection)
                self.assertEqual(plan, before)

    def test_audio_crossing_real_recording_gap_is_rejected(self):
        xml, plan = edit_fixture(sessions=[(1000, [60], [(0, 1)]), (1360, [60], [(0, 2)])])
        with self.assertRaisesRegex(ValueError, 'crosses a recording gap'):
            add_primary_audio(xml, plan, chosen(audio_file(1000, 420)))

    def test_invalid_audio_duration_channel_rate_or_path_is_rejected(self):
        xml, plan = edit_fixture()
        for key, value in [('frames', 179), ('end', 1179), ('channels', 1), ('sample_rate', 44100),
                           ('path', 'relative.wav'), ('frames', 180.5), ('frames', True)]:
            with self.subTest(key=key, value=value):
                source = audio_file(1000, 180)
                source[key] = value
                with self.assertRaises(ValueError): add_primary_audio(xml, plan, chosen(source))

    def test_missing_metadata_is_not_assumed_stereo(self):
        xml, plan = edit_fixture()
        source = audio_file(1000, 180)
        del source['channels']
        with self.assertRaises(ValueError): add_primary_audio(xml, plan, chosen(source))

    def test_camera_audio_or_changed_cut_geometry_is_rejected(self):
        xml, plan = edit_fixture()
        for change in ('camera-audio', 'offset', 'format'):
            with self.subTest(change=change):
                root = ET.fromstring(xml)
                if change == 'camera-audio': root.find('.//spine/mc-clip/mc-source').set('srcEnable', 'all')
                elif change == 'offset': root.find('.//spine/mc-clip').set('offset', '0s')
                else: root.find('./resources/format').set('frameDuration', '1/25s')
                with self.assertRaises(ValueError):
                    add_primary_audio(ET.tostring(root), plan, chosen(audio_file(1000, 180)))


if __name__ == '__main__':
    unittest.main()
