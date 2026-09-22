import unittest
from atem import frames,merge,parse
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
  records=[{'version':1,'recordingId':'a','masterTimecode':'23:59:59;29','mixEffectBlocks':[{'_index_':0,'source':3,'onAir':True}]},{'version':1,'recordingId':'a','masterTimecode':'00:00:00;00','mixEffectBlocks':[{'_index_':0,'source':4}]}]
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'input.drp';p.write_text('\n'.join(map(json.dumps,records)));ev,_=parse(p)
  self.assertEqual(ev[1]['frame']-ev[0]['frame'],1)
  self.assertEqual(ev[1]['session'],0)
  self.assertTrue(ev[1]['state']['mixEffectBlocks'][0]['onAir'])
 def test_truncated_record_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'input.drp';p.write_text('{"masterTimecode":')
   with self.assertRaisesRegex(ValueError,'line 1'):parse(p)
if __name__=='__main__':unittest.main()
