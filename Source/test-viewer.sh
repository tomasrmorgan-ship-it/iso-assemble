#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != Darwin ]]; then
  printf 'Resolve viewer tests require macOS and the Xcode command-line tools.\n' >&2
  exit 2
fi

viewer_test_source="$(cd "$(dirname "$0")" && pwd)"
viewer_test_build="$(mktemp -d "${TMPDIR:-/tmp}/isoassemble-viewer-tests.XXXXXX")"
trap 'rm -rf "$viewer_test_build"' EXIT

xcrun swiftc -O -framework Cocoa -framework ApplicationServices \
  "$viewer_test_source/ResolveViewer.swift" \
  "$viewer_test_source/Tests/ResolveViewerTests.swift" \
  -o "$viewer_test_build/ResolveViewerTests"
"$viewer_test_build/ResolveViewerTests"
