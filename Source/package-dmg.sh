#!/bin/bash
set -euo pipefail
APP_DIR="${1:?App bundle required}"
DMG_PATH="${2:?DMG output path required}"
README_PATH="${3:?User read-me path required}"
STAGING="$(mktemp -d -t isoassemble-dmg)"
trap 'rm -rf "$STAGING"' EXIT
ditto "$APP_DIR" "$STAGING/ISO Assemble.app"
cp "$README_PATH" "$STAGING/Read Me.md"
ln -s /Applications "$STAGING/Applications"
hdiutil create -volname 'ISO Assemble 1.2' -srcfolder "$STAGING" -format UDZO -ov "$DMG_PATH"
hdiutil verify "$DMG_PATH"
