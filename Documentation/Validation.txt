# Validation and limitations

## Version 1.4.3: organized media and the active cut timeline

Version 1.4.3 (build 8) addresses the handoff into Resolve: native multicam source clips and the finished cut timeline are placed in separate, clearly named bins. The generated edit is selected before save/export. Reopen validation checks that the active timeline is the finished edit and verifies its organized media. The completed export is identified by SHA-256, so an earlier verification project cannot stand in for changed DRP bytes.

Each normal Resolve Create now allocates a new dated run folder under the selected results folder's `Projects` directory and uses an available Resolve project name. Existing exports, legacy conversion state and previous compatibility reports do not supply the new result. The run performs its own compatibility proof and exact-export validation, preserving older projects and original media. Successful runs clean up only their own temporary test projects after checking identity; cleanup problems preserve the affected project and are reported. Lower-level ownership and idempotence checks remain implementation safeguards; they do not make the normal app reuse an earlier conversion.

Organization uses supported media-pool APIs. Only exact manifest source paths, generated multicam names and generated timeline identities are eligible to move. Camera originals, audio ISOs and program references remain local file references. Unrelated clips stay in their existing bins. Duplicate matches and conflicting ownership stop with a readable error. The layout helper is idempotent within one owned project; a new app Create still gets a fresh project.

The selection check places the playhead on the first actual native multicam cut, verifies its camera selection and frame interval, and handles drop-frame and midnight timecodes with integer arithmetic. Read-only inspection always requires the finished edit to be active. It can separately require the first-cut position; the current bin and playhead are otherwise reported without assuming those interface choices persist across project import.

The version 1.4.3 source suite passed **198 of 198 tests**, including all **four generated-media integration tests**. The 23 focused layout tests cover preserved unrelated clips, ambiguous source/bin rejection, failed or unapplied API calls, active timeline identity, first-cut selection after a gap or black, and midnight readback. The broader suite includes fresh-run isolation, project ownership, exact-export verification, compatibility, timing, audio mapping and existing exporters. API stand-ins and generated-media checks are automated evidence; the native editor checks below are separate.

Inside **Resolve Studio 21.1.1.10**, a generated recording with two MOV camera sources, two native multicam cuts, a ten-frame Mix and independent WAV audio passed creation, save, export and reimport. Supported API checks confirmed organized bins, the active finished edit, the first actual cut, camera selections, timing, media and audio. The exact exported DRP was identified by SHA-256.

In the native editor UI, a video-only change to Camera 2 was made with Option-click. The project was exported and reimported, retaining that angle selection, two video cuts and one independent audio item. The UI also displayed the camera-angle grid, program picture, cut timeline and WAV audio after the documented manual viewing steps. This is a small-fixture editability check, not a full-production visual review.

The actual 1.4.3 QA app then completed **two consecutive Create New Resolve Project runs**, using an existing results folder and a project name already present in Resolve. Each generated a distinct new project, run folder and DRP, performed its own native compatibility proof, exported and reimported the finished edit, and returned to that Edit timeline. Six owned temporary test projects were removed without warnings, leaving only one additional finished project per Create. Earlier DRP hashes were unchanged. This verifies the normal fresh-run workflow.

Optional macOS Accessibility automation prepares the Multicam viewer and Full Extent Zoom. It is separate from project construction and API verification. The app's permission-denied path was tested: it preserved successful DRP creation and supplied the manual fallback. The equivalent manual controls were exercised through desktop automation. The bundled helper's permission-granted path has not yet been validated. A DRP does not guarantee viewer layout on a recipient's Mac, and the helper does not perform or claim an unattended angle-change test.

Packaging checks passed for the 1.4.3 DMG: disk-image integrity verification, a read-only mount and strict app-signature verification. The app's bundled runtime ran the 198-test suite with **194 passing and four optional fixture-generation integration tests skipped**; the separate source run passed all 198 with those integrations enabled. The build remains ad-hoc signed and non-notarized.

Resolve 21.2.0.6, a clean second Mac, full-production visual review and new Premiere editor validation remain outside this patch's native test coverage.

## Version 1.4.2: historical Resolve runtime compatibility

Version 1.4.1 rejected Resolve Studio **21.2.0.6** because its version check allowed only two exact build strings. Version 1.4.2 (build 7) removes that whitelist: cut-only conversion requires Studio 21 or later, while optional Mix review requires Studio 21.1 or later. Meeting the minimum version permits a runtime check; it does not guarantee that every later Resolve release works.

