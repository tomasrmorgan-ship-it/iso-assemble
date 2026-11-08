import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import attach_audio as a


def video_probe(frames=35,tc='00:00:58;25',fps='30000/1001'):
    from fractions import Fraction
    rate=Fraction(fps)
    return dict(streams=[dict(codec_type='video',codec_name='h264',field_order='progressive',
        r_frame_rate=fps,avg_frame_rate=fps,nb_frames=str(frames),time_base=f'1/{rate.numerator}',
        duration_ts=frames*rate.denominator,start_pts=0,width=1920,height=1080,tags=dict(timecode=tc))])


def wav_probe(samples):
    return dict(streams=[dict(codec_type='audio',codec_name='pcm_s24le',sample_rate='48000',channels=2,
        duration_ts=samples,time_base='1/48000')],format=dict(tags=dict(time_reference='999999999999')))


def reference():
    return [dict(path=f'part-{part}.mp4',part=part,media=dict(frames=frames,fps='30000/1001',timecode=tc))
            for part,frames,tc in [(1,35,'00:00:58;25'),(2,60,'23:59:59;00'),(3,40,'00:00:01;00')]]


def wavs():
    return [dict(path='01.wav',media=dict(samples=56056)),dict(path='02.wav',media=dict(samples=160160))]


class MappingTests(unittest.TestCase):
    def test_unequal_split_counts_and_midnight_are_exact(self):
        mapping=a._map_parts(reference(),wavs())
        self.assertEqual([(m['wav'],m['start_sample'],m['end_sample']) for m in mapping],
                         [('01.wav',0,56056),('02.wav',0,96096),('02.wav',96096,160160)])

    def test_fractional_sample_boundary_is_not_rounded(self):
        clips=reference();clips[0]['media']['frames']=34
        with self.assertRaisesRegex(ValueError,'fractional sample'):a._map_parts(clips,wavs())

    def test_video_part_cannot_cross_a_wav_boundary(self):
        audio=wavs();audio[1]['media']['samples']=96095
        with self.assertRaisesRegex(ValueError,'crosses the end'):a._map_parts(reference(),audio)

    def test_unused_audio_is_not_silently_dropped(self):
        audio=wavs();audio[1]['media']['samples']+=1
        with self.assertRaisesRegex(ValueError,'exactly the same boundaries'):a._map_parts(reference(),audio)

    def test_gap_inside_shared_wav_is_rejected(self):
        clips=reference();clips[2]['media']['timecode']='00:00:01;01'
        with self.assertRaisesRegex(ValueError,'gap/overlap within one WAV'):a._map_parts(clips,wavs())

    def test_backwards_timecode_across_new_wav_is_rejected(self):
        clips=reference();clips[1]['media']['timecode']='00:00:30;00'
        with self.assertRaisesRegex(ValueError,'backwards or overlapping'):a._map_parts(clips,wavs())

    def test_bwf_clock_is_not_used_for_length(self):
        self.assertEqual(a._audio_info(Path('audio.wav'),wav_probe(56056))['samples'],56056)

    def test_invalid_drop_frame_label_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Nonexistent drop-frame'):
            a._video_info(Path('bad.mp4'),video_probe(tc='00:01:00;00'))

    def test_positive_start_pts_is_not_normalized(self):
        probe=video_probe();probe['streams'][0]['start_pts']=1001
        with self.assertRaisesRegex(ValueError,'nonzero video start_pts'):a._video_info(Path('delay.mp4'),probe)

    def test_declared_frame_rate_is_not_enough_for_sparse_media(self):
        probe=video_probe();probe['streams'][0]['avg_frame_rate']='7622/1000'
        with self.assertRaisesRegex(ValueError,'gapped/variable-rate'):a._video_info(Path('sparse.mp4'),probe)

    def test_only_pcm24_stereo_48k_is_accepted(self):
        for key,value in [('codec_name','pcm_s16le'),('channels',1),('sample_rate','44100')]:
            probe=wav_probe(100);probe['streams'][0][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'48 kHz stereo 24-bit'):
                a._audio_info(Path('audio.wav'),probe)

    def packet_check(self,pts):
        class Fake:
            stdout=io.StringIO(''.join(f'pts={p}|dts={i-2}|duration=1\n' for i,p in enumerate(pts)))
            def wait(self):return 0
            def poll(self):return 0
        with patch('attach_audio.subprocess.Popen',return_value=Fake()):
            a._check_packets(Path('test.mp4'),dict(frames=5,start_pts=0,step=1))

    def test_b_frame_packet_order_is_valid(self):self.packet_check([0,2,1,4,3])

    def test_equal_average_with_internal_gap_and_duplicate_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'gapped/variable-rate or duplicate'):
            self.packet_check([0,1,3,3,4])


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()/'Recording'
        (self.root/'Video ISO Files').mkdir(parents=True);(self.root/'Audio Source Files').mkdir()
        self.out=Path(self.temp.name).resolve()/'Results'
        for camera in (1,2):(self.root/'Video ISO Files'/f'Show CAM {camera} 01.mp4').write_bytes(b'video')
        (self.root/'Audio Source Files'/'Show CAM 8 01.wav').write_bytes(b'audio')

    def tearDown(self):self.temp.cleanup()

    def probe(self,path):return wav_probe(56056) if path.suffix=='.wav' else video_probe()

    def plan(self,probe=None):
        with patch('attach_audio._probe',side_effect=probe or self.probe),patch('attach_audio._check_packets'):
            return a.make_plan(self.root,'CAM 8',self.out)

    def test_discovery_ignores_atem_project_and_offers_explicit_audio_choice(self):
        (self.root/'bad.drp').write_text('not parseable ATEM')
        inventory=a.discover(self.root)
        self.assertEqual((inventory['cameras'],inventory['clips'],inventory['audioISOs']),(2,2,1))
        self.assertEqual(inventory['choices'][0]['id'],'CAM 8')

    def test_mp4_mov_duplicate_is_rejected(self):
        (self.root/'Video ISO Files'/'Show CAM 1 01.mov').write_bytes(b'duplicate')
        with self.assertRaisesRegex(ValueError,'Duplicate camera'):a.discover(self.root)

    def test_each_camera_must_have_matching_parts_before_any_output(self):
        (self.root/'Video ISO Files'/'Show CAM 2 02.mp4').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError,'part numbers differ'):self.plan()
        self.assertFalse((self.out/a.JOB).exists())

    def test_camera_frame_count_timecode_and_rate_mismatches_fail_before_mov(self):
        for key in ('frames','timecode','fps'):
            def probe(path):
                if 'CAM 2' in path.name:
                    return video_probe(frames=40 if key=='frames' else 35,
                        tc='00:00:58;26' if key=='timecode' else ('00:00:58:25' if key=='fps' else '00:00:58;25'),
                        fps='30000/1001' if key!='fps' else '30')
                return self.probe(path)
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'differs from the reference'):self.plan(probe)
            self.assertFalse((self.out/a.JOB).exists())

    def test_length_mismatch_does_not_create_job_or_mov(self):
        with self.assertRaisesRegex(ValueError,'exactly the same boundaries'):
            self.plan(lambda path:wav_probe(56057) if path.suffix=='.wav' else video_probe())
        self.assertFalse((self.out/a.JOB).exists())

    def test_dry_run_is_reusable_and_creates_no_mov(self):
        plan=self.plan();self.assertEqual(self.plan(),plan)
        self.assertEqual(list((self.out/a.JOB).glob('*.mov')),[])
        self.assertEqual(plan['mapping'][0]['samples'],56056)
        self.assertIn('ignored',plan['warnings'][0])

    def test_unowned_destination_and_symlinks_are_rejected(self):
        (self.out/a.JOB).mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'not owned'):self.plan()
        (self.out/a.JOB).rmdir();self.out.rmdir();self.out.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'Symlink'):self.plan()

    def test_changed_input_snapshot_and_tampered_plan_stop_before_ffmpeg(self):
        plan=self.plan();path=next(iter(plan['inputs']))
        Path(path).write_bytes(b'changed')
        with patch('attach_audio._run') as command:
            with self.assertRaisesRegex(ValueError,'Input changed'):a.build(self.out)
            command.assert_not_called()
        saved=Path(plan['path']);data=json.loads(saved.read_text());data['outputs'][0]['end_sample']+=1;saved.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'plan or ownership manifest was changed'):a.build(self.out)


