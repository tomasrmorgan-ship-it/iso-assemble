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
- Resolve version is restricted to the validated version. Other editor versions and active unsupported switcher effects require additional implementation or validation. See the version 1.3 rate matrix below.
- No full-show subjective audio/video review or subframe acoustic-latency measurement is claimed.


## Version 1.3 frame-rate expansion

Eight progressive 1080p rates are accepted: 23.976 (24000/1001; ATEM label 23.98 also accepted), 24, 25, 29.97 (30000/1001), 30, 50, 59.94 (60000/1001), and 60. Both DF and NDF are accepted at 29.97 and 59.94, making ten rate/timecode combinations. No frame interpolation or transcoding is performed.

A shared exact rational timing model now drives ATEM event parsing, camera timecodes/durations, audio sample alignment, FCPXML frame durations, Resolve settings, Premiere timebase/NTSC flags and native-project tick validation. DF skips two labels per ordinary minute at 29.97 and four at 59.94. Missing mode headers, unsupported modes, mixed timecode conventions, rate changes and mismatched media fail preflight.

Automated checks: 16 tests pass. Tests round-trip timecodes around all 1,440 daily minute boundaries in every rate/mode, verify midnight rollover, reject illegal DF labels, and check preflight, stereo audio alignment and both XML exporters across the matrix. Eight synthetic 1080p H.264 MP4 camera files per combination (80 total) passed real ffprobe preflight. The original production's Resolve and Premiere cut lists are unchanged. A real 1080p23.98 ATEM recording also passed the new bundled-runtime preflight: eight camera files, ten audio ISOs, 921 live cuts, all 11 primary-audio choices available, and no timing warnings. No new editor project was created from that private recording during this check.

Inside Resolve Studio 21.0.0.48: each of the ten combinations imported as two native eight-angle multicam cuts spanning a minute boundary. Exact cut positions, selected camera names, timeline rate and DF/NDF origin were checked through the documented API. Saving/reopening and exporting/reimporting a native DRP passed for every combination. These are synthetic-media tests, not full production recordings at each new rate. No new UI angle-switch exercise was performed per rate.

Premiere: XML rate fields, frame positions and audio construction are tested automatically across all ten combinations. Native Premiere import/save/reopen at the newly added rates remains unverified; the earlier 29.97 DF native-project proof remains the only real-editor Premiere rate validation. Expanded Premiere rates should be treated as preview support until those checks are completed.

Interlaced modes, other resolutions, variable/mixed-rate media and rates outside this matrix remain unsupported. All existing signing/distribution limitations still apply.
