# ISO Assemble 1.4.5

Version 1.4.5, build 10. A standalone Apple Silicon Mac app for ATEM ISO recordings. No Codex, account, separate Python installation, Homebrew or internet connection is needed. Python, FFmpeg and ffprobe are bundled. Connect the drive containing the original recordings before starting.

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
3. Keep Resolve open, then return to ISO Assemble and click **Create New Resolve Project**. If the app cannot connect, finish Resolve setup and check the Local setting before retrying. No editor is required for shared-audio camera files.

Before assembling the full edit, the app uses two existing camera clips with at least 12 overlapping frames for a small native multicam test. It checks both camera selections, then saves, exports and reimports the test project. Mix review also checks a native Cross Dissolve. An already saved open project is saved and restored around this check; the original ATEM project and media are unchanged. Resolve’s empty Untitled startup project is fine. If an unsaved project contains work, the app asks you to save it in Resolve before retrying.

Each **Create New Resolve Project** run starts fresh. The app makes a new dated folder with a random suffix under `Projects` inside your selected results folder. It chooses an available Resolve project name if the requested name already exists. Earlier exports, `resolve-state.json` files and compatibility reports are not reused, even when they remain from an older app version or their associated Resolve projects have been deleted.

The new run folder contains its own `Resolve Compatibility` subfolder with `Compatibility Report.json`, `state.json`, `Proof.fcpxml` and the small `Proof.drp`. The app runs a fresh compatibility proof for that conversion. After successful export verification it removes this run's temporary compatibility and reimport test projects when their ownership identities match, then returns to your finished edit. A cleanup problem is reported and the affected project is preserved. The proof files and reports remain in the run folder; keep them with the new export.

After a successful check, the app creates your separate full Resolve project and exports **`<project name>.drp` into that new run folder**. Use the result path shown by the app to find this run's export. It reimports that export into an owned verification project and checks the media, multicam selections, audio, planned transitions, organized bins and active edit timeline. The check is tied to the exact export's SHA-256, recorded in `validation.json`; a different or changed DRP cannot reuse an earlier verification result. The app then returns to your full project and its edit timeline. This produces a native Resolve DRP, not just XML interchange. Keep the reports with the export.

### Verify your chosen audio

Version 1.4.4 imports the chosen audio with the camera edit, onto an independent stereo **A1** track. Choose the source containing your intended mix before Create. For example, selecting `CAM 8` places the captured CAM 8 WAVs beneath the live video cuts; the other captured sources remain available in **04 Audio ISOs**. A single long WAV can continue through several camera-file parts without restarting at each video rollover. Audio is continuous within each recording session; actual recording gaps remain silent.

Before exporting, the app verifies that A1 contains exactly the selected files at the planned timeline positions and offsets within those files. It repeats these checks after reopening the exported DRP. Enabled state and stereo channel assignments are also checked when exposed by the installed Resolve; `validation.json` records which checks ran. Empty A1, missing coverage, an incorrect mix or an invalid channel assignment stops creation with an error. A successful media-pool import alone is insufficient.

After opening the finished edit, play a representative section to confirm that the chosen source contains the sound you intended. Structural checks cannot establish the recorded signal's loudness or your speaker/headphone routing. Use video-only multicam switching when changing camera angles so the independent mix stays intact.

If an older result has no audio, keep that project and create a fresh conversion with the current version after selecting the intended source. Each Create uses a new project and run folder; it does not patch your older creative edit. Keep the new `conversion.json` and `validation.json` reports with the DRP if an error needs investigation.

### Open the finished Resolve edit

The app selects **`<project name>_Edit`**, opens Resolve's **Edit** page and places the playhead at the first actual multicam cut. This avoids opening on black or a long recording gap. Its checks verify the selected timeline's identity, rather than accepting another timeline with a similar name.

The media pool is organized into:

- **01 Edit:** the finished timeline containing the live camera cuts.
- **02 Multicam:** native multicam clips containing the synchronized angles.
- **03 Camera Originals:** original camera clips, separated into **Camera 1**, **Camera 2**, and the other camera bins.
- **04 Audio ISOs:** captured audio sources, including those not chosen as the primary mix.
- **05 Program Reference:** original program recordings and the preserved reference timeline.

To edit the live camera choices, open the timeline in **01 Edit**. Opening a clip in **02 Multicam** shows its underlying angles rather than the completed cut sequence. Bin organization does not change source files or move unrelated media added to the project.

