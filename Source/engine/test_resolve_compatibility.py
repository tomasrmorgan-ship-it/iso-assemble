"""Runtime proof ownership, caching, restoration and negative API paths."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import resolve_compatibility as c
from timing import Timing
from test_resolve_transitions import Timeline, Video


class PoolItem:
    def __init__(self, uid, path='', frames=24):self.uid,self.path,self.frames=uid,path,frames
    def GetUniqueId(self):return self.uid
    def GetClipProperty(self,key):
        return {'File Path':self.path,'Frames':str(self.frames),'Type':'Video' if self.path else 'Multicam'}[key]


class ProofVideo(Video):
    def GetMediaPoolItem(self):return self.timeline.mc


class ProofTimeline(Timeline):
    def __init__(self,plan,fail=None):
        super().__init__(plan)
        self.mc=PoolItem('multicam',frames=plan['end']-plan['origin'])
        self.videos=[ProofVideo(self,cut,plan) for cut in plan['cuts']]
        self.fail_add=fail=='transition'
        self.shift_new_transition=fail=='geometry'
    def GetName(self):return self.plan['sessions'][0]['multicam_name'].removesuffix('_Multicam')+'_Edit'
    def GetSetting(self,key):return Timing.from_plan(self.plan).resolve_rate


class Folder:
    def __init__(self,project):self.project=project
    def GetClipList(self):
        if self.project.content:return [PoolItem('content','/existing/media.mov')]
        if not self.project.timelines:return []
        items=[PoolItem('source-'+str(i),m['path']) for i,m in enumerate(self.project.pm.sources)]
        return items+[self.project.timelines[0].mc]
    def GetSubFolderList(self):return []


class Pool:
    def __init__(self,project):self.project=project
    def GetRootFolder(self):return Folder(self.project)
    def ImportTimelineFromFile(self,path):
        if self.project.pm.fail=='timeline_import':return None
        self.project.timelines=[ProofTimeline(copy.deepcopy(self.project.pm.plan),self.project.pm.fail)]
        return self.project.timelines[0]


class Project:
    def __init__(self,pm,name,uid):
        self.pm,self.name,self.uid=pm,name,uid;self.timelines=[];self.content=False
    def GetUniqueId(self):return self.uid
    def GetName(self):return self.name
    def GetTimelineCount(self):return len(self.timelines)
    def GetTimelineByIndex(self,index):return self.timelines[index-1]
    def GetMediaPool(self):return Pool(self)
    def SetSetting(self,key,value):return self.pm.fail!='settings'
    def SetCurrentTimeline(self,timeline):return True


class Manager:
    def __init__(self):
        self.serial=0;self.projects={};self.current=None;self.plan=None;self.sources=[]
        self.fail=None;self.creates=[];self.deletes=[];self.saves=[];self.exported=None
        self.current=self.CreateProject('Working');self.creates=[]
    def CreateProject(self,name):
        if name in self.projects:return None
        self.serial+=1;p=Project(self,name,'id-'+str(self.serial));self.projects[name]=p;self.current=p;self.creates.append(name);return p
    def GetCurrentProject(self):return self.current
    def GetProjectListInCurrentFolder(self):return list(self.projects)
    def SaveProject(self):
        self.saves.append(self.current.name)
        if self.fail=='save_previous' and self.current.name=='Working':return False
        if self.fail=='save_proof' and self.current.name!='Working':return False
        return True
    def LoadProject(self,name):
        if self.fail=='restore' and name=='Working' and self.creates:return None
        p=self.projects.get(name)
        if p:self.current=p
        return p
    def CloseProject(self,project):
        if self.current is project:self.current=None
        return True
    def DeleteProject(self,name):
        if self.current and self.current.name==name:return False
        self.deletes.append(name);del self.projects[name];return True
    def ExportProject(self,name,path):
        if self.fail=='export':return False
        Path(path).write_bytes(b'proof project');self.exported=self.projects[name];return True
    def ImportProject(self,path,name):
        if self.fail=='reimport':return False
        p=self.CreateProject(name)
        if not p:return False
        p.timelines=[ProofTimeline(copy.deepcopy(self.exported.timelines[0].plan))]
        p.timelines[0].transitions=copy.deepcopy(self.exported.timelines[0].transitions)
        if self.fail=='changed_reimport':p.timelines[0].videos[1].name='Wrong selected angle'
        return True


class Resolve:
    def __init__(self,version='21.2.0.6'):
        self.version=version;self.pm=Manager()
    def GetProjectManager(self):return self.pm
    def GetVersionString(self):return self.version
    def GetVersion(self):return [*c._version_fields(self.version),'']


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.out=self.root/'output';self.resolve=Resolve()
        self.data=dict(timing=Timing().data(),media=[])
        for camera in (1,2):
            p=self.root/f'Camera {camera}.mov';p.write_bytes(b'media')
            self.data['media'].append(dict(path=str(p),camera=camera,start=1000,end=1060,frames=60))
        self.real_xml=c._proof_xml
        def xml(sources,start,duration,timing,name,needs_mix):
            result=self.real_xml(sources,start,duration,timing,name,needs_mix)
            self.resolve.pm.plan=result[1];self.resolve.pm.sources=sources
            return result
        self.patch=patch.object(c,'_proof_xml',side_effect=xml);self.patch.start();self.addCleanup(self.patch.stop)
    def run_proof(self,mix=True):return c.ensure_compatible(self.resolve,self.data,self.out,mix)
    def state(self):return json.loads((self.out/'Resolve Compatibility/state.json').read_text())

    def test_numeric_gate_accepts_new_builds_and_suffix(self):
        for value in ('21.2.0.6','21.1.1b.10','22.0.0.1',[21,2,0,6,'']):
            c.check_version(value,True)
        c.check_version('21.0.0.99',False)
        for value,mix in (('20.3.1.9',False),('21.0.0.99',True),('unknown',False)):
            with self.subTest(value=value),self.assertRaises(ValueError):c.check_version(value,mix)

    def test_passed_proof_has_two_native_angles_and_restores_working_project(self):
        previous=self.resolve.pm.current.uid
        result=self.run_proof()
        self.assertEqual((result['cuts_verified'],result['transitions_verified']), (2,1))
        self.assertEqual(result['selected_angles'],[1,2]);self.assertTrue(result['previous_project_restored'])
        self.assertEqual(self.resolve.pm.current.uid,previous)
        self.assertEqual(len(self.resolve.pm.creates),2);self.assertEqual(len(self.resolve.pm.projects),3)
        self.assertTrue(self.state()['complete']);self.assertEqual(result['resolve_version'],'21.2.0.6')

    def test_cache_saves_current_project_but_does_not_create_another_proof(self):
        first=self.run_proof();creates=list(self.resolve.pm.creates);saves=len(self.resolve.pm.saves)
        second=self.run_proof()
        self.assertTrue(second['cached']);self.assertEqual(first['fingerprint'],second['fingerprint'])
        self.assertEqual(self.resolve.pm.creates,creates)
        self.assertEqual(self.resolve.pm.saves[saves:],['Working'])

    def test_source_change_retests_using_only_the_same_two_owned_names(self):
        first=self.run_proof();names=first['proof_project_names']
        Path(self.data['media'][0]['path']).write_bytes(b'changed media identity')
        second=self.run_proof()
        self.assertFalse(second['cached']);self.assertNotEqual(second['fingerprint'],first['fingerprint'])
        self.assertEqual(second['proof_project_names'],names);self.assertEqual(self.resolve.pm.deletes,names)
        self.assertEqual(len(self.resolve.pm.projects),3)

    def test_version_rate_drop_and_policy_are_cache_keys(self):
        previous=self.run_proof()
        self.resolve.version='21.2.0.7';current=self.run_proof();self.assertNotEqual(previous['fingerprint'],current['fingerprint'])
        self.data['timing']=Timing('30000/1001',False).data();previous=current;current=self.run_proof();self.assertNotEqual(previous['fingerprint'],current['fingerprint'])
        self.data['timing']=Timing('25',False).data();previous=current;current=self.run_proof();self.assertNotEqual(previous['fingerprint'],current['fingerprint'])
        previous=current;current=self.run_proof(False);self.assertNotEqual(previous['fingerprint'],current['fingerprint'])
        self.assertEqual(current['transitions_verified'],0)

    def test_api_failures_restore_previous_and_never_cache_success(self):
        for failure in ('settings','timeline_import','transition','geometry','save_proof','export','reimport','changed_reimport'):
            with self.subTest(failure=failure):
                self.out=self.root/failure;self.resolve.pm=Manager();self.resolve.pm.fail=failure
                previous=self.resolve.pm.current.uid
                with self.assertRaisesRegex(ValueError,'did not pass'):self.run_proof()
                self.assertEqual(self.resolve.pm.current.uid,previous)
                self.assertFalse(self.state()['complete'])
                self.assertFalse((self.out/'Resolve Compatibility/Compatibility Report.json').exists())

    def test_restore_failure_prevents_passed_report(self):
        self.resolve.pm.fail='restore'
        with self.assertRaisesRegex(ValueError,'could not restore'):self.run_proof()
        self.assertFalse(self.state()['complete'])
        self.assertFalse((self.out/'Resolve Compatibility/Compatibility Report.json').exists())

    def test_changed_project_id_is_never_deleted(self):
        result=self.run_proof();name=result['proof_project_names'][0]
        self.resolve.pm.projects[name].uid='unowned-replacement'
        Path(self.data['media'][0]['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'unowned or changed'):self.run_proof()
        self.assertEqual(self.resolve.pm.deletes,[])
        self.assertEqual(self.resolve.pm.current.name,'Working')

    def test_unowned_output_folder_is_preserved(self):
        folder=self.out/'Resolve Compatibility';folder.mkdir(parents=True);p=folder/'Proof.drp';p.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'unowned files'):self.run_proof()
        self.assertEqual(p.read_bytes(),b'keep');self.assertEqual(self.resolve.pm.creates,[])

    def test_too_short_or_same_camera_has_no_project_side_effects(self):
        self.data['media'][1]['end']=1011
        with self.assertRaisesRegex(ValueError,'12 overlapping'):self.run_proof()
        self.assertEqual(self.resolve.pm.creates,[]);self.assertEqual(self.resolve.pm.saves,[])
        self.data['media'][1].update(end=1060,camera=1)
        with self.assertRaisesRegex(ValueError,'two different camera'):self.run_proof()

    def test_empty_unsaved_startup_project_does_not_open_save_modal(self):
        pm=self.resolve.pm;pm.current=Project(pm,'Untitled Project','temporary');pm.projects={}
        result=self.run_proof()
        self.assertTrue(result['previous_project_restored']);self.assertIsNone(pm.current)
        self.assertNotIn('Untitled Project',pm.saves)

    def test_unsaved_project_with_content_requires_manual_save_without_api_save(self):
        pm=self.resolve.pm;pm.current=Project(pm,'Untitled Project','temporary');pm.current.content=True;pm.projects={}
        with self.assertRaisesRegex(ValueError,'has not been saved yet'):self.run_proof()
        self.assertEqual(pm.saves,[]);self.assertEqual(pm.creates,[])

    def test_cached_path_still_rejects_unsaved_work_without_save_modal(self):
        self.run_proof();pm=self.resolve.pm;saves=len(pm.saves);creates=len(pm.creates)
        pm.current=Project(pm,'Untitled Project','temporary');pm.current.content=True
        with self.assertRaisesRegex(ValueError,'has not been saved yet'):self.run_proof()
        self.assertEqual(len(pm.saves),saves);self.assertEqual(len(pm.creates),creates)

    def test_named_project_save_failure_occurs_before_proof_creation(self):
        self.resolve.pm.fail='save_previous'
        with self.assertRaisesRegex(ValueError,'Could not save'):self.run_proof()
        self.assertEqual(self.resolve.pm.creates,[])

    def test_owned_output_symlinks_never_overwrite_other_files(self):
        self.run_proof();folder=self.out/'Resolve Compatibility'
        destination=self.root/'keep.txt';destination.write_text('original')
        for name in ('Proof.fcpxml','Compatibility Report.json','state.json.tmp'):
            with self.subTest(name=name):
                p=folder/name;backup=p.read_bytes() if p.exists() else None
                if p.exists():p.unlink()
                p.symlink_to(destination)
                with self.assertRaisesRegex(ValueError,'symbolic link'):self.run_proof()
                self.assertEqual(destination.read_text(),'original')
                p.unlink()
                if backup is not None:p.write_bytes(backup)

    def test_symlinked_compatibility_directory_is_rejected(self):
        self.out.mkdir();destination=self.root/'existing';destination.mkdir()
        (self.out/'Resolve Compatibility').symlink_to(destination)
        with self.assertRaisesRegex(ValueError,'symbolic link'):self.run_proof()
        self.assertEqual(list(destination.iterdir()),[])


if __name__=='__main__':unittest.main()
