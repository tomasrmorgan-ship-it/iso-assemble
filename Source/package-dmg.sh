#!/bin/bash
set -euo pipefail
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${1:?App bundle required}"
DMG_PATH="${2:?DMG output path required}"
README_PATH="${3:?User read-me path required}"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP_DIR/Contents/Info.plist")"
BUILD="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP_DIR/Contents/Info.plist")"
if [[ "$VERSION" != 1.4.3 || "$BUILD" != 8 ]]; then
  printf 'Expected ISO Assemble 1.4.3 build 8; found %s build %s. Build the current app before packaging.\n' "$VERSION" "$BUILD" >&2
  exit 2
fi
python3 "$SOURCE_DIR/package_runtimes.py" --verify --app "$APP_DIR"
if [[ ! -f "$README_PATH" ]]; then
  printf 'Read-me file not found: %s\n' "$README_PATH" >&2
  exit 2
fi
STAGING="$(mktemp -d -t isoassemble-dmg)"
trap 'rm -rf "$STAGING"' EXIT
ditto "$APP_DIR" "$STAGING/ISO Assemble.app"
mkdir -p "$STAGING/Documentation"
cp "$README_PATH" "$STAGING/Documentation/Read Me.md"
TEXT_PATH="${README_PATH%.md}.txt"
if [[ -f "$TEXT_PATH" ]]; then
  cp "$TEXT_PATH" "$STAGING/Documentation/Read Me.txt"
else
  cp "$README_PATH" "$STAGING/Documentation/Read Me.txt"
fi
# Keep the linked feature guide and validation notes with the installer.
DOC_DIR="$(dirname "$README_PATH")"
if [[ -f "$DOC_DIR/SharedAudio.md" ]]; then
  cp "$DOC_DIR"/*.md "$DOC_DIR"/*.txt "$STAGING/Documentation/"
fi
ln -s /Applications "$STAGING/Applications"
mkdir -p "$(dirname "$DMG_PATH")"
hdiutil create -volname 'ISO Assemble 1.4.3' -srcfolder "$STAGING" -format UDZO -ov "$DMG_PATH"
hdiutil verify "$DMG_PATH"
