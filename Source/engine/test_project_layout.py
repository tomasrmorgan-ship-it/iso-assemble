"""Project organization and edit selection with documented API stand-ins."""
import unittest

from project_layout import (BINS, inspect_edit_session, inspect_project_layout,
                            organize_project, select_edit_session)
from timing import Timing


class Media:
    def __init__(self, uid, name, kind='Video', path=''):
        self.uid, self.name, self.kind, self.path = uid, name, kind, path

    def GetUniqueId(self): return self.uid
    def GetName(self): return self.name
    def GetClipProperty(self, key):
        return {'Type': self.kind, 'File Path': self.path}[key]


class Folder:
    def __init__(self, uid, name, clips=None):
        self.uid, self.name = uid, name
        self.clips, self.children = list(clips or []), []

    def GetUniqueId(self): return self.uid
    def GetName(self): return self.name
    def GetClipList(self): return list(self.clips)
    def GetSubFolderList(self): return list(self.children)


class Pool:
    def __init__(self, root):
        self.root = self.current = root
        self.moves, self.created = [], []
        self.fail_move = self.lie_move = self.fail_folder = self.lie_select = False

    def GetRootFolder(self): return self.root
    def GetCurrentFolder(self): return self.current

    def AddSubFolder(self, parent, name):
        if self.fail_folder: return None
        folder = Folder('folder-' + str(len(self.created)), name)
        parent.children.append(folder)
        self.created.append(folder)
        return folder

    def MoveClips(self, clips, target):
        self.moves.append((list(clips), target))
        if self.fail_move: return False
        if self.lie_move: return True

        def remove(folder, clip):
            if clip in folder.clips: folder.clips.remove(clip)
            for child in folder.children: remove(child, clip)

        for clip in clips:
            remove(self.root, clip)
            target.clips.append(clip)
        return True

    def SetCurrentFolder(self, folder):
        if not self.lie_select: self.current = folder
        return True


class Video:
    def __init__(self, start, end, name, media):
        self.start, self.end, self.name, self.media = start, end, name, media

    def GetStart(self): return self.start
    def GetEnd(self): return self.end
    def GetName(self): return self.name
    def GetMediaPoolItem(self): return self.media


class Timeline:
    def __init__(self, uid, name, media):
        self.uid, self.name, self.media = uid, name, media
        self.timecode, self.video = '00:00:00;00', None
        self.fail_timecode = self.lie_timecode = False
        self.seeks = []

    def GetUniqueId(self): return self.uid
    def GetName(self): return self.name
    def GetMediaPoolItem(self): return self.media
    def GetCurrentTimecode(self): return self.timecode
    def GetCurrentVideoItem(self): return self.video

    def SetCurrentTimecode(self, timecode):
        self.seeks.append(timecode)
        if self.fail_timecode: return False
        if not self.lie_timecode: self.timecode = timecode
        return True


class Project:
    def __init__(self, pool, timelines):
        self.pool, self.timelines = pool, timelines
        self.current = timelines[-1]
        self.fail_timeline = self.lie_timeline = False

    def GetMediaPool(self): return self.pool
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]
    def GetCurrentTimeline(self): return self.current

    def SetCurrentTimeline(self, timeline):
        if self.fail_timeline: return False
        if not self.lie_timeline: self.current = timeline
        return True


class Resolve:
    def __init__(self):
        self.page = 'media'
        self.fail_page = self.lie_page = False

    def OpenPage(self, page):
        if self.fail_page: return False
        if not self.lie_page: self.page = page
        return True

    def GetCurrentPage(self): return self.page