Version 1.4.5 first fits the **entire edit** into the timeline using **Full Extent Zoom**, the view achieved manually with **Shift-Z**. This zooms the view only: it does not combine cuts, move clips, shorten the timeline or remove recording gaps. A long gap can make the recorded sections look small because the whole timeline is visible.

Automatic view setup needs macOS **Accessibility** permission for **ISO Assemble**. Click **Enable Automatic View**, then allow ISO Assemble under **System Settings → Privacy & Security → Accessibility**. This is a one-time permission step; when you return to the app after granting it, the app retries the view setup. Future successful Create runs attempt the same setup automatically. Creation does not prompt for permission automatically, and project creation/export verification work without it. Without permission, use the manual steps below.

After creation, **Show Entire Edit** retries for the project the app just created. If the timeline is already fitted, repeating the action leaves it fitted. After the fit, the app tries to prepare the **Multicam** viewer, turn off **Inspector** so the source viewer has room, show Media Pool, and select video-only switching. A successful timeline fit is preserved even if one of these optional controls is unavailable. `Viewer Setup.json` records the separate viewing result.

The exported edit remains native and its angles remain editable if permission is unavailable or Resolve's controls differ. Viewer state is not guaranteed to travel with a DRP to another Mac. The app's button works with its most recently created project; it is not an arbitrary-project picker. To use the updated automatic flow, replace the app and follow the normal fresh Create workflow. An older finished edit can be fitted manually without recreating it.

Manual viewing steps, checked in Resolve Studio 21.1:

1. Open the **Edit** page. Show **Media Pool** if needed, then open **01 Edit → `<project name>_Edit`**.
2. Focus the timeline and press **Shift-Z**, or click **Full Extent Zoom** above it, to show the entire edit. If it is already fitted, leave it as it is; the shortcut toggles the view.
3. Turn off **Inspector** if it is open. On a narrow window, its width can hide the source viewer.
4. Click **Multicam** beneath the timeline viewer to show the camera-angle grid beside the program picture. Use video-only switching to keep the independent mix intact.

These controls change the view, not the selected camera angles or audio.

### Premiere creation

**Premiere:** Previously tested with **26.2.2**. Save your work and **quit Premiere before Create**. The app launches Premiere with the generated XML in a new project. After import, use **File → Save As** with the project name and results folder shown by ISO Assemble. The app verifies the native `.prproj` automatically. Open the `<project name>_Edit` sequence and enable Multi-Camera view. Manual Save As remains necessary; the app has no verified external Premiere save bridge.

### Multicam timing and supported events

Project conversion preserves eight named native multicam angles, supported live camera selections, integer timecode timing and recording gaps. Camera media and captured audio ISOs are referenced locally without copying or transcoding. The selected stereo primary audio stays independent of video switching. A separate program-recording reference timeline is retained where available.

For **Resolve only**, the optional **Rebuild mixes as linear dissolves; mark uncertain events for review** checkbox enables reviewed Mix reconstruction. It is off by default. Clear camera-to-camera intervals become linear Cross Dissolves over the recorded start/end frames, while the camera edit point stays at the recorded Mix end. Ambiguous intervals keep all logged source changes and receive review markers. Read `ATEM Review.txt` and compare the result with the preserved program reference: logged endpoints do not establish the original manual fader movement. This mode does not recover an unrecorded target camera.

Premiere export still refuses recordings with active Mix transitions. Keys, fades, unsupported transition types and unknown sources also stop conversion. These restrictions remain separate from the MOV relink fix.

Resolve groups contiguous file segments into each angle's recording-session multicam. **Premiere uses one native multicam per physical camera-file segment**, because its legacy XML importer drops additional files placed inside one angle. When a cut spans a physical file boundary, the app adds a splice with the same angle selected on both sides. No real gap is collapsed.

## Project timing, reruns and errors

Supported ATEM project modes are progressive 1080p at 23.976, 24, 25, 29.97, 30, 50, 59.94 and 60 fps. Rates are detected from the header and checked against every camera file. 29.97 and 59.94 support DF or NDF; other rates require NDF. Mixed rates, changes mid-project, missing mode headers and unsupported media timing are rejected. This does not convert media to a different frame rate.

Resolve import/save/reopen checks passed historically for every supported rate/mode. Premiere has automated XML/timing tests across those rates; native-editor validation remains limited to the earlier 29.97 DF project. See the validation report for details. Interlaced modes, other resolutions and ambiguous or missing timing remain unsupported by project conversion.

