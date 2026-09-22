#!/bin/bash
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE"
tar -xf Python-3.11.16.tar.xz
tar -xf ffmpeg-8.1.3.tar.xz
cd Python-3.11.16
MACOSX_DEPLOYMENT_TARGET=13.0 ./configure --prefix="$BASE/python-runtime" --enable-shared --without-ensurepip --without-static-libpython > "$BASE/python-configure.log" 2>&1
make -j8 > "$BASE/python-build.log" 2>&1
make install > "$BASE/python-install.log" 2>&1
cd "$BASE/ffmpeg-8.1.3"
./configure --prefix="$BASE/ffprobe-runtime" --disable-autodetect --disable-everything --disable-network --disable-doc --disable-ffmpeg --disable-ffplay --enable-ffprobe --enable-protocol=file --enable-demuxer=mov,wav,aiff,flac --enable-parser=h264,hevc,aac --enable-decoder=h264,hevc,aac,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,flac --enable-shared --disable-static --disable-avdevice --disable-avfilter --disable-swscale --disable-swresample --extra-cflags=-mmacosx-version-min=13.0 --extra-ldflags=-mmacosx-version-min=13.0 > "$BASE/ffprobe-configure.log" 2>&1
make -j8 > "$BASE/ffprobe-build.log" 2>&1
make install > "$BASE/ffprobe-install.log" 2>&1
