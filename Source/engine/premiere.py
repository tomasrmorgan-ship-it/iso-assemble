#!/usr/bin/env python3
"""Premiere's supported legacy FCP XML importer: native eight-angle multiclips.

Premiere imports only the first file of a multiclip angle. Therefore physical
recording boundaries are represented by separate multiclips, with an explicit
technical splice where a live cut crosses that boundary. No media is rendered.
"""
import copy,hashlib,json,xml.etree.ElementTree as E
from pathlib import Path
from convert import build
def timecode(n):
 if n<0:raise ValueError('Negative timecode is unsupported')
 n%=2589408
 tens,remainder=divmod(n,17982)
 dropped=18*tens+2*max(0,(remainder-2)//1798)
 nominal=n+dropped
 h,rem=divmod(nominal,108000);m,rem=divmod(rem,1800);sec,f=divmod(rem,30)
 return f'{h:02d}:{m:02d}:{sec:02d};{f:02d}'


def el(p,t,value=None,**attrs):
 e=E.SubElement(p,t,{k:str(v) for k,v in attrs.items()})
 if value is not None:e.text=str(value)
 return e

def rate(p):
 r=el(p,'rate');el(r,'timebase',30);el(r,'ntsc','TRUE')

def video_format(p):
 for k,v in [('width',1920),('height',1080),('anamorphic','FALSE'),('pixelaspectratio','square'),('fielddominance','none')]:el(p,k,v)
 rate(p)

def tc(p,n):
 t=el(p,'timecode');rate(t);el(t,'frame',n);el(t,'string',timecode(n));el(t,'displayformat','DF')

class Writer:
 def __init__(self):self.files={};self.angles=set()
 def file(self,p,m,video=True):
  path=m['path'];key='file-'+hashlib.sha256(path.encode()).hexdigest()[:16]
  f=el(p,'file',id=key)
  if path in self.files:return f
  self.files[path]=m
  el(f,'name',Path(path).name);el(f,'pathurl',Path(path).as_uri());rate(f);el(f,'duration',m['frames']);tc(f,m['start'])
  media=el(f,'media')
  if video:video_format(el(el(media,'video'),'samplecharacteristics'))
  a=el(media,'audio');sc=el(a,'samplecharacteristics');el(sc,'depth',24 if path.lower().endswith('.wav') else 16);el(sc,'samplerate',m.get('sample_rate',48000));el(a,'channelcount',m.get('channels',2))
  return f
 def item(self,p,m,start,end,source=0,audio=False,name=None):
  c=el(p,'clipitem');el(c,'name',name or Path(m['path']).name);el(c,'duration',m['frames']);rate(c)
  for k,v in [('start',start),('end',end),('in',source),('out',source+end-start)]:el(c,k,v)
  self.file(c,m,not m['path'].lower().endswith('.wav'))
  st=el(c,'sourcetrack');el(st,'mediatype','audio' if audio else 'video');el(st,'trackindex',1)
  if audio:el(c,'channelcount',2)
  return c
 def angle(self,p,m):
  aid='angle-'+hashlib.sha256(m['path'].encode()).hexdigest()[:16]
  c=el(p,'clip',id=aid)
  if aid in self.angles:return
  self.angles.add(aid)
  el(c,'name',f'{m["camera"]} {m["name"]}');el(c,'duration',m['frames']);rate(c);el(c,'in',0);el(c,'out',m['frames']);el(c,'defaultangle',m['camera'])
  self.item(el(el(el(c,'media'),'video'),'track'),m,0,m['frames'])
 def sequence(self,p,name,start,duration):
  s=el(p,'sequence');el(s,'name',name);el(s,'duration',duration);rate(s);tc(s,start)
  media=el(s,'media');v=el(media,'video');video_format(el(el(v,'format'),'samplecharacteristics'));vt=el(v,'track')
  a=el(media,'audio');el(a,'numOutputChannels',2);sc=el(el(a,'format'),'samplecharacteristics');el(sc,'depth',16);el(sc,'samplerate',48000);at=el(a,'track')
  return s,vt,at

def generate(package,name,primary):
 data=package['data'];cat=package['catalog'];_,plan=build(data,name)
 chosen=next((c for c in cat['candidates'] if c['id']==primary and c['selectable']),None)
 if not chosen:raise ValueError('Select a verified primary audio source.')
 if any(m.get('channels',2)!=2 for m in chosen['files']):raise ValueError('Premiere output currently supports stereo primary audio only.')
 groups={}
 for m in data['media']:groups.setdefault((m['start'],m['end']),[]).append(m)
 for g in groups.values():
  if sorted(m['camera'] for m in g)!=sorted(plan['camera_names']):raise ValueError('Premiere requires matching recording boundaries across every camera.')
 r=E.Element('xmeml',version='5');project=el(r,'project');el(project,'name',name);children=el(project,'children');w=Writer()
 seq,vt,at=w.sequence(children,name+'_Edit',plan['origin'],plan['end']-plan['origin']);expected=[];splices=[]
 for cut in plan['cuts']:
  if cut['angle'] in (None,0):continue
  remaining=cut['end']-cut['start']
  for (start,end),angles in sorted(groups.items()):
   a,b=max(cut['start'],start),min(cut['end'],end)
   if b<=a:continue
   m=next(m for m in angles if m['camera']==cut['angle'])
   c=w.item(vt,m,a-plan['origin'],b-plan['origin'],a-start,name=f'{cut["angle"]} {m["name"]}')
   mc=el(c,'multiclip',id=f'mc-{start}');el(mc,'name',f'{name}_Multicam_{timecode(start).replace(":","-").replace(";","-")}');el(mc,'collapsed','FALSE');el(mc,'synctype',1)
   for angle in sorted(angles,key=lambda x:x['camera']):
    ae=el(mc,'angle');el(ae,'activevideoangle','TRUE' if angle['camera']==cut['angle'] else 'FALSE');el(ae,'activeaudioangle','FALSE');w.angle(ae,angle)
   expected.append(dict(start=a,end=b,angle=cut['angle'],source_in=a-start,group_start=start,group_end=end));remaining-=b-a
   if a>cut['start']:splices.append(dict(frame=a,angle=cut['angle'],reason='Physical MP4 boundary inside original live edit; angle unchanged'))
  if remaining:raise ValueError(f'Uncovered live cut at {cut["start"]}')
 for m in chosen['files']:w.item(at,m,m['start']-plan['origin'],m['end']-plan['origin'],audio=True)
 program=next((c for c in cat['candidates'] if c['id']=='program' and c['selectable']),None)
 if program:
  _,rv,ra=w.sequence(children,'Live_Program_Reference',plan['origin'],plan['end']-plan['origin'])
  for m in program['files']:
   w.item(rv,m,m['start']-plan['origin'],m['end']-plan['origin']);w.item(ra,m,m['start']-plan['origin'],m['end']-plan['origin'],audio=True)
 bin=el(children,'bin');el(bin,'name','All Audio ISOs');bc=el(bin,'children')
 for m in cat['inventory']:
  if m['kind']!='audio_iso':continue
  c=el(bc,'clip');el(c,'name',Path(m['path']).name);el(c,'duration',m['frames']);rate(c);el(c,'in',0);el(c,'out',m['frames'])
  w.item(el(el(el(c,'media'),'audio'),'track'),m,0,m['frames'],audio=True)
 # Premiere's stereo representation uses two linked exploded channels.
 serial=0
 for audio_node in r.findall('.//audio'):
  tracks=audio_node.findall('track')
  for left in tracks:
   right=copy.deepcopy(left)
   for idx,track in enumerate((left,right)):
    track.attrib.update(currentExplodedTrackIndex=str(idx),totalExplodedTrackCount='2',premiereTrackType='Stereo')
    el(track,'outputchannelindex',idx+1)
   for ci,(lc,rc) in enumerate(zip(left.findall('clipitem'),right.findall('clipitem')),1):
    serial+=1;ids=[f'audio-{serial}-L',f'audio-{serial}-R']
    for idx,c in enumerate((lc,rc)):
     c.set('id',ids[idx]);c.set('premiereChannelType','stereo');c.find('sourcetrack/trackindex').text=str(idx+1)
     for j,ref in enumerate(ids):
      link=el(c,'link');el(link,'linkclipref',ref);el(link,'mediatype','audio');el(link,'trackindex',j+1);el(link,'clipindex',ci);el(link,'groupindex',1)
     if idx==1:
      f=c.find('file');f.clear();f.set('id',lc.find('file').get('id'))
   audio_node.append(right)
 E.indent(r)
 report=dict(name=name,origin=plan['origin'],end=plan['end'],cuts=expected,original_live_cuts=sum(c['angle'] not in (None,0) for c in plan['cuts']),native_multicam_groups=len(groups),technical_splices=splices,camera_names=plan['camera_names'],media_paths=sorted(w.files),audio=chosen,recording_sessions=plan['sessions'],warnings=data['warnings']+cat['warnings'],status='XML generated; Premiere import, Save As and native verification required')
 return E.tostring(r,encoding='utf-8',xml_declaration=True),report
