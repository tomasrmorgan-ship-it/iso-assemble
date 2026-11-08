#!/bin/bash
set -euo pipefail
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${1:-$SOURCE_DIR/../ISO Assemble.app}"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources/engine"
if [[ -n "${VENDOR_DIR:-}" ]]; then
  python3 "$SOURCE_DIR/package_runtimes.py" --vendor "$VENDOR_DIR" --app "$APP_DIR"
else
  if ! python3 "$SOURCE_DIR/package_runtimes.py" --verify --app "$APP_DIR"; then
    printf 'A complete Python + FFmpeg + ffprobe runtime is required. Run build-runtimes.sh with the accompanying sources, then build with VENDOR_DIR=/path/to/vendor. The older ffprobe-only runtime cannot attach audio.\n' >&2
    exit 2
  fi
fi
cp "$SOURCE_DIR"/engine/*.py "$APP_DIR/Contents/Resources/engine/"
mkdir -p "$APP_DIR/Contents/Resources/Legal"
cp "$SOURCE_DIR/LICENSE" "$APP_DIR/Contents/Resources/Legal/ISO-Assemble-MIT-LICENSE.txt"
xcrun swiftc -O -target arm64-apple-macos13.0 -framework Cocoa "$SOURCE_DIR/ISOAssemble.swift" -o "$APP_DIR/Contents/MacOS/ISOAssemble"
cat > "$APP_DIR/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>ISOAssemble</string>
<key>CFBundleIdentifier</key><string>org.isoassemble.app</string>
<key>CFBundleName</key><string>ISO Assemble</string>
<key>CFBundleDisplayName</key><string>ISO Assemble</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.4.2</string>
<key>CFBundleVersion</key><string>7</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
xcrun swift "$SOURCE_DIR/make_icon.swift" "$APP_DIR/Contents/Resources/AppIcon.iconset"
iconutil -c icns "$APP_DIR/Contents/Resources/AppIcon.iconset" -o "$APP_DIR/Contents/Resources/AppIcon.icns"
/usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string AppIcon" "$APP_DIR/Contents/Info.plist"
codesign --force --deep --sign - "$APP_DIR"
printf 'Built %s\n' "$APP_DIR"
