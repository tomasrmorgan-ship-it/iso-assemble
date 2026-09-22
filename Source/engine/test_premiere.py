import unittest,copy,xml.etree.ElementTree as E
from unittest.mock import patch
from premiere import timecode,generate
from atem import frames
class PremiereTests(unittest.TestCase):
 def test_dropframe_inverse_each_minute(self):
  for minute in range(1440):
   boundary=minute*1800-2*(minute-minute//10)
   for delta in (-1,0,1,2,29):
    n=(boundary+delta)%2589408
    self.assertEqual(frames(timecode(n)),n)
 def package(self):
  ms=[dict(path=f'/tmp/CAM {c} {seg}.mp4',camera=c,name=f'Camera {c}',start=start,end=end,frames=end-start) for seg,start,end in [(1,100,200),(2,200,300)] for c in (1,2)]
  plan=dict(origin=100,end=300,camera_names={1:'Camera 1',2:'Camera 2'},cuts=[dict(start=100,end=250,angle=1),dict(start=250,end=300,angle=2)],sessions=[dict(start=100,end=300)])
  p=dict(data=dict(media=ms,warnings=[]),catalog=dict(candidates=[dict(id='program',selectable=True,files=[dict(path='/tmp/program.wav',start=100,end=300,frames=200,channels=2)])],inventory=[],warnings=[]))
  return p,plan
 def test_cross_boundary_cut_split_preserves_angle(self):
  p,plan=self.package()
  with patch('premiere.build',return_value=(b'',plan)):xml,report=generate(p,'Test','program')
  self.assertEqual([(c['start'],c['end'],c['angle']) for c in report['cuts']],[(100,200,1),(200,250,1),(250,300,2)])
  self.assertEqual(len(report['technical_splices']),1)
  root=E.fromstring(xml);tracks=root.find('project/children/sequence/media/audio').findall('track')
  self.assertEqual(len(tracks),2)
  self.assertEqual([t.findtext('clipitem/sourcetrack/trackindex') for t in tracks],['1','2'])
 def test_inconsistent_camera_boundaries_rejected(self):
  p,plan=self.package();p['data']['media'].pop()
  with patch('premiere.build',return_value=(b'',plan)):
   with self.assertRaisesRegex(ValueError,'matching recording boundaries'):generate(p,'Test','program')
if __name__=='__main__':unittest.main()