In version 1.4.2, before full conversion, the app checked the installed Resolve with a small native two-angle, two-selection multicam project, including save, export and reimport. Mix mode also requires a native Cross Dissolve with verified geometry. The proof uses ownership-checked projects and a `Resolve Compatibility/Compatibility Report.json` report. That release allowed a cached result only when it matched the Resolve version, recording timing, source snapshot and proof code. Version 1.4.3 instead uses a fresh proof folder for each normal Create run. The previously open project is restored before success is recorded. Failure stops full conversion rather than bypassing the check. The main conversion still creates its project inside Resolve, exports a native DRP to the selected results folder, then reopens and validates that export.

The version 1.4.2 source suite passed **134 of 134 tests**, including **16 compatibility tests** and all four generated-media integration tests. Version-gate tests accept **21.2.0.6**. That is automated version-policy coverage, not a native test of Resolve 21.2.0.6 on another machine.

Inside the installed **Resolve Studio 21.1.1.10**, the new automatic proof passed: two native multicam angles, two camera selections, a four-frame Cross Dissolve, save/export/reimport, source-path presence and restored startup state. It handled Resolve's empty unsaved Untitled startup project without opening a Save As dialog. A repeat run reused the matching completed proof without creating additional projects. These are native API checks; no new UI angle-switch exercise is claimed for this proof.

The earlier full-production export and UI editability proofs remain below with their actual versions and scope. Resolve 21.2.0.6 has not been exercised locally or remotely for this patch; that installation must pass its own runtime proof before full conversion. No second-machine certification, notarization or future-version guarantee is claimed.

The complete application bridge also passed a generated 1080p29.97 DF recording: two MOV replacements for MP4 references, two native multicam selections, one ten-frame Mix, independent stereo WAV audio, native DRP export and reimport validation. The main export was created successfully in the results folder. These are generated local sample files; the production media drive was not connected.

## Version 1.4.1: MOV relinking, audio mapping and optional Mix review

The main patch makes existing ATEM MP4 references usable with verified MOV replacements. It also puts **What would you like to create?** before folder selection, requires an initial output choice, and restores the last mode on later launches. Existing media and ATEM files are preserved. Mix reconstruction is a separate opt-in Resolve setting; strict conversion remains the default.

Completed read-only production checks:

- All **24 MOV camera files** were matched to the original references across eight angles and three file parts. Checks covered camera/part identity, rate, integer duration, source timecode and corroborated rollover timing. Original MP4s were unavailable, so encoded-content identity with those originals is not claimed.
- The full scan found **20 audio ISOs**, two recording sessions and **11 selectable primary sources**. Exact WAV sample lengths mapped to verified camera parts, including one WAV spanning consecutive video parts. Conflicting BWF clocks were reported rather than used to move the audio.
- All **1,396 event records** were parsed. The planned edit retained **980 video selections** plus the recording gap. Every positive-duration event interval retained its original selected camera and integer frame range.
- Optional Mix review identified **410 intervals**: **405** clear camera-to-camera intervals were planned as linear dissolves, and **five** ambiguous intervals were marked. Four had the same camera at both endpoints; two intervals contained an internal camera change, with one belonging to both groups. Those internal selections, including short three- and nine-frame selections, were preserved.

Automated tests cover strict defaults, state-update edges, drop-frame minute/midnight boundaries, source switches inside Mixes, unresolved markers, incomplete transitions, protected source-file boundaries, saved opt-in policy, editor-version gates and fingerprints. An initial partial run skipped four optional generated-media integration tests; the completed 117-test run reported below included all four. The earlier version 1.4 packaged-runtime media checks remain historical evidence for that release.

Inside **Resolve Studio 21.1.1.10**, a small native multicam proof created a supported Cross Dissolve with `AddTransition`. A ten-frame left-aligned transition at cut 24 occupied frames **14–24**, while the adjacent multicam items kept their original edit and source offsets. The project was saved, exported and reopened; a camera angle was changed in the native UI and remained editable. This UI exercise establishes editability for the small proof; it is separate from the full-production API validation below.

The full production was then assembled, saved, exported and reimported in Resolve Studio 21.1.1.10. Supported API checks passed for **24 source camera files**, **20 imported WAVs**, **two native multicam sessions**, **980 editable video selections**, **405 Cross Dissolves with the exact planned frame intervals**, and **five unresolved review markers**. The selected camera ISO mix remained independent of video switching and continuous within each recording session. Media resolved after reopening.

