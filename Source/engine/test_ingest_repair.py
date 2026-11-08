"""Missing camera references must identify the actual problem without relinking MOVs."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ingest import repair_for,audio_catalog
from atem import preflight


class FilenameRepairTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'Unrelated Container Name'
  self.video=self.root/'Video ISO Files';self.video.mkdir(parents=True)
  self.references=[f'Video ISO Files/Original CAM {camera} 01.mp4' for camera in (1,2)]
  self.project=self.root/'Capture.drp'
  record=dict(videoMode='1080p29.97',recordingId='recording',masterTimecode='00:00:00;00',
   sources=[dict(_index_=i,type='Video',name=f'Camera {i}',file=f,startTimecode='00:00:00;00') for i,f in enumerate(self.references,1)])
  self.project.write_text(json.dumps(record)+'\n')
 def tearDown(self):self.temp.cleanup()
 def files(self,prefix='Original',suffix='.mp4',cameras=(1,2)):
  for camera in cameras:(self.video/f'{prefix} CAM {camera} 01{suffix}').write_bytes(f'untouched {camera}'.encode())
 def snapshot(self):
  return {str(p.relative_to(self.root)):(p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()) for p in self.root.rglob('*') if p.is_file()}
 def test_complete_original_references_need_no_repair(self):
  self.files();self.assertIsNone(repair_for(self.root,self.project))
 def test_missing_mp4_with_same_stem_mov_is_explained_but_not_substituted(self):
  self.files(suffix='.mov');before=self.snapshot()
  with self.assertRaises(ValueError) as caught:repair_for(self.root,self.project,allow_mov=False)
  message=str(caught.exception)
  for f in self.references:self.assertIn(f,message)
  self.assertIn('DRP still references MP4',message)
  self.assertIn('MOV present; unverified',message)
  self.assertIn('not automatically approved or substituted',message)
  self.assertIn('Camera files with shared audio',message)
  self.assertIn('does not use the DRP',message)
  self.assertIn('restore the original',message)
  self.assertEqual(self.snapshot(),before)
 def test_actual_missing_reference_is_listed(self):
  self.files(cameras=(1,))
  with self.assertRaises(ValueError) as caught:repair_for(self.root,self.project)
  message=str(caught.exception)
  self.assertIn('references 1 missing',message);self.assertIn(self.references[1],message)
  self.assertNotIn('MOV files are present',message)
 def test_unique_actual_prefix_is_inferred_independently_of_root_name(self):
  self.files(prefix='Renamed Capture');before=self.snapshot()
  self.assertEqual(repair_for(self.root,self.project),['Original','Renamed Capture'])
  self.assertEqual(self.snapshot(),before)
 def test_original_root_name_prefix_rule_still_works(self):
  self.files(prefix=self.root.name)
  self.assertEqual(repair_for(self.root,self.project),['Original',self.root.name])
 def test_partial_prefix_match_never_authorizes_repair(self):
  self.files(prefix='Partial',cameras=(1,))
  with self.assertRaisesRegex(ValueError,'No complete verified filename-prefix repair'):repair_for(self.root,self.project)
 def test_two_complete_candidates_require_explicit_choice(self):
  self.files(prefix='First');self.files(prefix='Second')
  with self.assertRaisesRegex(ValueError,'Multiple complete'):repair_for(self.root,self.project)
  self.assertEqual(repair_for(self.root,self.project,['Original','Second']),['Original','Second'])
 def test_explicit_partial_repair_reports_its_missing_target(self):
  self.files(prefix='Partial',cameras=(1,))
  with self.assertRaisesRegex(ValueError,'Partial CAM 2 01.mp4'):repair_for(self.root,self.project,['Original','Partial'])
 def test_same_stem_mov_cannot_satisfy_a_prefix_repair(self):
  self.files(prefix='Renamed',suffix='.mov')
  with self.assertRaises(ValueError):repair_for(self.root,self.project,['Original','Renamed'])
 def test_external_media_symlinks_do_not_verify_a_prefix(self):
  outside=Path(self.temp.name)/'outside.mp4';outside.write_bytes(b'outside')
  for camera in (1,2):(self.video/f'Renamed CAM {camera} 01.mp4').symlink_to(outside)
  with self.assertRaisesRegex(ValueError,'No complete verified filename-prefix repair'):repair_for(self.root,self.project)
 def valid_probe(self,path,frames=35,tc='00:00:00;00'):
  return dict(streams=[dict(codec_type='video',width=1920,height=1080,avg_frame_rate='30000/1001',
   r_frame_rate='30000/1001',nb_frames=str(frames),duration_ts=frames*1001,time_base='1/30000',start_pts=0,tags=dict(timecode=tc))])
 def test_mov_mapping_is_used_only_after_preflight_verifies_it(self):
  self.files(suffix='.mov');before=self.snapshot();mapping=repair_for(self.root,self.project)
  self.assertEqual(mapping,{f:str(Path(f).with_suffix('.mov')) for f in self.references})
  with patch('atem.probe',side_effect=self.valid_probe):data=preflight(self.project,self.root,mapping)
  self.assertEqual(len(data['media_relinks']),2)
  self.assertTrue(all(Path(m['path']).suffix=='.mov' for m in data['media']))
  self.assertTrue(any('Relinked MP4 reference -> MOV' in w for w in data['warnings']))
  self.assertEqual(self.snapshot(),before)
 def test_existing_original_wins_over_same_stem_mov(self):
  self.files(cameras=(1,));self.files(suffix='.mov')
  mapping=repair_for(self.root,self.project)
  self.assertEqual(mapping[self.references[0]],self.references[0])
  self.assertEqual(Path(mapping[self.references[1]]).suffix,'.mov')
 def test_unique_mov_prefix_can_be_relinked(self):
  self.files(prefix='Renamed',suffix='.mov')
  mapping=repair_for(self.root,self.project)
  self.assertEqual(mapping[self.references[0]],'Video ISO Files/Renamed CAM 1 01.mov')
 def test_multiple_mov_prefixes_are_not_guessed(self):
  self.files(prefix='First',suffix='.mov');self.files(prefix='Second',suffix='.mov')
  with self.assertRaisesRegex(ValueError,'Multiple complete MOV'):repair_for(self.root,self.project)
 def test_mov_timing_frame_count_or_identity_mismatch_is_rejected(self):
  self.files(suffix='.mov');mapping=repair_for(self.root,self.project)
  for fault in ('frames','timecode','duration'):
   def probe(path):
    data=self.valid_probe(path,frames=40 if fault=='frames' and 'CAM 2' in path.name else 35,
      tc='00:00:00;02' if fault=='timecode' else '00:00:00;00')
    if fault=='duration':data['streams'][0]['duration_ts']+=1
    return data
   with self.subTest(fault=fault),patch('atem.probe',side_effect=probe),self.assertRaises(ValueError):preflight(self.project,self.root,mapping)
  mapping[self.references[0]]=mapping[self.references[1]]
  with self.assertRaisesRegex(ValueError,'identity'):preflight(self.project,self.root,mapping)
 def rollover_project(self):
  self.files(suffix='.mov')
  for camera in (1,2):(self.video/f'Original CAM {camera} 02.mov').write_bytes(b'next part')
  initial=json.loads(self.project.read_text());update=dict(masterTimecode='00:00:01;01',sources=[dict(_index_=camera,file=f'Video ISO Files/Original CAM {camera} 02.mp4',startTimecode='00:00:01;01') for camera in (1,2)])
  self.project.write_text(json.dumps(initial)+'\n'+json.dumps(update)+'\n')
 def rollover_probe(self,path):
  return self.valid_probe(path,frames=30,tc='00:00:01;00' if '02.' in path.name else '00:00:00;00')
 def test_one_frame_rollover_requires_independent_program_and_continuity(self):
  self.rollover_project();mapping=repair_for(self.root,self.project)
  with patch('atem.probe',side_effect=self.rollover_probe),self.assertRaisesRegex(ValueError,'matching program'):preflight(self.project,self.root,mapping)
  (self.root/'Original 02.mp4').write_bytes(b'program reference')
  with patch('atem.probe',side_effect=self.rollover_probe):data=preflight(self.project,self.root,mapping)
  self.assertEqual([m['source_start_delta_frames'] for m in data['media_relinks']],[0,0,-1,-1])
  self.assertTrue(any('Confirmed one-frame-late' in w for w in data['warnings']))
  def noncontiguous(path):return self.valid_probe(path,frames=25 if '01.' in path.name else 30,tc='00:00:01;00' if '02.' in path.name else '00:00:00;00')
  with patch('atem.probe',side_effect=noncontiguous),self.assertRaisesRegex(ValueError,'not contiguous'):preflight(self.project,self.root,mapping)


class ExactAudioCatalogTests(unittest.TestCase):
 def test_two_wavs_cover_three_video_parts_with_unreliable_bwf_clocks(self):
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary).resolve();audio=root/'Audio Source Files';audio.mkdir()
   paths=[audio/f'Show CAM 8 {part:02d}.wav' for part in (1,2)]
   for path in paths:path.write_bytes(b'mocked WAV')
   media=[]
   for camera in (1,2):
    for part,start,frames in [(1,0,35),(2,300,60),(3,360,40)]:
     from timing import Timing
     media.append(dict(camera=camera,path=str(root/f'Show CAM {camera} {part:02d}.mov'),start=start,frames=frames,timecode=Timing().timecode(start)))
   plan=dict(timing=dict(fps='30000/1001',drop=True),media=media,sessions=[dict(start=0,end=35,id='first'),dict(start=300,end=400,id='second')])
   def probe(path):
    samples=56056 if path==paths[0] else 160160
    return dict(streams=[dict(codec_type='audio',duration_ts=samples,time_base='1/48000',sample_rate='48000',channels=2)],format=dict(tags=dict(time_reference='999999999',creation_time='01:02:03')))
   with patch('ingest.probe',side_effect=probe):catalog=audio_catalog(root,plan)
   candidate=catalog['candidates'][0]
   self.assertTrue(candidate['selectable']);self.assertEqual([(f['start'],f['frames']) for f in candidate['files']],[(0,35),(300,100)])
   self.assertTrue(any('BWF time_reference differs' in w for w in catalog['warnings']))
   def mismatch(path):
    result=probe(path);result['streams'][0]['duration_ts']+=1;return result
   with patch('ingest.probe',side_effect=mismatch):catalog=audio_catalog(root,plan)
   self.assertFalse(catalog['candidates'][0]['selectable'])


if __name__=='__main__':unittest.main()
