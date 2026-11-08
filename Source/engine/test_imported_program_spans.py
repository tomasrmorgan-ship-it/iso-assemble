"""Missing rollover paths need exact native span evidence, not filename guesses."""
import copy
import unittest

from imported_program_spans import verified_program_spans
from timing import Timing


class Media:
    def __init__(self, path, start, frames, timing):
        self.values = {'File Path':path, 'Start TC':timing.timecode(start), 'Frames':str(frames)}
    def GetClipProperty(self, key): return self.values.get(key)


class ProgramSpanTests(unittest.TestCase):
    def setUp(self):
        self.timing = Timing()
        self.rows = [dict(path=f'/footage/Program {part:02d}.mp4', start=start, frames=60)
                     for part, start in ((1,107892), (2,111480), (3,111540))]
        self.pool = {row['path']:Media(row['path'],row['start'],120 if index==1 else 60,self.timing)
                     for index,row in enumerate(self.rows[:2])}
    def verify(self): return verified_program_spans(self.rows,self.pool,self.timing)
    def test_native_120_frame_source_exactly_covers_two_60_frame_rollovers(self):
        before = copy.deepcopy(self.rows); report = self.verify()
        self.assertEqual(report['covered_missing_paths'],[self.rows[2]['path']])
        self.assertEqual(report['unresolved_program_paths'],[])
        self.assertEqual(report['spans'][0]['start'],111480)
        self.assertEqual(report['spans'][0]['end'],111600)
        self.assertEqual(report['spans'][0]['files'],[row['path'] for row in self.rows[1:]])
        self.assertEqual(self.rows,before)
    def test_a_missing_file_without_native_span_evidence_stays_missing(self):
        self.pool[self.rows[1]['path']].values['Frames']='60'
        report=self.verify()
        self.assertEqual(report['covered_missing_paths'],[])
        self.assertEqual(report['unresolved_program_paths'],[self.rows[2]['path']])
    def test_native_start_timecode_must_match_verified_first_file(self):
        self.pool[self.rows[1]['path']].values['Start TC']=self.timing.timecode(111481)
        with self.assertRaisesRegex(RuntimeError,'different timecode'):self.verify()
    def test_real_gap_or_overlap_cannot_be_hidden_by_a_native_span(self):
        for offset in (-1,1):
            rows=copy.deepcopy(self.rows);rows[2]['start']+=offset
            with self.subTest(offset=offset),self.assertRaisesRegex(RuntimeError,'tiled exactly'):
                verified_program_spans(rows,self.pool,self.timing)
    def test_native_end_cannot_cut_through_or_exceed_verified_files(self):
        for count in (119,121,180):
            self.pool[self.rows[1]['path']].values['Frames']=str(count)
            with self.subTest(count=count),self.assertRaises(RuntimeError):self.verify()
    def test_native_start_path_and_frame_metadata_are_mandatory(self):
        for key,value in (('File Path','/other.mov'),('Start TC',None),('Frames','unknown'),('Frames','59')):
            original=self.pool[self.rows[1]['path']].values[key]
            self.pool[self.rows[1]['path']].values[key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError):self.verify()
            self.pool[self.rows[1]['path']].values[key]=original
    def test_unwrapped_midnight_continuity_uses_native_frame_of_day(self):
        rows=[dict(path='/p02.mp4',start=self.timing.day-60,frames=60),
              dict(path='/p03.mp4',start=self.timing.day,frames=60)]
        pool={'/p02.mp4':Media('/p02.mp4',rows[0]['start'],120,self.timing)}
        report=verified_program_spans(rows,pool,self.timing)
        self.assertEqual(report['covered_missing_paths'],['/p03.mp4'])
    def test_audio_iso_paths_are_never_excused(self):
        report=self.verify()
        self.assertNotIn('/footage/CAM 8 02.wav',report['covered_missing_paths'])
        self.assertEqual(set(report['covered_missing_paths']),{self.rows[2]['path']})


if __name__=='__main__':unittest.main()
