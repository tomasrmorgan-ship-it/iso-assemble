import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app_engine import snapshot,create
class AppSafetyTests(unittest.TestCase):
 def test_changed_media_stops_before_resolve(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d);media=out/'clip.wav';media.write_bytes(b'old')
   package={'snapshot':snapshot([media]),'data':{},'catalog':{}}
   (out/'scan.json').write_text(json.dumps(package));media.write_bytes(b'changed media')
   with patch('resolve_project.connect') as connection:
    with self.assertRaisesRegex(ValueError,'changed after scanning'):create(out,'New Project','program')
    connection.assert_not_called()
 def test_no_implicit_audio_selection(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d);(out/'scan.json').write_text(json.dumps({'snapshot':{},'data':{},'catalog':{'candidates':[]}}))
   with patch('resolve_project.connect') as connection:
    with self.assertRaisesRegex(ValueError,'Select a primary audio'):create(out,'New Project','program')
    connection.assert_not_called()
if __name__=='__main__':unittest.main()