A narrowly identified delayed source-file rollover record can now be restored to its declared effective time without changing switcher-event order. The scan report identifies that correction. This parser fix does not repair dropped frames, missing media, audio mismatches or ambiguous events. Optional Mix review is a separate, explicit setting.

To make another Resolve conversion, choose the recording root again or rescan it, select the intended audio, and click **Create New Resolve Project**. Each Create makes a new independent project and a new `Projects` run folder. You do not need to delete earlier exports or clear old conversion state first. Older conversions and creative edits are preserved. A recording changed since scanning must be rescanned before creation; the app does not approve changed media using the old scan.

Keep each run's reports with its DRP. The fresh-project behavior applies to Resolve conversion; the separate camera-file export mode retains the resumable behavior described below.

For camera-file exports, keep the `Attached Audio` job folder, including its mapping, job state and verification reports. An interrupted job can reuse completed outputs only when they match the saved job and pass verification. Changed sources, a different audio choice or conflicting files are refused; choose a fresh destination when prompted. Existing source or unrecognized destination files are never overwritten.

Automatic project filename-prefix repair is applied only when every referenced camera file resolves under the root. WAV names do not need renaming. If a root contains multiple ATEM projects, project mode presents a picker. Shared-audio mode discovers the camera and WAV files directly and does not use that repair to change source names.

When referenced MP4s are missing, project mode can relink to a complete matching MOV set after verifying camera/part identity, rate, exact frame counts and timing. Source timecode must agree, or rollover timing must be corroborated by contiguous camera parts and the program recording. A filename alone is insufficient. Each relink is recorded in the report; the ATEM DRP and MOVs are not rewritten. If the original MP4s are unavailable, their encoded contents cannot be compared with the MOVs. Incomplete, ambiguous or mismatched replacements stop with a readable error.

For captured WAVs, exact sample lengths are matched to the verified camera parts. One WAV may cover several consecutive parts; suffixes need not match. Conflicting BWF clock metadata is reported and is not used to shift an exact-length match. Unmatched, partial or ambiguous coverage is refused. Choose the intended mix by its recorded content; metadata cannot identify what is audible.

Resolve's source-media clock is separate from the WAV's placement in the edit. The app accounts for a WAV's BWF clock when referencing that file inside Resolve, while the verified sample-length mapping determines when it plays. A timestamp that points to a later camera rollover must not delay the WAV or restart it there. The original WAV metadata is not rewritten.

## Sharing this build

The app supports **Apple Silicon** Macs with macOS 13 or later; Resolve/Premiere may require newer macOS. The package is **ad-hoc signed, not Apple notarized**. Gatekeeper may block a downloaded copy. Developer ID signing and notarization require the publisher's Apple Developer identity. Do not disable system-wide security protections. The source includes `sign-and-notarize.sh` and `package-dmg.sh` for distribution preparation. Intel and Windows builds are not included. Testing on a second, clean Mac remains outstanding.

Editor project files do not include recordings. Share the recording folder too, and relink it if the path changes. Camera-file MOVs contain their selected picture and audio, but no multicam edit. The application package contains no private recordings or credentials. Runtime licenses, complete sources and the rebuild recipe are under `Contents/Resources/Legal`.

## Advanced local CLI

The source is supplied separately. For project mode, `engine/app_engine.py scan --root ROOT --output OUTPUT` performs preflight; `create --output OUTPUT --name NAME --audio program` builds Resolve; `premiere` with the same flags writes Premiere interchange; `verify-premiere --output OUTPUT --name NAME` checks a saved native project. Invoke these with the bundled Python and put bundled `runtime/ffprobe/bin` on PATH.

`engine/app_engine.py scan` and `engine/convert.py` accept `--mix-policy linear-review` for explicit Resolve Mix review; the default is `strict`. The scan saves this choice for creation. `engine/convert.py` also supports `--input`, `--media-root`, `--output-dir`, `--name`, `--camera-names` (JSON mapping), `--repair-prefix OLD NEW`, and `--dry-run`. Its FCPXML contains native multicam cuts; the accompanying transition plan still needs Resolve application and validation. For shared-audio mode, run `audio-scan --root ROOT --output OUT` to list sources, `audio-plan --root ROOT --audio 'CAM 8' --output OUT` to check the exact mapping, and `audio-build --output OUT` to create and verify MOVs. These commands also run through `engine/app_engine.py` and need bundled `runtime/ffmpeg/bin` on PATH. They use `OUT/Attached Audio` and do not require a project name or editor. All tools run locally without Codex.
