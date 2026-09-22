# ISO Assemble source

Swift/AppKit desktop application with a local Python conversion engine. See the included user instructions and validation report for supported versions and current Premiere limitations.

## Rebuild

Requires Apple's command-line build tools and make. Runtime source archives are distributed inside the app under `Contents/Resources/Legal`.

1. Copy `Python-3.11.16.tar.xz`, `ffmpeg-8.1.3.tar.xz`, and `build-runtimes.sh` into a build/vendor folder.
2. Run `bash build/vendor/build-runtimes.sh`. This compiles Python and a minimal LGPL shared-library ffprobe with network support disabled. No OpenSSL, Homebrew, pip, or third-party Python modules are required at runtime.
3. Run `VENDOR_DIR=/absolute/build/vendor bash build.sh /absolute/output/ISO\ Assemble.app`. The packager relocates Mach-O dependencies, rejects unbundled non-system libraries, includes complete source/license archives and ad-hoc signs the app. Existing bundled runtimes are reused; delete only your build output to force a clean bundle.
4. Run the bundled Python in `engine` with `-m unittest discover -v`.
5. For distribution, use `sign-and-notarize.sh APP 'Developer ID Application: ...' KEYCHAIN_PROFILE`, then `package-dmg.sh APP OUTPUT_DMG README`. This final signing path is supplied but could not be executed without an installed Developer ID identity and notarytool credentials. It is not claimed tested.

`premiere.py` writes supported legacy XMEML, imported by Premiere as native multiclips. `verify_premiere.py` only reads Premiere's saved native project to verify exact timing and angles; it never modifies the project. Resolve uses the local documented scripting API plus native FCPXML import. No Resolve database is modified.

Premiere launch requires the application to be closed first, preventing an XML file-open event from importing into a user's current project. The user performs Save As into the selected results folder; the app watches and validates the resulting `.prproj`. No Accessibility permission, Codex service, Adobe plugin or undocumented scripting call is used.

Unit tests cover parser merging/truncation, recording headers, 29.97 DF minute boundaries throughout a day, source mutation safeguards, audio coverage and Premiere rollover/stereo structure. End-to-end checks and limitations are in the delivered validation report.

## License

ISO Assemble application code is MIT licensed; see LICENSE. Bundled Python and FFmpeg retain their respective PSF and LGPL licenses and complete sources under the app’s Contents/Resources/Legal. Camera labels are read from each user’s ATEM project, not hardcoded to a particular production.
