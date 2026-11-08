import unittest
from unittest.mock import patch
from atem import frames,merge,parse,preflight
from pathlib import Path
import tempfile,json
class TimingTests(unittest.TestCase):
 def test_drop_minute(self):
  self.assertEqual(frames('00:01:00;02')-frames('00:00:59;29'),1)
  self.assertEqual(frames('00:10:00;00')-frames('00:09:59;29'),1)
  self.assertEqual(frames('01:00:00;00'),107892)
  with self.assertRaises(ValueError):frames('00:01:00;00')
 def test_partial_indexed_updates(self):
  initial={'sources':[{'_index_':1,'name':'Camera 1','file':'01.mp4'},{'_index_':2,'name':'Camera 2'}]}
  result=merge(initial,{'sources':[{'_index_':1,'file':'03.mp4'}]})
  self.assertEqual(result['sources'][0]['name'],'Camera 1')
  self.assertEqual(result['sources'][1]['name'],'Camera 2')
  self.assertEqual(initial['sources'][0]['file'],'01.mp4')
 def test_rollover_and_repeated_header(self):
  records=[{'videoMode':'1080p29.97','version':1,'recordingId':'a','masterTimecode':'23:59:59;29','mixEffectBlocks':[{'_index_':0,'source':3,'onAir':True}]},{'videoMode':'1080p29.97','version':1,'recordingId':'a','masterTimecode':'00:00:00;00','mixEffectBlocks':[{'_index_':0,'source':4}]}]
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'input.drp';p.write_text('\n'.join(map(json.dumps,records)));ev,_=parse(p)
  self.assertEqual(ev[1]['frame']-ev[0]['frame'],1)
  self.assertEqual(ev[1]['session'],0)
  self.assertTrue(ev[1]['state']['mixEffectBlocks'][0]['onAir'])
 def test_truncated_record_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'input.drp';p.write_text('{"masterTimecode":')
   with self.assertRaisesRegex(ValueError,'line 1'):parse(p)
