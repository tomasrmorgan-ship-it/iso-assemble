#!/bin/bash
# Build redistributable Apple Silicon runtimes from the accompanying sources.
set -euo pipefail
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
VENDOR_DIR="${1:-$SOURCE_DIR}"
FFMPEG_ONLY="${2:-}"
if [[ "$FFMPEG_ONLY" != "" && "$FFMPEG_ONLY" != "--ffmpeg-only" ]]; then
  printf 'Usage: %s [vendor-directory] [--ffmpeg-only]\n' "$0" >&2
  exit 2
fi
mkdir -p "$VENDOR_DIR"
VENDOR_DIR="$(cd "$VENDOR_DIR" && pwd)"
for archive in Python-3.11.16.tar.xz ffmpeg-8.1.3.tar.xz; do
  if [[ ! -f "$VENDOR_DIR/$archive" ]]; then
    printf 'Missing source archive: %s/%s. Copy the accompanying Legal source archive here before building.\n' "$VENDOR_DIR" "$archive" >&2
    exit 2
  fi
done
if [[ "$(uname -m)" != arm64 ]]; then
  printf 'This build recipe targets Apple Silicon (arm64) macOS 13 or later.\n' >&2
  exit 2
fi
JOBS="${BUILD_JOBS:-$(sysctl -n hw.ncpu)}"
if [[ "$SOURCE_DIR/build-runtimes.sh" != "$VENDOR_DIR/build-runtimes.sh" ]]; then
  cp "$SOURCE_DIR/build-runtimes.sh" "$VENDOR_DIR/build-runtimes.sh"
fi
cd "$VENDOR_DIR"
if [[ ! -d Python-3.11.16 ]]; then tar -xf Python-3.11.16.tar.xz; fi
if [[ ! -d ffmpeg-8.1.3 ]]; then tar -xf ffmpeg-8.1.3.tar.xz; fi
if [[ "$FFMPEG_ONLY" == --ffmpeg-only ]]; then
  if [[ ! -x "$VENDOR_DIR/python-runtime/bin/python3.11" ]]; then
    printf '%s\n' '--ffmpeg-only requires an existing self-built python-runtime with its source archive and LICENSE.' >&2
    exit 2
  fi
else
  printf 'Building Python 3.11.16; logs: %s/python-*.log\n' "$VENDOR_DIR"
  mkdir -p python-build
  cd python-build
  MACOSX_DEPLOYMENT_TARGET=13.0 "$VENDOR_DIR/Python-3.11.16/configure" \
    --prefix="$VENDOR_DIR/python-runtime" --enable-shared --without-ensurepip \
    --without-static-libpython > "$VENDOR_DIR/python-configure.log" 2>&1
  make -j"$JOBS" > "$VENDOR_DIR/python-build.log" 2>&1
  make install > "$VENDOR_DIR/python-install.log" 2>&1
  cd "$VENDOR_DIR"
fi
printf 'Building FFmpeg/ffprobe 8.1.3 (LGPL, local files only); logs: %s/ffmpeg-*.log\n' "$VENDOR_DIR"
mkdir -p ffmpeg-build
cd ffmpeg-build
"$VENDOR_DIR/ffmpeg-8.1.3/configure" \
  --prefix="$VENDOR_DIR/ffmpeg-runtime" \
  --disable-autodetect --disable-everything --disable-network --disable-doc \
  --disable-gpl --disable-nonfree --disable-version3 \
  --enable-ffmpeg --enable-ffprobe --disable-ffplay \
  --enable-protocol=file,pipe,md5 \
  --enable-demuxer=mov,wav,aiff,flac \
  --enable-muxer=mov,mp4,wav,md5,pcm_s24le \
  --enable-parser=h264,hevc,aac \
  --enable-decoder=h264,hevc,aac,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,flac \
  --enable-encoder=pcm_s24le \
  --enable-filter=atrim,asetpts,aformat,anull,aresample \
  --enable-shared --disable-static --disable-avdevice --disable-swscale \
  --enable-swresample --enable-avfilter \
  --extra-cflags=-mmacosx-version-min=13.0 \
  --extra-ldflags=-mmacosx-version-min=13.0 > "$VENDOR_DIR/ffmpeg-configure.log" 2>&1
make -j"$JOBS" > "$VENDOR_DIR/ffmpeg-build.log" 2>&1
make install > "$VENDOR_DIR/ffmpeg-install.log" 2>&1
"$VENDOR_DIR/ffmpeg-runtime/bin/ffmpeg" -version
"$VENDOR_DIR/ffmpeg-runtime/bin/ffprobe" -version
printf 'Runtimes ready: %s. Package with package_runtimes.py to relocate and verify dependencies.\n' "$VENDOR_DIR"
