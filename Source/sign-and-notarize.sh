#!/bin/bash
# Run only when your Developer ID Application identity and notarytool profile exist.
set -euo pipefail
APP_DIR="${1:?Usage: sign-and-notarize.sh app-path Developer-ID-identity notarytool-profile}"
IDENTITY="${2:?Developer ID Application identity required}"
PROFILE="${3:?Stored notarytool keychain profile required}"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
ENTITLEMENTS="$(mktemp -t isoassemble-entitlements)"
ARCHIVE="$(mktemp -d -t isoassemble-notarize)"
trap 'rm -f "$ENTITLEMENTS"; rm -rf "$ARCHIVE"' EXIT
cat > "$ENTITLEMENTS" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>com.apple.security.cs.disable-library-validation</key><true/></dict></plist>
PLIST
# Python must load Blackmagic's locally installed Resolve scripting library.
while IFS= read -r -d '' binary; do
 if file -b "$binary" | grep -q 'Mach-O'; then
  if [[ "$binary" == */python/bin/python3.11 ]]; then
   codesign --force --sign "$IDENTITY" --options runtime --timestamp --entitlements "$ENTITLEMENTS" "$binary"
  else
   codesign --force --sign "$IDENTITY" --options runtime --timestamp "$binary"
  fi
 fi
done < <(find "$APP_DIR/Contents/Resources/runtime" -type f -print0)
codesign --force --sign "$IDENTITY" --options runtime --timestamp "$APP_DIR"
codesign --verify --deep --strict --verbose=2 "$APP_DIR"
ditto -c -k --sequesterRsrc --keepParent "$APP_DIR" "$ARCHIVE/ISO-Assemble.zip"
xcrun notarytool submit "$ARCHIVE/ISO-Assemble.zip" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$APP_DIR"
xcrun stapler validate "$APP_DIR"
spctl --assess --type execute --verbose=2 "$APP_DIR"
echo 'Signed, notarized and stapled. Rebuild the DMG from this app bundle.'