@unittest.skipUnless(os.environ.get('ATTACH_AUDIO_TEST_FFMPEG'),'Set ATTACH_AUDIO_TEST_FFMPEG for generated media integration')
class AttachmentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.base=Path(cls.temp.name).resolve()
        cls.ffmpeg=os.environ['ATTACH_AUDIO_TEST_FFMPEG']
        cls.path_patch=patch.dict(os.environ,PATH=str(Path(cls.ffmpeg).parent)+os.pathsep+os.environ.get('PATH',''))
        cls.path_patch.start();cls.fixture=cls.base/'fixture';(cls.fixture/'Video ISO Files').mkdir(parents=True);(cls.fixture/'Audio Source Files').mkdir()
        cls.call(['-f','lavfi','-i','testsrc2=size=160x90:rate=30000/1001','-frames:v','35','-c:v','libx264','-pix_fmt','yuv420p',
                  '-timecode','00:00:58;25',str(cls.fixture/'Video ISO Files'/'Show CAM 1 01.mp4')])
        for camera in (2,):shutil.copyfile(cls.fixture/'Video ISO Files'/'Show CAM 1 01.mp4',cls.fixture/'Video ISO Files'/f'Show CAM {camera} 01.mp4')
        cls.call(['-f','lavfi','-i','sine=frequency=997:sample_rate=48000','-af','atrim=end_sample=56056','-ac','2','-c:a','pcm_s24le',
                  '-write_bext','1','-metadata','time_reference=999999999',str(cls.fixture/'Audio Source Files'/'Show CAM 8 01.wav')])

    @classmethod
    def call(cls,args):subprocess.run([cls.ffmpeg,'-nostdin','-v','error','-y',*args],check=True)

    @classmethod
    def tearDownClass(cls):cls.path_patch.stop();cls.temp.cleanup()

    def setUp(self):
        self.root=self.base/self._testMethodName;shutil.copytree(self.fixture,self.root)
        self.out=self.base/(self._testMethodName+'-out');self.plan=a.make_plan(self.root,'CAM 8',self.out)

    def test_build_hashes_exact_samples_tmcd_and_safe_resume(self):
        result=a.build(self.out);self.assertEqual(result['verified_count'],2)
        for path in result['outputs']:
            info=a._probe(Path(path));self.assertEqual(a._audio_info(Path(path),info)['samples'],56056)
            self.assertEqual(a._video_info(Path(path),info)['timecode'],'00:00:58;25')
        self.assertEqual(a.build(self.out)['resumed_count'],2)
        Path(result['outputs'][0]).write_bytes(b'tampered output')
        with self.assertRaises(ValueError):a.build(self.out)
        self.assertEqual(Path(result['outputs'][0]).read_bytes(),b'tampered output')

    def test_owned_publish_reservation_recovers_without_rebuilding_video(self):
        result=a.build(self.out);job=Path(result['output']);output=Path(result['outputs'][0])
        temporary=job/'.partial'/('a'*32+'.mov');output.rename(temporary);output.touch()
        state=json.loads((job/a.STATE).read_text());state['outputs'][str(output)]=dict(status='publishing',temporary=str(temporary),reservation=a._snapshot(output))
        (job/a.STATE).write_text(json.dumps(state))
        self.assertEqual(a.build(self.out)['verified_count'],2);self.assertFalse(temporary.exists())

    def test_unowned_output_collision_and_low_disk_fail_before_mov(self):
        output=Path(self.plan['outputs'][0]['output']);output.write_bytes(b'keep me')
        with self.assertRaisesRegex(ValueError,'Unowned output collision'):a.build(self.out)
        self.assertEqual(output.read_bytes(),b'keep me');output.unlink()
        with patch('attach_audio.shutil.disk_usage',return_value=shutil._ntuple_diskusage(100,100,0)):
            with self.assertRaisesRegex(ValueError,'Insufficient output disk space'):a.build(self.out)
        self.assertEqual(list(output.parent.glob('*.mov')),[])

    def test_verification_report_symlink_never_overwrites_target(self):
        job=Path(self.plan['output']);target=self.base/'untouched.txt';target.write_text('original')
        (job/'Attach Audio Verification.txt').symlink_to(target)
        with self.assertRaisesRegex(ValueError,'symlink'):a.build(self.out)
        self.assertEqual(target.read_text(),'original')


if __name__=='__main__':unittest.main()
