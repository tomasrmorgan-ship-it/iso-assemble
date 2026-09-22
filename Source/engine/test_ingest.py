import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from ingest import discover_project,audio_catalog
class RootIngestTests(unittest.TestCase):
 def test_discovery_requires_unambiguous_atem(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'one.drp').write_text('{"masterTimecode":"00:00:00;00"}\n');(root/'resolve.drp').write_bytes(b'PK\x00')
   self.assertEqual(discover_project(root).name,'one.drp')
   (root/'two.drp').write_text('{"masterTimecode":"00:00:00;00"}\n')
   with self.assertRaisesRegex(ValueError,'Found 2'):discover_project(root)
 def test_audio_rollover_timestamp_and_coverage(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'Show MIC 1 01.wav').touch()
   # Exact frame-aligned 10-second recording; BWF incorrectly stamps internal frame 200.
   plan={'sessions':[{'start':100,'end':400,'id':'x'}],'media':[{'path':'dummy','start':200}], '_events':[{'session':0,'state':{'masterTimecode':'00:00:03;10'}}]}
   fake={'streams':[{'codec_type':'audio','duration_ts':480480,'time_base':'1/48000','sample_rate':'48000','channels':2}], 'format':{'tags':{'creation_time':'00:00:03','time_reference':'320320'}}}
   with patch('ingest.probe',return_value=fake):cat=audio_catalog(root,plan)
   self.assertEqual(cat['candidates'][0]['files'][0]['start'],100)
   self.assertTrue(cat['candidates'][0]['selectable']);self.assertTrue(cat['warnings'])
   fake['format']['tags']['time_reference']='1000000'
   with patch('ingest.probe',return_value=fake):
    with self.assertRaisesRegex(ValueError,'Conflicting BWF'):audio_catalog(root,plan)
if __name__=='__main__':unittest.main()