No full-production visual review or UI angle-switch exercise was performed for every clip. The small proof supplies the UI editability evidence. No new Premiere import or native-project validation is claimed for this MOV fixture; Premiere still rejects active Mix recordings. Endpoint-only ATEM data cannot establish the original manual fader curve or an unlogged transition target. The five unresolved intervals and reconstructed linear Mixes still require comparison with the preserved program reference.

The standalone 1.4.1 app UI also completed the production folder scan: 24 MOVs, 20 WAVs, 980 video selections and 11 audio choices. The optional Mix checkbox was visible, unchecked by default, and supplied the reviewed policy only when enabled. Scan warnings describe the pre-application plan; the subsequent export/reimport validation records the 405 applied and verified transitions.

Version 1.4.1 source suite: **117 of 117 tests passed**, including four generated-media integration checks. Native standalone UI scan passed on the converted MOV recording. App signature verification passed. These checks describe the 1.4.1 implementation and do not establish later-version editor coverage.

## Version 1.4 shared-audio mode

Version 1.4 adds **Camera files with shared audio**. It maps a chosen sequence of captured WAVs to matching camera parts by exact sample lengths, ignores BWF timestamps for alignment, and writes new MOVs with stream-copied video, retained timecode and 24-bit PCM audio. It is independent of Resolve, Premiere and ATEM project parsing. It does not change a DRP, rebuild live cuts or relink existing editor media.

Completed automated media checks using the app's bundled Python, FFmpeg and ffprobe:

- **32 MOV outputs passed:** 24 from generated recordings with eight cameras, three video parts and two WAV parts per selected source; eight from a short real recording with one part per camera. Every output passed compressed-video MD5, decoded PCM MD5 against its exact source-WAV range, audio sample count, video frame count, and timecode-tag/timecode-track checks.
- All 32 outputs passed a repeat run without rewriting the media. Source SHA-256 hashes remained unchanged. A malformed DRP was ignored by this mode, and changed audio inputs were refused.
- **Eight additional MOV outputs passed**, one at each supported rate: 24000/1001, 24, 25, 30000/1001, 30, 50, 60000/1001 and 60 fps. Each used 120 video frames and passed exact sample-count, frame-count and timecode checks with the bundled runtime. These are small generated fixtures, not full production recordings at each rate.
- Dry runs wrote mapping reports and no MOVs. The unequal-split fixture verified that one WAV can cover multiple video parts without assuming equal filename suffixes.

The full automated source suite passed **62 of 62 tests**, including four generated-media integration tests enabled with `ATTACH_AUDIO_TEST_FFMPEG`. Those four tests use a full developer FFmpeg to generate fixtures; it is not an application runtime dependency. The separate 40-output checks above exercised the packaged runtime. The suite includes six bridge tests guarding the shared-audio path against project parsing/editor conversion, missing source selection and false completion after errors.

Inside the native ISO Assemble app, the complete folder scan → source selection → Check Audio Mapping → Create Camera Files workflow produced and verified all 24 generated camera MOVs. Restarting the app and resuming verified the existing outputs. Changing the selected audio invalidated the plan, and pressing Return after a source change could not start an export using the earlier plan. No Resolve or Premiere application was opened for these feature checks; no new multicam or editor import/reopen proof is claimed.

Runtime packaging checks passed for **81 Apple Silicon Mach-O binaries**, with no unbundled non-system dependencies. App signature verification passed. This remains an ad-hoc signed, non-notarized build; testing on a second Mac remains outstanding.

These results establish small-fixture and short-real-recording correctness. A full-length 24-file production export, a full-recording speed benchmark, subjective mix quality and subframe acoustic alignment were not tested. The historical editor proofs below are separate from this camera-file feature.

## Version 1.4 ATEM parser correction

A separate correction handles narrowly identified delayed source-file rollover metadata: it restores the descriptor to its declared effective time within the recording session while preserving actual switcher-event order. Regression comparisons for three existing project fixtures remained identical. A real late descriptor at record 1540 was restored correctly without reordering control events. Diagnostics retain the correction and unsupported events.

This fixes a parser rejection; it does not make variable/gapped recordings or active unsupported transitions convertible. For example, the separately audited recording contained 495 Mix events: 479 changed camera and 16 ended on the same camera without recording a target. Only transition endpoints were present; intermediate fader positions were absent. Strict project conversion rejects these transitions, and capture timing gaps remain blockers even with optional Mix review. That recording was not claimed as a completed multicam conversion. Shared-audio mode likewise rejects media timing that cannot meet its exact mapping requirements.

## Historical project-conversion checks

