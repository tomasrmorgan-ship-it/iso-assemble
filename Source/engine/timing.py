"""Exact progressive ATEM frame rates and SMPTE timecode arithmetic."""
from fractions import Fraction
import re
RATES={'23.976':(24000,1001),'23.98':(24000,1001),'24':(24,1),'25':(25,1),'29.97':(30000,1001),'30':(30,1),'50':(50,1),'59.94':(60000,1001),'60':(60,1)}
class Timing:
 def __init__(self,rate='30000/1001',drop=True):
  self.fps=Fraction(rate)
  if self.fps not in [Fraction(*x) for x in RATES.values()]:raise ValueError(f'Unsupported frame rate: {rate}')
  self.nominal=round(self.fps);self.drop=bool(drop)
  if self.drop and self.fps not in (Fraction(30000,1001),Fraction(60000,1001)):raise ValueError('Drop-frame timecode requires 29.97 or 59.94 fps')
  self.skip=self.nominal//15 if self.drop else 0
  self.day=self.nominal*86400-self.skip*(1440-144)
 @classmethod
 def from_plan(cls,p):
  t=p.get('timing',{});return cls(t.get('fps','30000/1001'),t.get('drop',True))
 @classmethod
 def from_mode(cls,mode,tc):
  m=re.fullmatch(r'1080p(23\.976|23\.98|24|25|29\.97|30|50|59\.94|60)',mode or '')
  if not m:raise ValueError(f'Unsupported video mode: {mode}; expected progressive 1080p at 23.976, 24, 25, 29.97, 30, 50, 59.94 or 60 fps')
  return cls(Fraction(*RATES[m[1]]),';' in tc)
 def data(self):return dict(fps=str(self.fps),drop=self.drop)
 def frames(self,tc):
  m=re.fullmatch(r'(\d{2}):(\d{2}):(\d{2})([:;])(\d{2})',tc)
  if not m:raise ValueError(f'Invalid timecode: {tc}')
  h,mi,s,f=map(int,(m[1],m[2],m[3],m[5]))
  if h>23 or mi>59 or s>59 or f>=self.nominal:raise ValueError(f'Invalid timecode: {tc}')
  if (m[4]==';')!=self.drop:raise ValueError(f'Timecode DF/NDF mode mismatch: {tc}')
  if self.drop and mi%10 and s==0 and f<self.skip:raise ValueError(f'Nonexistent drop-frame label: {tc}')
  return ((h*60+mi)*60+s)*self.nominal+f-self.skip*(h*60+mi-(h*60+mi)//10)
 def timecode(self,n):
  if n<0:raise ValueError('Negative timecode is unsupported')
  n%=self.day
  if self.drop:
   ten=self.nominal*600-self.skip*9;minute=self.nominal*60-self.skip
   blocks,remainder=divmod(n,ten);n+=self.skip*9*blocks+self.skip*max(0,(remainder-self.skip)//minute)
  h,n=divmod(n,self.nominal*3600);m,n=divmod(n,self.nominal*60);s,f=divmod(n,self.nominal)
  return f'{h:02d}:{m:02d}:{s:02d}{";" if self.drop else ":"}{f:02d}'
 def seconds(self,n):return Fraction(n,1)/self.fps
 def xml_time(self,n):return f'{n*self.fps.denominator}/{self.fps.numerator}s'
 @property
 def display(self):return 'DF' if self.drop else 'NDF'
 @property
 def resolve_rate(self):return next(k for k,v in RATES.items() if Fraction(*v)==self.fps)
 @property
 def ticks(self):
  value=254016000000/self.fps
  if value.denominator!=1:raise ValueError('Frame rate is not integral in Premiere ticks')
  return int(value)