def fixture():
    plan = dict(name='Example', origin=0, timing=dict(fps='30000/1001', drop=True),
                media=[dict(path='/footage/cam1.mov', camera=1),
                       dict(path='/footage/cam2.mov', camera=2)],
                audio_inventory=[dict(path='/footage/mic.wav', kind='audio_iso'),
                                 dict(path='/footage/program.mp4', kind='program_or_other',
                                      tags={'com.apple.proapps.cameraName': '0'}),
                                 dict(path='/footage/unrelated.mp4', kind='program_or_other')],
                sessions=[dict(multicam_name='Example_Session_01', start=1790, end=1900)],
                cuts=[dict(start=0, end=1790, angle=None),
                      dict(start=1790, end=1800, angle=0, session=0),
                      dict(start=1800, end=1830, angle=2, session=0),
                      dict(start=1830, end=1900, angle=1, session=0)],
                camera_names={'1': 'Camera 1', '2': 'Camera 2'})
    camera1 = Media('cam1', 'cam1.mov', path='/footage/cam1.mov')
    camera2 = Media('cam2', 'cam2.mov', path='/footage/cam2.mov')
    audio = Media('audio', 'mic.wav', 'Audio', '/footage/mic.wav')
    program = Media('program', 'program.mp4', path='/footage/program.mp4')
    multicam = Media('mc', 'Example_Session_01', 'Multicam')
    edit = Timeline('edit-timeline', 'Example_Edit', Media('edit-pool', 'Example_Edit', 'Timeline'))
    reference = Timeline('ref-timeline', 'Example_Live_Program_Reference',
                         Media('ref-pool', 'Example_Live_Program_Reference', 'Timeline'))
    edit.video = Video(1800, 1830, 'Example_Session_01 - 2 Camera 2', multicam)
    root = Folder('root', 'Master', [camera1, camera2, audio, program, multicam,
                                    edit.media, reference.media])
    user = Folder('user-folder', 'My media', [Media('user', 'unrelated.mp4', path='/footage/unrelated.mp4'),
                                           Media('user-mc', 'Other Multicam', 'Multicam')])
    root.children.append(user)
    project = Project(Pool(root), [edit, reference])
    return plan, project, edit, Resolve()


