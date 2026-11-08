# ISO Assemble 1.4.2

A standalone Apple Silicon Mac app for ATEM ISO recordings. No Codex, account, separate Python installation, Homebrew or internet connection is needed. Python, FFmpeg and ffprobe are bundled. Connect the drive containing the original recordings before starting.

## Install and choose an output mode

1. Open the supplied Apple Silicon DMG and drag **ISO Assemble.app** to Applications.
2. Open the app and use **What would you like to create?** at the top. On first launch it shows **Choose an output** and folder selection remains disabled until you choose. Subsequent launches restore your last selected mode. Choose **DaVinci Resolve** for an editable multicam DRP, including when the camera inputs are MOVs. Choose **Camera files with shared audio** only when you want new MOV media files carrying your chosen audio.
3. Choose the ATEM recording root, such as `My Recording`, and a separate output folder.

**Camera files with shared audio** creates new MOV media files that you can import into any compatible editor. It needs `Video ISO Files` and `Audio Source Files`, but no DRP or installed editor.

**Resolve** and **Premiere** reconstruct supported live cuts as native editable multicam projects. They require the ATEM text-based `.drp`, supported recording media and the appropriate installed editor.

## Camera files with shared audio

1. Select **Camera files with shared audio**, then choose the recording root. Folder selection scans for camera files and captured WAV sources.
2. Choose the captured audio source whose WAV files should accompany every camera, for example `CAM 8` or `MIC 1`. Choose the source for its recorded content; a filename alone cannot establish which mix it contains.
3. Click **Check Audio Mapping**. This is a dry run that reads the recordings and produces a mapping report without writing camera MOVs.
4. Review the mapping and any error. WAV part numbers do not have to match video part numbers: one WAV may cover several consecutive video parts.
5. Click **Create Camera Files**. The MOVs and reports are written into `Attached Audio` inside your chosen output folder. Leave both drives connected until creation and verification finish.
6. Import the resulting MOVs into your editor manually. Each contains the original camera picture and timecode plus the chosen shared audio as 24-bit PCM.

The ATEM DRP remains unchanged and still references the original MP4s. This mode does not transfer the live cuts, rebuild a multicam timeline, or replace media in an existing project. It does not launch Resolve or Premiere.

Original camera audio is replaced in each new MOV, not mixed with the selected audio. The original MP4s and WAVs remain untouched. Exact sample ranges are derived from frame counts, verified frame rate and chosen WAV lengths; BWF timestamps are ignored for alignment. A video part may use only part of a WAV, and several video parts may share one WAV. If a boundary does not match exactly, the app stops instead of rounding, padding or guessing.

Camera inputs can be MP4 or MOV files containing progressive, constant-rate H.264. The chosen WAVs must be 24-bit PCM, 48 kHz stereo. The original picture dimensions are retained. Read [SharedAudio.md](SharedAudio.md), or its `.txt` copy, for mapping examples, verification, disk-space guidance and rejection cases.

## Resolve and Premiere multicam projects

1. Select Resolve or Premiere and choose an output folder and project name. Scanning checks timing and media before creating an editor project.
2. Explicitly choose the primary audio source. All captured audio ISOs are retained; only the selected source plays. Choose **ATEM stereo program mix** when the program recording contains the intended mix. Some ATEM recordings have silent program audio, so use the appropriate captured WAV source in that case.
3. Create the project. Original media and ATEM files remain unchanged.

**Resolve requirements:** use **DaVinci Resolve Studio 21 or later** for cut-based multicam projects, or **Studio 21.1 or later** for optional Mix review. Newer version numbers are eligible for a runtime compatibility check; they are not automatically declared supported. The app stops before full conversion if that check fails.

Before your first Resolve conversion:

1. Open Resolve Studio, finish its initial setup and select a local project library. Save any current work.
2. In **Resolve Preferences → System → General**, set **External scripting using** to **Local** and save the preferences. Restart Resolve if it asks you to.
3. Keep Resolve open, then return to ISO Assemble and click **Create Resolve Project**. If the app cannot connect, finish Resolve setup and check the Local setting before retrying. No editor is required for shared-audio camera files.

Before assembling the full edit, the app uses two existing camera clips with at least 12 overlapping frames for a small native multicam test. It checks both camera selections, then saves, exports and reimports the test project. Mix review also checks a native Cross Dissolve. An already saved open project is saved and restored around this check; the original ATEM project and media are unchanged. Resolve’s empty Untitled startup project is fine. If an unsaved project contains work, the app asks you to save it in Resolve before retrying.

The results folder contains a `Resolve Compatibility` subfolder with `Compatibility Report.json`, `state.json`, `Proof.fcpxml` and the small `Proof.drp`. The app keeps two owned test projects in the selected Resolve library and reuses a completed report only when the installed version, recording timing, source snapshot and proof code still match. Keep this folder for safe reruns. Conflicting project ownership stops the check.

After a successful check, the app creates your separate full Resolve project and exports **`<project name>.drp` into the results folder you selected**. It reimports that export into an owned verification project, checks the media, multicam selections, audio and any planned transitions, then returns to the edit. This produces a native Resolve DRP, not just XML interchange. Keep the reports with the export.

**Premiere:** Previously tested with **26.2.2**. Save your work and **quit Premiere before Create**. The app launches Premiere with the generated XML in a new project. After import, use **File → Save As** with the project name and results folder shown by ISO Assemble. The app verifies the native `.prproj` automatically. Open the `<project name>_Edit` sequence and enable Multi-Camera view. Manual Save As remains necessary; the app has no verified external Premiere save bridge.

Project conversion preserves eight named native multicam angles, supported live camera selections, integer timecode timing and recording gaps. Camera media and captured audio ISOs are referenced locally without copying or transcoding. The selected stereo primary audio stays independent of video switching. A separate program-recording reference timeline is retained where available.