Tested with Resolve Studio 21.0.0.48 and Premiere 26.2.2 on Apple Silicon macOS, using ATEM 1080p 30000/1001 drop-frame recordings. The test production contained eight cameras, 24 camera files, 20 audio ISOs and three program recordings. All 1,335 original live switch positions and selections were verified. These private test recordings and projects are not included in this release.

Resolve: small native multicam proof changed angles through the editor UI and retained that change after saving/reopening. Full exported project was reimported and checked through the supported API. Full-production eight-tile viewer inspection remains outstanding; an active user render was preserved.

Premiere: native eight-angle proof retained a UI angle change after saving/reopening. Full native project reopened with media available. Read-only native-file validation checked all camera paths, selected angles, integer timing and independent stereo program audio. Premiere uses one multicam per physical MP4 segment. One extra same-angle technical splice was required in the test production; no original switch was lost.

Standalone UI: folder selection, ambiguous-project picker, audio selection, Resolve creation/export/reimport and Premiere generation/Save As/automatic validation were exercised in the earlier project-conversion build. Those checks are historical editor evidence; version 1.4's separate camera-file tests are listed above.

## Historical release checks

The unit suite covers partial state updates, repeated headers, truncated input, 29.97 drop-frame arithmetic, ambiguous input discovery, changed-media detection, audio coverage and Premiere rollover handling. Release 1.2 passed all 11 tests using its newly compiled bundled Python, including from the mounted read-only DMG with a clean environment. Bundled ffprobe successfully read a source recording. All 79 Mach-O binaries passed the dependency audit. The DMG checksum and deep/strict app signature verification passed. The generic interface opened successfully. Application source and documentation were checked for production-specific names; none remain.

## Known limits

- Ad-hoc signed, not notarized. Public distribution requires a Developer ID identity and Apple notarization. Gatekeeper acceptance on another Mac is not claimed.
- No second-machine certification, Intel build or Windows build.
- Premiere must be closed before creation and requires File → Save As to the displayed output path. Native-file validation follows automatically.
- Resolve Studio 21+ is eligible for cut-only conversion and Studio 21.1+ for Mix review, subject to the installed editor passing the runtime compatibility check. A passing version gate is not blanket validation of a later release. Unsupported switcher effects remain unsupported. See the version 1.3 rate matrix below for historical editor coverage.
- No full-show subjective audio/video review or subframe acoustic-latency measurement is claimed.


## Version 1.3 frame-rate expansion

Eight progressive 1080p rates are accepted: 23.976 (24000/1001; ATEM label 23.98 also accepted), 24, 25, 29.97 (30000/1001), 30, 50, 59.94 (60000/1001), and 60. Both DF and NDF are accepted at 29.97 and 59.94, making ten rate/timecode combinations. No frame interpolation or transcoding is performed.

A shared exact rational timing model now drives ATEM event parsing, camera timecodes/durations, audio sample alignment, FCPXML frame durations, Resolve settings, Premiere timebase/NTSC flags and native-project tick validation. DF skips two labels per ordinary minute at 29.97 and four at 59.94. Missing mode headers, unsupported modes, mixed timecode conventions, rate changes and mismatched media fail preflight.

Automated checks: 16 tests pass. Tests round-trip timecodes around all 1,440 daily minute boundaries in every rate/mode, verify midnight rollover, reject illegal DF labels, and check preflight, stereo audio alignment and both XML exporters across the matrix. Eight synthetic 1080p H.264 MP4 camera files per combination (80 total) passed real ffprobe preflight. The original production's Resolve and Premiere cut lists are unchanged. A real 1080p23.98 ATEM recording also passed the new bundled-runtime preflight: eight camera files, ten audio ISOs, 921 live cuts, all 11 primary-audio choices available, and no timing warnings. No new editor project was created from that private recording during this check.

Inside Resolve Studio 21.0.0.48: each of the ten combinations imported as two native eight-angle multicam cuts spanning a minute boundary. Exact cut positions, selected camera names, timeline rate and DF/NDF origin were checked through the documented API. Saving/reopening and exporting/reimporting a native DRP passed for every combination. These are synthetic-media tests, not full production recordings at each new rate. No new UI angle-switch exercise was performed per rate.

Premiere: XML rate fields, frame positions and audio construction are tested automatically across all ten combinations. Native Premiere import/save/reopen at the newly added rates remains unverified; the earlier 29.97 DF native-project proof remains the only real-editor Premiere rate validation. Expanded Premiere rates should be treated as preview support until those checks are completed.

Interlaced modes, other resolutions, variable/mixed-rate media and rates outside this matrix remain unsupported. All existing signing/distribution limitations still apply.
