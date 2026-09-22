#!/usr/bin/env python3
"""Bundle self-built runtimes and relocate all non-system Mach-O dependencies."""
import argparse,os,shutil,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--vendor',required=True);p.add_argument('--app',required=True);a=p.parse_args()
vendor=Path(a.vendor).resolve();app=Path(a.app).resolve();resources=app/'Contents/Resources';runtime=resources/'runtime'
if runtime.exists():shutil.rmtree(runtime)
runtime.mkdir()
shutil.copytree(vendor/'python-runtime',runtime/'python',symlinks=True,ignore=shutil.ignore_patterns('__pycache__','test','tests','idlelib','ensurepip','tkinter'))
shutil.copytree(vendor/'ffprobe-runtime',runtime/'ffprobe',symlinks=True)
# Exclude development headers, pkgconfig and manuals from execution bundle.
for tree in [runtime/'python/include',runtime/'python/share',runtime/'ffprobe/include',runtime/'ffprobe/share']:
 if tree.exists():shutil.rmtree(tree)
for tree in (runtime/'python/lib').glob('python*/config-*'):shutil.rmtree(tree)
for path in sorted(runtime.rglob('*')):
 if path.is_symlink() or not path.is_file():continue
 if 'Mach-O' not in subprocess.check_output(['file','-b',str(path)],text=True):continue
 try:deps=subprocess.check_output(['otool','-L',str(path)],text=True).splitlines()[1:]
 except subprocess.CalledProcessError:continue
 for row in deps:
  old=row.strip().split(' (')[0]
  if old.startswith('/') and Path(old).resolve().is_relative_to(vendor):
   suffix=Path(old).resolve().relative_to(vendor)
   if suffix.parts[0] not in ('python-runtime','ffprobe-runtime'):raise RuntimeError(f'Unexpected dependency: {old}')
   target=runtime/('python' if suffix.parts[0]=='python-runtime' else 'ffprobe')/Path(*suffix.parts[1:])
   if not target.exists():raise RuntimeError(f'Missing bundled dependency {target}')
   new='@loader_path/'+os.path.relpath(target,path.parent)
   subprocess.run(['install_name_tool','-change',old,new,str(path)],check=True)
  elif old.startswith('/') and not old.startswith(('/System/Library/','/usr/lib/')):raise RuntimeError(f'Unbundled dependency {old}')
 if path.suffix=='.dylib':subprocess.run(['install_name_tool','-id','@loader_path/'+path.name,str(path)],check=True)
 subprocess.run(['codesign','--force','--sign','-',str(path)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
legal=resources/'Legal';legal.mkdir(exist_ok=True)
for src,name in [(vendor/'Python-3.11.16/LICENSE','Python-LICENSE.txt'),(vendor/'ffmpeg-8.1.3/COPYING.LGPLv2.1','FFmpeg-LGPL-2.1.txt'),(vendor/'ffmpeg-8.1.3/LICENSE.md','FFmpeg-LICENSE.md'),(vendor/'Python-3.11.16.tar.xz','Python-3.11.16.tar.xz'),(vendor/'ffmpeg-8.1.3.tar.xz','ffmpeg-8.1.3.tar.xz'),(vendor/'build-runtimes.sh','build-runtimes.sh')]:shutil.copy2(src,legal/name)
(legal/'README.txt').write_text('Python 3.11.16 (PSF license) and FFmpeg 8.1.3 (LGPL 2.1 or later) are bundled. Complete unmodified sources, licenses and build recipe accompany this binary. FFmpeg libraries are dynamically linked and replaceable. Reverse engineering for debugging modifications to the LGPL libraries is permitted. Re-sign locally after replacing libraries. Official sources: https://www.python.org/ftp/python/3.11.16/Python-3.11.16.tar.xz and https://ffmpeg.org/releases/ffmpeg-8.1.3.tar.xz. No recording media or Resolve/Adobe libraries are bundled.\n')
print(runtime)