class LateSourceMetadataTests(unittest.TestCase):
 def header(self,tc='00:00:00;00',recording='a'):
  return dict(videoMode='1080p29.97',recordingId=recording,masterTimecode=tc,
   sources=[dict(_index_=1,name='Camera 1',type='Video',file='01.mp4',startTimecode=tc)],
   mixEffectBlocks=[dict(_index_=0,source=1,onAir=True,transitionActive=False)])
 def control(self,tc,**update):
  return dict(masterTimecode=tc,mixEffectBlocks=[dict(_index_=0,**update)])
 def metadata(self,tc,file='03.mp4'):
  return dict(masterTimecode=tc,sources=[dict(_index_=1,file=file,startTimecode=tc,volume='Disk',projectPath='Session'),
   dict(_index_=12,volume='Disk',projectPath='Session',startTimecode='00:00:00:00')])
 def parse_records(self,records):
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'input.drp';p.write_text('\n'.join(map(json.dumps,records)))
   return parse(p)
 def test_merge_partial_controls_after_repositioning_metadata(self):
  records=[self.header(),self.control('00:00:20;00',transitionActive=True),
   self.control('00:00:30;00',source=2,transitionActive=False),
   self.control('00:00:40;00',transitionActive=True),self.metadata('00:00:25;00'),
   self.control('00:00:50;00',source=3,transitionActive=False)]
  events,sources=self.parse_records(records)
  self.assertEqual([e['line'] for e in events],[1,2,5,3,4,6])
  moved=events[2];state=moved['state']['mixEffectBlocks'][0]
  self.assertEqual(state['source'],1)
  self.assertTrue(state['transitionActive']);self.assertTrue(state['onAir'])
  self.assertEqual(events[3]['state']['mixEffectBlocks'][0]['source'],2)
  self.assertFalse(events[3]['state']['mixEffectBlocks'][0]['transitionActive'])
  self.assertTrue(events[4]['state']['mixEffectBlocks'][0]['transitionActive'])
  self.assertEqual(events[-1]['state']['mixEffectBlocks'][0]['source'],3)
  self.assertEqual(set(sources),{'01.mp4','03.mp4'})
  self.assertEqual(moved['normalization']['logged_after_line'],4)
  self.assertEqual(moved['normalization']['delay_frames'],450)
  self.assertEqual(records[4],moved['update'])
 def test_same_frame_controls_keep_original_order(self):
  events,_=self.parse_records([self.header(),self.control('00:00:10;00',source=2),
   self.control('00:00:10;00',transitionActive=True),self.control('00:00:20;00',source=3,transitionActive=False),
   self.metadata('00:00:10;00')])
  self.assertEqual([e['line'] for e in events],[1,2,3,5,4])
  self.assertEqual(events[3]['state']['mixEffectBlocks'][0]['source'],2)
  self.assertTrue(events[3]['state']['mixEffectBlocks'][0]['transitionActive'])
  self.assertEqual(events[1]['state']['sources'][0]['file'],'01.mp4')
  self.assertEqual(events[3]['state']['sources'][0]['file'],'03.mp4')
 def test_actual_control_regression_is_not_hidden_by_metadata(self):
  records=[self.header(),self.control('00:00:30;00',source=2),self.metadata('00:00:10;00'),self.control('00:00:20;00',source=3)]
  with self.assertRaisesRegex(ValueError,'Nonmonotonic event at line 4'):self.parse_records(records)
 def test_metadata_mixed_with_controls_is_not_reordered(self):
  mixed=self.metadata('00:00:10;00');mixed.update(mixEffectBlocks=[dict(_index_=0,source=2)])
  with self.assertRaisesRegex(ValueError,'Nonmonotonic event at line 3'):
   self.parse_records([self.header(),self.control('00:00:30;00',source=3),mixed])
 def test_unknown_source_changes_and_mismatched_file_start_are_rejected(self):
  for field,value in [('name','Renamed'),('startTimecode','00:00:09;00')]:
   with self.subTest(field=field):
    metadata=self.metadata('00:00:10;00');metadata['sources'][0][field]=value
    with self.assertRaisesRegex(ValueError,'Nonmonotonic event at line 3'):
     self.parse_records([self.header(),self.control('00:00:30;00',source=3),metadata])
 def test_normalization_cannot_cross_recording_boundary(self):
  with self.assertRaisesRegex(ValueError,'Nonmonotonic event at line 4'):
   self.parse_records([self.header(),self.header('00:00:20;00','b'),
    self.control('00:00:30;00',source=2),self.metadata('00:00:10;00')])
 def test_late_pre_midnight_metadata_does_not_advance_day_again(self):
  events,_=self.parse_records([self.header('23:59:59;10'),self.control('00:00:01;00',source=2),
   self.metadata('23:59:59;20'),self.control('00:00:02;00',source=3)])
  self.assertEqual([e['line'] for e in events],[1,3,2,4])
  self.assertEqual(events[1]['frame']-events[0]['frame'],10)
  self.assertEqual(events[2]['frame']-events[1]['frame'],40)
  self.assertEqual(events[3]['frame']-events[2]['frame'],30)
  self.assertEqual({e['session'] for e in events},{0})
 def test_late_post_midnight_metadata_stays_on_current_day(self):
  events,_=self.parse_records([self.header('23:59:59;10'),self.control('00:00:02;00',source=2),
   self.metadata('00:00:01;00'),self.control('00:00:03;00',source=3)])
  self.assertEqual([e['line'] for e in events],[1,3,2,4])
  self.assertEqual(events[2]['frame']-events[1]['frame'],30)
  self.assertEqual(events[3]['frame']-events[2]['frame'],30)
 def test_preflight_reports_normalization(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);project=root/'input.drp'
   project.write_text('\n'.join(map(json.dumps,[self.header(),self.control('00:00:20;00',source=2),self.metadata('00:00:10;00')])))
   for name in ['01.mp4','03.mp4']:(root/name).write_bytes(b'mocked media')
   def fake_probe(path):
    tc='00:00:00;00' if path.name=='01.mp4' else '00:00:10;00'
    return dict(streams=[dict(codec_type='video',avg_frame_rate='30000/1001',width=1920,height=1080,
     tags=dict(timecode=tc),nb_frames='100',duration_ts=100100,time_base='1/30000')])
   with patch('atem.probe',side_effect=fake_probe):report=preflight(project,root)
  self.assertEqual(len(report['warnings']),1)
  self.assertIn('Line 3: late source-file metadata',report['warnings'][0])
  self.assertIn('300 frame(s) earlier',report['warnings'][0])
 def test_sparse_nominal_rate_reports_timestamp_problem_without_accepting_media(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);project=root/'input.drp';project.write_text(json.dumps(self.header()))
   (root/'01.mp4').write_bytes(b'mocked media')
   probe=dict(streams=[dict(codec_type='video',avg_frame_rate='7622/1000',r_frame_rate='30000/1001')])
   with patch('atem.probe',return_value=probe):
    with self.assertRaisesRegex(ValueError,r'01\.mp4: declared nominal frame rate.*7\.622000.*Gapped timestamps.*no retiming'):
     preflight(project,root)
 def test_actual_rate_mismatch_still_fails_as_frame_rate_error(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);project=root/'input.drp';project.write_text(json.dumps(self.header()))
   (root/'01.mp4').write_bytes(b'mocked media')
   probe=dict(streams=[dict(codec_type='video',avg_frame_rate='25',r_frame_rate='25')])
   with patch('atem.probe',return_value=probe):
    with self.assertRaisesRegex(ValueError,'Unsupported frame rate'):
     preflight(project,root)

if __name__=='__main__':unittest.main()
