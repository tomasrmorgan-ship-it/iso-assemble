#!/usr/bin/env python3
"""Bundle and verify self-built, dynamically linked local media runtimes.

No downloaded/system FFmpeg is substituted. --verify also checks an existing app
before build.sh reuses it, so an older ffprobe-only bundle cannot ship as 1.4.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

SYSTEM_PREFIXES = ('/System/Library/', '/usr/lib/')
REQUIRED = ('python/bin/python3.11', 'ffmpeg/bin/ffmpeg', 'ffprobe/bin/ffprobe')


def run(args, **kwargs):
    return subprocess.check_output([str(a) for a in args], text=True,
                                   stderr=subprocess.STDOUT, **kwargs)


def macho_files(root):
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        if 'Mach-O' in run(['file', '-b', path]):
            yield path


def dependencies(path):
    return [row.strip().split(' (')[0]
            for row in run(['otool', '-L', path]).splitlines()[1:]]


def verify(runtime):
    runtime = runtime.resolve()
    for rel in REQUIRED:
        path = runtime / rel
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError(f'Missing executable {path}. Rebuild with build-runtimes.sh, '
                               'then set VENDOR_DIR when running build.sh; ffprobe-only runtimes are insufficient.')
    for path in runtime.rglob('*'):
        if path.is_symlink() and (not path.resolve().is_relative_to(runtime) or not path.exists()):
            raise RuntimeError(f'Runtime symlink escapes bundle or is broken: {path}')
    binaries = list(macho_files(runtime))
    for path in binaries:
        if 'arm64' not in run(['lipo', '-archs', path]).split():
            raise RuntimeError(f'Runtime does not contain arm64: {path}')
        for dep in dependencies(path):
            if dep.startswith(SYSTEM_PREFIXES):
                continue
            if dep.startswith('@loader_path/'):
                target = (path.parent / dep[len('@loader_path/'):]).resolve()
                if target.is_relative_to(runtime) and target.is_file():
                    continue
            raise RuntimeError(f'Unbundled or unresolved dependency {dep} in {path}')
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('DYLD_', 'PYTHON'))}
    env['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    run([runtime / 'python/bin/python3.11', '-I', '-c',
         'import ctypes, hashlib, json, subprocess, wave; assert hasattr(ctypes, "CDLL")'], env=env)
    ffmpeg = runtime / 'ffmpeg/bin/ffmpeg'
    version = run([ffmpeg, '-version'], env=env)
    if not version.startswith('ffmpeg version 8.1.3'):
        raise RuntimeError('Expected the source-built FFmpeg 8.1.3 runtime')
    probe_version = run([runtime / 'ffprobe/bin/ffprobe', '-version'], env=env)
    if not probe_version.startswith('ffprobe version 8.1.3'):
        raise RuntimeError('Expected the source-built ffprobe 8.1.3 runtime')
    if '--disable-network' not in version or '--enable-gpl' in version or '--enable-nonfree' in version:
        raise RuntimeError('FFmpeg must be an LGPL build with networking disabled')
    protocols_output = run([ffmpeg, '-hide_banner', '-protocols'], env=env)
    protocols = {line.strip() for line in protocols_output.splitlines()
                 if re.fullmatch(r'\s+[a-z][a-z0-9_]+\s*', line)}
    if protocols != {'file', 'pipe', 'md5'}:
        raise RuntimeError(f'Unexpected FFmpeg protocols: {sorted(protocols)}')
    requirements = {
        'filter': ('atrim', 'asetpts', 'aformat', 'anull', 'aresample'),
        'encoder': ('pcm_s24le',),
        'decoder': ('pcm_s24le', 'h264', 'hevc'),
        'demuxer': ('mov', 'wav'),
        'muxer': ('mov', 'md5', 's24le'),
    }
    for kind, names in requirements.items():
        for name in names:
            help_text = run([ffmpeg, '-hide_banner', '-h', f'{kind}={name}'], env=env)
            if not re.search(r'^' + kind.title() + r'\s+' + re.escape(name) + r'\b', help_text, re.M):
                raise RuntimeError(f'Bundled FFmpeg is missing {kind} {name}')
    return {'schema': 1, 'python': '3.11.16', 'ffmpeg': '8.1.3',
            'architecture': 'arm64', 'minimum_macos': '13.0',
            'protocols': sorted(protocols), 'features': requirements,
            'macho_files_checked': len(binaries), 'dependencies': 'bundle and macOS system libraries only'}


def package(vendor, app):
    resources = app / 'Contents/Resources'
    resources.mkdir(parents=True, exist_ok=True)
    roots = {'python': (vendor / 'python-runtime').resolve(),
             'ffmpeg': (vendor / 'ffmpeg-runtime').resolve()}
    for name, rel in (('python', 'bin/python3.11'), ('ffmpeg', 'bin/ffmpeg'), ('ffmpeg', 'bin/ffprobe')):
        if not (roots[name] / rel).is_file():
            raise RuntimeError(f'Missing {roots[name] / rel}. Run build-runtimes.sh {vendor}; '
                               'an old ffprobe-runtime cannot provide audio attachment.')
    legal_sources = [
        (vendor / 'Python-3.11.16/LICENSE', 'Python-LICENSE.txt'),
        (vendor / 'ffmpeg-8.1.3/COPYING.LGPLv2.1', 'FFmpeg-LGPL-2.1.txt'),
        (vendor / 'ffmpeg-8.1.3/LICENSE.md', 'FFmpeg-LICENSE.md'),
        (vendor / 'ffmpeg-8.1.3/LICENSE.md', 'FFmpeg-LICENSE.txt'),
        (vendor / 'Python-3.11.16.tar.xz', 'Python-3.11.16.tar.xz'),
        (vendor / 'ffmpeg-8.1.3.tar.xz', 'ffmpeg-8.1.3.tar.xz'),
        (Path(__file__).with_name('build-runtimes.sh'), 'build-runtimes.sh'),
        (Path(__file__), 'package_runtimes.py'),
    ]
    for src, _ in legal_sources:
        if not src.is_file():
            raise RuntimeError(f'Missing corresponding runtime source/license: {src}')
    with tempfile.TemporaryDirectory(prefix='.runtime-stage-', dir=resources) as temp:
        staged = Path(temp)
        runtime = staged / 'runtime'
        runtime.mkdir()
        for name, src in roots.items():
            shutil.copytree(src, runtime / name, symlinks=True,
                            ignore=shutil.ignore_patterns('__pycache__', 'test', 'tests',
                                                         'idlelib', 'ensurepip', 'tkinter'))
            for rel in ('include', 'share', 'lib/pkgconfig'):
                tree = runtime / name / rel
                if tree.exists():
                    shutil.rmtree(tree)
        for tree in (runtime / 'python/lib').glob('python*/config-*'):
            shutil.rmtree(tree)
        # Keep the existing probe path without shipping a second set of libraries.
        (runtime / 'ffprobe/bin').mkdir(parents=True)
        (runtime / 'ffprobe/bin/ffprobe').symlink_to('../../ffmpeg/bin/ffprobe')
        for path in macho_files(runtime):
            for old in dependencies(path):
                if old.startswith(SYSTEM_PREFIXES):
                    continue
                target = None
                if old.startswith('/'):
                    for name, source in roots.items():
                        resolved = Path(old).resolve()
                        if resolved.is_relative_to(source):
                            target = runtime / name / resolved.relative_to(source)
                            break
                if target is None or not target.is_file():
                    raise RuntimeError(f'Cannot bundle dependency {old} in {path}')
                new = '@loader_path/' + os.path.relpath(target, path.parent)
                subprocess.run(['install_name_tool', '-change', old, new, str(path)], check=True)
            if path.suffix == '.dylib':
                subprocess.run(['install_name_tool', '-id', '@loader_path/' + path.name, str(path)], check=True)
            subprocess.run(['codesign', '--force', '--sign', '-', str(path)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result = verify(runtime)
        result['source_sha256'] = {name: hashlib.sha256(src.read_bytes()).hexdigest()
                                   for src, name in legal_sources if name.endswith('.tar.xz')}
        (runtime / 'runtime-manifest.json').write_text(json.dumps(result, indent=2) + '\n')
        legal = staged / 'Legal'
        legal.mkdir()
        for src, name in legal_sources:
            shutil.copy2(src, legal / name)
        (legal / 'README.txt').write_text(
            'Python 3.11.16 (PSF license) and FFmpeg/ffprobe 8.1.3 (LGPL 2.1 or later) are bundled. '
            'Complete unmodified source archives, licenses, build recipe and relocation script accompany these binaries. '
            'FFmpeg has no network protocols and uses no GPL or nonfree components. Its libraries are dynamically linked and replaceable. '
            'Reverse engineering for debugging modifications to the LGPL libraries is permitted. Re-sign locally after replacing libraries. '
            'The ffprobe compatibility path links to the same FFmpeg installation. '
            'Official sources: https://www.python.org/ftp/python/3.11.16/Python-3.11.16.tar.xz and '
            'https://ffmpeg.org/releases/ffmpeg-8.1.3.tar.xz. No recording media or Resolve/Adobe libraries are bundled.\n')
        destination = resources / 'runtime'
        if destination.exists() or destination.is_symlink():
            destination.rename(staged / 'previous-runtime')
        runtime.rename(destination)
        (resources / 'Legal').mkdir(exist_ok=True)
        for path in legal.iterdir():
            shutil.copy2(path, resources / 'Legal' / path.name)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', type=Path)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--verify', action='store_true', help='Verify an existing app without changing it')
    args = parser.parse_args()
    try:
        if args.verify:
            result = verify(args.app.resolve() / 'Contents/Resources/runtime')
        else:
            if not args.vendor:
                parser.error('--vendor is required unless --verify is used')
            result = package(args.vendor.resolve(), args.app.resolve())
        print(json.dumps(result, indent=2))
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f'Runtime packaging failed: {exc}\n')


if __name__ == '__main__':
    main()