class LayoutTests(unittest.TestCase):
    def test_organizes_known_sources_and_preserves_unrelated_items(self):
        plan, project, _, _ = fixture()
        user = project.pool.root.children[0]
        originals = list(user.clips)
        report = organize_project(project, plan)
        self.assertEqual(report['moved_items'], 7)
        self.assertEqual(report['unknown_items_preserved'], 2)
        self.assertEqual(user.clips, originals)
        self.assertEqual(report['bins']['01 Edit']['item_ids'], ['edit-pool'])
        self.assertEqual(report['bins']['02 Multicam']['item_ids'], ['mc'])
        self.assertEqual(report['bins']['03 Camera Originals/Camera 1']['item_ids'], ['cam1'])
        self.assertEqual(report['bins']['03 Camera Originals/Camera 2']['item_ids'], ['cam2'])
        self.assertEqual(report['bins']['04 Audio ISOs']['item_ids'], ['audio'])
        self.assertEqual(report['bins']['05 Program Reference']['item_ids'], ['program', 'ref-pool'])
        self.assertEqual(report['missing_program_paths'], [])

    def test_rerun_and_read_only_inspection_create_no_duplicates(self):
        plan, project, _, _ = fixture()
        organize_project(project, plan)
        calls = (len(project.pool.created), len(project.pool.moves))
        again = organize_project(project, plan)
        readback = inspect_project_layout(project, plan)
        self.assertEqual(again['moved_items'], 0)
        self.assertEqual(again, readback)
        self.assertEqual(calls, (len(project.pool.created), len(project.pool.moves)))

    def test_explicit_program_paths_and_selected_program_are_supported(self):
        plan, project, _, _ = fixture()
        plan['audio_inventory'][1].pop('tags')
        plan['program_files'] = [dict(path='/footage/program.mp4'), '/footage/spanned.mp4']
        plan['audio'] = dict(selected='program', files=[dict(path='/footage/program.mp4')])
        report = organize_project(project, plan)
        self.assertEqual(report['missing_program_paths'], ['/footage/spanned.mp4'])
        self.assertIn('program', report['bins']['05 Program Reference']['item_ids'])

    def test_missing_source_is_rejected_before_mutating(self):
        plan, project, _, _ = fixture()
        plan['media'][0]['path'] = '/footage/missing.mov'
        with self.assertRaisesRegex(RuntimeError, 'Imported source is missing'):
            organize_project(project, plan)
        self.assertEqual(project.pool.created, [])
        self.assertEqual(project.pool.moves, [])

    def test_duplicate_source_or_multicam_is_rejected_before_mutating(self):
        for duplicate in (Media('dup', 'copy', path='/footage/cam1.mov'),
                          Media('dup', 'Example_Session_01', 'Multicam')):
            with self.subTest(kind=duplicate.kind):
                plan, project, _, _ = fixture()
                project.pool.root.clips.append(duplicate)
                with self.assertRaises(RuntimeError): organize_project(project, plan)
                self.assertEqual(project.pool.created, [])
                self.assertEqual(project.pool.moves, [])

    def test_conflicting_source_roles_are_rejected_before_mutating(self):
        plan, project, _, _ = fixture()
        plan['media'].append(dict(path='/footage/cam1.mov', camera=2))
        with self.assertRaisesRegex(RuntimeError, 'different media bins'):
            organize_project(project, plan)
        self.assertEqual(project.pool.created, [])

    def test_duplicate_target_bin_is_not_chosen_arbitrarily(self):
        plan, project, _, _ = fixture()
        project.pool.root.children.extend([Folder('one', '01 Edit'), Folder('two', '01 Edit')])
        with self.assertRaisesRegex(RuntimeError, 'Duplicate media bin'):
            organize_project(project, plan)
        self.assertEqual(project.pool.moves, [])

    def test_move_false_or_unapplied_success_is_reported(self):
        for flag in ('fail_move', 'lie_move'):
            with self.subTest(flag=flag):
                plan, project, _, _ = fixture()
                setattr(project.pool, flag, True)
                with self.assertRaises(RuntimeError): organize_project(project, plan)

    def test_bin_create_failure_is_reported(self):
        plan, project, _, _ = fixture()
        project.pool.fail_folder = True
        with self.assertRaisesRegex(RuntimeError, 'could not create'):
            organize_project(project, plan)

    def test_inspection_detects_misplaced_owned_item_without_fixing_it(self):
        plan, project, _, _ = fixture()
        organize_project(project, plan)
        camera_bin = next(f for f in project.pool.created if f.name == 'Camera 1')
        camera = camera_bin.clips.pop()
        project.pool.root.clips.append(camera)
        calls = len(project.pool.moves)
        with self.assertRaisesRegex(RuntimeError, 'outside its expected bin'):
            inspect_project_layout(project, plan)
        self.assertEqual(len(project.pool.moves), calls)
        self.assertIn(camera, project.pool.root.clips)

    def test_missing_or_duplicate_edit_is_rejected(self):
        for duplicate in (False, True):
            plan, project, edit, _ = fixture()
            if duplicate: project.timelines.append(edit)
            else: project.timelines.remove(edit)
            with self.assertRaisesRegex(RuntimeError, 'Expected one finished edit'):
                organize_project(project, plan)
            self.assertEqual(project.pool.moves, [])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.project, self.edit, self.resolve = fixture()
        organize_project(self.project, self.plan)

    def test_opens_real_cut_after_gap_and_black_with_drop_frame_readback(self):
        result = select_edit_session(self.resolve, self.project, self.plan)
        self.assertEqual(result['timeline_id'], 'edit-timeline')
        self.assertEqual(result['frame'], 1800)
        self.assertEqual(result['timecode'], '00:01:00;02')
        self.assertEqual(result['angle'], 2)
        self.assertEqual(self.resolve.page, 'edit')
        self.assertEqual(self.project.pool.current.name, BINS[0])
        self.assertIs(self.project.current, self.edit)
        self.assertEqual(self.edit.seeks, ['00:01:00;02'])

    def test_midnight_wrap_uses_integer_frame_timecode(self):
        day = Timing.from_plan(self.plan).day
        for cut in self.plan['cuts']:
            cut['start'] += day
            cut['end'] += day
        self.edit.video.start += day
        self.edit.video.end += day
        result = select_edit_session(self.resolve, self.project, self.plan)
        self.assertEqual(result['frame'], day + 1800)
        self.assertEqual(result['timecode'], '00:01:00;02')

    def test_wrong_day_video_item_is_detected_even_when_timecode_matches(self):
        for cut in self.plan['cuts']:
            cut['start'] += Timing.from_plan(self.plan).day
            cut['end'] += Timing.from_plan(self.plan).day
        with self.assertRaisesRegex(RuntimeError, 'expected first native multicam cut'):
            select_edit_session(self.resolve, self.project, self.plan)

    def test_no_video_cuts_fails_before_changing_selection(self):
        self.plan['cuts'] = self.plan['cuts'][:2]
        before = self.project.current
        with self.assertRaisesRegex(RuntimeError, 'no actual multicam cut'):
            select_edit_session(self.resolve, self.project, self.plan)
        self.assertIs(self.project.current, before)

    def test_failed_or_false_success_api_calls_are_detected(self):
        for owner, flag in (('project', 'fail_timeline'), ('project', 'lie_timeline'),
                            ('resolve', 'fail_page'), ('resolve', 'lie_page'),
                            ('edit', 'fail_timecode'), ('edit', 'lie_timecode'),
                            ('pool', 'lie_select')):
            with self.subTest(flag=flag):
                plan, project, edit, resolve = fixture()
                organize_project(project, plan)
                setattr({'project': project, 'resolve': resolve, 'edit': edit,
                         'pool': project.pool}[owner], flag, True)
                with self.assertRaises(RuntimeError): select_edit_session(resolve, project, plan)

    def test_wrong_angle_or_non_native_item_is_detected(self):
        for change in ('angle', 'kind', 'gap'):
            with self.subTest(change=change):
                plan, project, edit, resolve = fixture()
                organize_project(project, plan)
                if change == 'angle': edit.video.name = 'Example_Session_01 - 1 Camera 1'
                elif change == 'kind': edit.video.media.kind = 'Video'
                else: edit.video = None
                with self.assertRaisesRegex(RuntimeError, 'expected first native multicam cut'):
                    select_edit_session(resolve, project, plan)


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.project, self.edit, self.resolve = fixture()
        organize_project(self.project, self.plan)
        select_edit_session(self.resolve, self.project, self.plan)

    def test_strict_readback_verifies_first_cut_without_mutations(self):
        before = (len(self.project.pool.moves), len(self.project.pool.created),
                  list(self.edit.seeks), self.project.current, self.project.pool.current)
        result = inspect_edit_session(self.project, self.plan, require_first_cut=True)
        self.assertEqual(result['frame'], 1800)
        self.assertEqual(result['timecode_frame'], 1800)
        self.assertEqual(result['timecode'], '00:01:00;02')
        self.assertTrue(result['native_multicam_at_playhead'])
        self.assertTrue(result['first_cut_verified'])
        self.assertTrue(result['selected_edit_bin'])
        self.assertEqual(before, (len(self.project.pool.moves), len(self.project.pool.created),
                                  list(self.edit.seeks), self.project.current, self.project.pool.current))

    def test_different_timeline_identity_fails_even_if_name_matches(self):
        self.project.current = Timeline('wrong-id', 'Example_Edit', self.edit.media)
        with self.assertRaisesRegex(RuntimeError, 'not the current timeline'):
            inspect_edit_session(self.project, self.plan)
        self.assertEqual(self.project.current.uid, 'wrong-id')

    def test_default_reports_unpersisted_playhead_and_bin_without_reselection(self):
        self.edit.timecode = '00:00:00;00'
        self.edit.video = None
        self.project.pool.current = self.project.pool.root
        result = inspect_edit_session(self.project, self.plan)
        self.assertEqual(result['timecode'], '00:00:00;00')
        self.assertIsNone(result['frame'])
        self.assertFalse(result['native_multicam_at_playhead'])
        self.assertFalse(result['first_cut_verified'])
        self.assertFalse(result['selected_edit_bin'])
        self.assertIs(self.project.pool.current, self.project.pool.root)
        with self.assertRaisesRegex(RuntimeError, 'expected first native multicam cut'):
            inspect_edit_session(self.project, self.plan, require_first_cut=True)

    def test_strict_cut_does_not_require_bin_selection_to_persist(self):
        self.project.pool.current = self.project.pool.root
        result = inspect_edit_session(self.project, self.plan, require_first_cut=True)
        self.assertTrue(result['first_cut_verified'])
        self.assertFalse(result['selected_edit_bin'])

    def test_strict_readback_rejects_wrong_angle_and_position(self):
        for change in ('angle', 'position'):
            with self.subTest(change=change):
                plan, project, edit, resolve = fixture()
                organize_project(project, plan)
                select_edit_session(resolve, project, plan)
                if change == 'angle': edit.video.name = 'Example_Session_01 - 1 Camera 1'
                else: edit.timecode = '00:01:00;03'
                with self.assertRaisesRegex(RuntimeError, 'expected first native multicam cut'):
                    inspect_edit_session(project, plan, require_first_cut=True)

    def test_absolute_frame_is_recovered_after_midnight(self):
        day = Timing.from_plan(self.plan).day
        for cut in self.plan['cuts']:
            cut['start'] += day
            cut['end'] += day
        self.edit.video.start += day
        self.edit.video.end += day
        result = inspect_edit_session(self.project, self.plan, require_first_cut=True)
        self.assertEqual(result['frame'], day + 1800)
        self.assertEqual(result['timecode_frame'], 1800)


if __name__ == '__main__':
    unittest.main()
