# Validation and limitations

## Conversion checks

Tested with Resolve Studio 21.0.0.48 and Premiere 26.2.2 on Apple Silicon macOS, using ATEM 1080p 30000/1001 drop-frame recordings. The test production contained eight cameras, 24 camera files, 20 audio ISOs and three program recordings. All 1,335 original live switch positions and selections were verified. These private test recordings and projects are not included in this release.

Resolve: small native multicam proof changed angles through the editor UI and retained that change after saving/reopening. Full exported project was reimported and checked through the supported API. Full-production eight-tile viewer inspection remains outstanding; an active user render was preserved.

Premiere: native eight-angle proof retained a UI angle change after saving/reopening. Full native project reopened with media available. Read-only native-file validation checked all camera paths, selected angles, integer timing and independent stereo program audio. Premiere uses one multicam per physical MP4 segment. One extra same-angle technical splice was required in the test production; no original switch was lost.

Standalone UI: folder selection, ambiguous-project picker, audio selection, Resolve creation/export/reimport and Premiere generation/Save As/automatic validation were exercised. The previous conversion build passed end-to-end; this release changes generic branding, documentation, licensing and runtime build location.

## Release checks

The unit suite covers partial state updates, repeated headers, truncated input, 29.97 drop-frame arithmetic, ambiguous input discovery, changed-media detection, audio coverage and Premiere rollover handling. Release 1.2 passed all 11 tests using its newly compiled bundled Python, including from the mounted read-only DMG with a clean environment. Bundled ffprobe successfully read a source recording. All 79 Mach-O binaries passed the dependency audit. The DMG checksum and deep/strict app signature verification passed. The generic interface opened successfully. Application source and documentation were checked for production-specific names; none remain.

## Known limits

- Ad-hoc signed, not notarized. Public distribution requires a Developer ID identity and Apple notarization. Gatekeeper acceptance on another Mac is not claimed.
- No second-machine certification, Intel build or Windows build.
- Premiere must be closed before creation and requires File → Save As to the displayed output path. Native-file validation follows automatically.
- Resolve version is restricted to the validated version. Other frame rates, editor versions and active unsupported switcher effects require additional implementation or validation.
- No full-show subjective audio/video review or subframe acoustic-latency measurement is claimed.