For **Resolve only**, the optional **Rebuild mixes as linear dissolves; mark uncertain events for review** checkbox enables reviewed Mix reconstruction. It is off by default. Clear camera-to-camera intervals become linear Cross Dissolves over the recorded start/end frames, while the camera edit point stays at the recorded Mix end. Ambiguous intervals keep all logged source changes and receive review markers. Read `ATEM Review.txt` and compare the result with the preserved program reference: logged endpoints do not establish the original manual fader movement. This mode does not recover an unrecorded target camera.

Premiere export still refuses recordings with active Mix transitions. Keys, fades, unsupported transition types and unknown sources also stop conversion. These restrictions remain separate from the MOV relink fix.

Resolve groups contiguous file segments into each angle's recording-session multicam. **Premiere uses one native multicam per physical camera-file segment**, because its legacy XML importer drops additional files placed inside one angle. When a cut spans a physical file boundary, the app adds a splice with the same angle selected on both sides. No real gap is collapsed.

## Project timing, reruns and errors

Supported ATEM project modes are progressive 1080p at 23.976, 24, 25, 29.97, 30, 50, 59.94 and 60 fps. Rates are detected from the header and checked against every camera file. 29.97 and 59.94 support DF or NDF; other rates require NDF. Mixed rates, changes mid-project, missing mode headers and unsupported media timing are rejected. This does not convert media to a different frame rate.

Resolve import/save/reopen checks passed historically for every supported rate/mode. Premiere has automated XML/timing tests across those rates; native-editor validation remains limited to the earlier 29.97 DF project. See the validation report for details. Interlaced modes, other resolutions and ambiguous or missing timing remain unsupported by project conversion.

A narrowly identified delayed source-file rollover record can now be restored to its declared effective time without changing switcher-event order. The scan report identifies that correction. This parser fix does not repair dropped frames, missing media, audio mismatches or ambiguous events. Optional Mix review is a separate, explicit setting.

For project reruns, use the same output folder and name to verify/reuse the same conversion. Changed media, audio selection, conflicting projects or manifests require a new output folder/name. Edited projects are not reset; validation reports differences. Keep generated reports with the project, and save a copy before creative editing if you want the original conversion to remain verifiable.

For camera-file exports, keep the `Attached Audio` job folder, including its mapping, job state and verification reports. An interrupted job can reuse completed outputs only when they match the saved job and pass verification. Changed sources, a different audio choice or conflicting files are refused; choose a fresh destination when prompted. Existing source or unrecognized destination files are never overwritten.

Automatic project filename-prefix repair is applied only when every referenced camera file resolves under the root. WAV names do not need renaming. If a root contains multiple ATEM projects, project mode presents a picker. Shared-audio mode discovers the camera and WAV files directly and does not use that repair to change source names.

When referenced MP4s are missing, project mode can relink to a complete matching MOV set after verifying camera/part identity, rate, exact frame counts and timing. Source timecode must agree, or rollover timing must be corroborated by contiguous camera parts and the program recording. A filename alone is insufficient. Each relink is recorded in the report; the ATEM DRP and MOVs are not rewritten. If the original MP4s are unavailable, their encoded contents cannot be compared with the MOVs. Incomplete, ambiguous or mismatched replacements stop with a readable error.

For captured WAVs, exact sample lengths are matched to the verified camera parts. One WAV may cover several consecutive parts; suffixes need not match. Conflicting BWF clock metadata is reported and is not used to shift an exact-length match. Unmatched, partial or ambiguous coverage is refused. Choose the intended mix by its recorded content; metadata cannot identify what is audible.

## Sharing this build

The app supports **Apple Silicon** Macs with macOS 13 or later; Resolve/Premiere may require newer macOS. The package is **ad-hoc signed, not Apple notarized**. Gatekeeper may block a downloaded copy. Developer ID signing and notarization require the publisher's Apple Developer identity. Do not disable system-wide security protections. The source includes `sign-and-notarize.sh` and `package-dmg.sh` for distribution preparation. Intel and Windows builds are not included. Testing on a second, clean Mac remains outstanding.

Editor project files do not include recordings. Share the recording folder too, and relink it if the path changes. Camera-file MOVs contain their selected picture and audio, but no multicam edit. The application package contains no private recordings or credentials. Runtime licenses, complete sources and the rebuild recipe are under `Contents/Resources/Legal`.

## Advanced local CLI

The source is supplied separately. For project mode, `engine/app_engine.py scan --root ROOT --output OUTPUT` performs preflight; `create --output OUTPUT --name NAME --audio program` builds Resolve; `premiere` with the same flags writes Premiere interchange; `verify-premiere --output OUTPUT --name NAME` checks a saved native project. Invoke these with the bundled Python and put bundled `runtime/ffprobe/bin` on PATH.

`engine/app_engine.py scan` and `engine/convert.py` accept `--mix-policy linear-review` for explicit Resolve Mix review; the default is `strict`. The scan saves this choice for creation. `engine/convert.py` also supports `--input`, `--media-root`, `--output-dir`, `--name`, `--camera-names` (JSON mapping), `--repair-prefix OLD NEW`, and `--dry-run`. Its FCPXML contains native multicam cuts; the accompanying transition plan still needs Resolve application and validation. For shared-audio mode, run `audio-scan --root ROOT --output OUT` to list sources, `audio-plan --root ROOT --audio 'CAM 8' --output OUT` to check the exact mapping, and `audio-build --output OUT` to create and verify MOVs. These commands also run through `engine/app_engine.py` and need bundled `runtime/ffmpeg/bin` on PATH. They use `OUT/Attached Audio` and do not require a project name or editor. All tools run locally without Codex.
