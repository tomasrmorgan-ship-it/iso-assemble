import json,tempfile,unittest,xml.etree.ElementTree as E
from pathlib import Path
from fractions import Fraction
from unittest.mock import patch
from timing import Timing,RATES
from atem import parse,preflight
from convert import build
from premiere import generate
from ingest import audio_catalog
CASES=[(label,drop) for label in RATES if label!='23.98' for drop in ([False,True] if label in ('29.97','59.94') else [False])]
def fixture(t,root):
 start=t.frames('00:00:59'+(';' if t.drop else ':')+'00');count=t.nominal*3
 source=dict(_index_=1,name='Camera 1',file='camera.mp4',startTimecode=t.timecode(start))
 rows=[dict(videoMode='1080p'+t.resolve_rate,recordingId='test',masterTimecode=t.timecode(start),sources=[source],mixEffectBlocks=[dict(_index_=0,onAir=True,source=1)]),dict(masterTimecode=t.timecode(start+count),mixEffectBlocks=[dict(_index_=0,onAir=False)])]
 p=root/'test.drp';p.write_text('\n'.join(map(json.dumps,rows)));(root/'camera.mp4').touch()
 v=dict(codec_type='video',avg_frame_rate=str(t.fps),width=1920,height=1080,tags={'timecode':t.timecode(start)},nb_frames=str(count),duration_ts=count*t.fps.denominator,time_base='1/'+str(t.fps.numerator))
 return p,v,start,count
class RateTests(unittest.TestCase):
 def test_timecode_all_minutes_all_modes(self):
  for label,drop in CASES:
   t=Timing(Fraction(*RATES[label]),drop)
   for minute in range(1440):
    boundary=minute*60*t.nominal-t.skip*(minute-minute//10)
    for delta in (-1,0,1,t.nominal-1):
     n=(boundary+delta)%t.day
     self.assertEqual(t.frames(t.timecode(n)),n,(label,drop,n))
   self.assertEqual(t.seconds(1),1/t.fps)
   self.assertEqual(t.ticks*t.fps,254016000000)
 def test_drop_invalid_labels_and_mode(self):
  for label in ['29.97','59.94']:
   t=Timing(Fraction(*RATES[label]),True)
   for frame in range(t.skip):
    with self.assertRaises(ValueError):t.frames(f'00:01:00;{frame:02d}')
   with self.assertRaises(ValueError):t.frames('00:01:00:00')
  for label in ['23.976','24','25','30','50','60']:
   with self.assertRaises(ValueError):Timing(Fraction(*RATES[label]),True)
 def test_exports_preflight_and_audio_all_modes(self):
  for label,drop in CASES:
   with self.subTest(rate=label,drop=drop),tempfile.TemporaryDirectory() as d:
    root=Path(d);t=Timing(Fraction(*RATES[label]),drop);p,v,start,count=fixture(t,root)
    with patch('atem.probe',return_value={'streams':[v]}):data=preflight(p,root)
    xml,plan=build(data,'Test');r=E.fromstring(xml)
    self.assertEqual(r.find('resources/format').get('frameDuration'),t.xml_time(1))
    self.assertEqual(r.find('.//sequence').get('tcFormat'),t.display)
    self.assertEqual(plan['end']-plan['origin'],count)
    plan['media']=data['media'];plan['_events']=data['events']
    (root/'Test MIC 1 01.wav').touch();samples=t.seconds(count)*48000
    probe={'streams':[dict(codec_type='audio',duration_ts=int(samples),time_base='1/48000',sample_rate='48000',channels=2)],'format':{'tags':{'creation_time':'00:00:59'}}}
    with patch('ingest.probe',return_value=probe):cat=audio_catalog(root,plan)
    self.assertTrue(cat['candidates'][0]['selectable'])
    px,report=generate(dict(data=data,catalog=cat),'Test','mic1');pr=E.fromstring(px)
    for rate in pr.findall('.//rate'):
     self.assertEqual(rate.findtext('timebase'),str(t.nominal));self.assertEqual(rate.findtext('ntsc'),'TRUE' if t.fps.denominator==1001 else 'FALSE')
    for tc in pr.findall('.//timecode'):self.assertEqual(tc.findtext('displayformat'),t.display)
    self.assertEqual(report['timing'],t.data())
 def test_mismatch_and_missing_rate_fail(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);t=Timing('25',False);p,v,_,_=fixture(t,root);v['avg_frame_rate']='30'
   with patch('atem.probe',return_value={'streams':[v]}),self.assertRaisesRegex(ValueError,'frame rate'):preflight(p,root)
   rows=[json.loads(x) for x in p.read_text().splitlines()];rows[1]['videoMode']='1080p30';p.write_text('\n'.join(map(json.dumps,rows)))
   with self.assertRaisesRegex(ValueError,'changed'):parse(p)
   rows[0].pop('videoMode');p.write_text('\n'.join(map(json.dumps,rows)))
   with self.assertRaisesRegex(ValueError,'Unsupported video mode'):parse(p)
 def test_midnight_all_modes(self):
  for label,drop in CASES:
   t=Timing(Fraction(*RATES[label]),drop)
   with tempfile.TemporaryDirectory() as d:
    p=Path(d)/'a.drp';p.write_text('\n'.join(map(json.dumps,[dict(videoMode='1080p'+label,recordingId='a',masterTimecode=t.timecode(t.day-1)),dict(masterTimecode=t.timecode(0))])))
    ev,_=parse(p);self.assertEqual(ev[1]['frame']-ev[0]['frame'],1)
if __name__=='__main__':unittest.main()
