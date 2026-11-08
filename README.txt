# ISO Assemble 1.4.3

A standalone Apple Silicon Mac app for ATEM ISO recordings. Create editable multicam projects for DaVinci Resolve or Adobe Premiere Pro, or create camera MOV files carrying one shared audio source. Processing stays local; no Codex, account, cloud service, Homebrew or separate Python installation is required.

## Download and release status

Version **1.4.3 (build 8)** creates a fresh Resolve project on every Create run, organizes its media bins, and verifies that the finished cut timeline is active when the project is exported and reopened. The installer and source package are available from the [1.4.3 release page](https://github.com/tomasrmorgan-ship-it/iso-assemble/releases/tag/v1.4.3). See [validation and limitations](Documentation/Validation.md) for completed checks and editor coverage.

Start with **What would you like to create?** at the top of the app. On first launch, choose an output before selecting a recording folder; the app does not choose an editor for you. Later launches restore your last selected output mode.

The distributed app is an **ad-hoc signed, non-notarized prerelease**. Gatekeeper may block a downloaded copy. Apple Silicon only; the app requires macOS 13 or later, while an editing application may require a newer system. No Intel or Windows build is provided.

## Camera files with shared audio

Use this mode when your camera MP4 or MOV files have silent or unwanted embedded audio and a captured WAV contains the sound you want on every angle.

1. Select **Camera files with shared audio**, then choose the ATEM recording root containing `Video ISO Files` and `Audio Source Files`.
2. Choose a new output folder, then select the captured audio source.
3. Click **Check Audio Mapping**. Review which WAV and exact sample range will accompany each camera part.
4. Click **Create Camera Files**. The app writes MOV copies and reports into `Attached Audio` inside your output folder. It keeps the original compressed video and timecode and replaces embedded audio with the selected 24-bit PCM audio.
5. Import the new MOVs into your editor manually.

This mode needs no Resolve or Premiere installation and does not read or rewrite the ATEM edit. It does not create a multicam timeline, change an existing DRP, or relink its MP4 references. See [shared-audio mapping and safeguards](Documentation/SharedAudio.md).

## Editable multicam projects

1. Select Resolve or Premiere, then choose a recording root containing its text-based ATEM `.drp`, `Video ISO Files`, and captured audio folders.
2. Choose an output folder, project name and primary audio source.
3. Scan, then create the project. All captured audio ISOs are retained, while only the selected primary audio plays independently of camera switching.

**Resolve:** requires Studio 21 or later; optional Mix review requires 21.1 or later. Finish Resolve’s first-launch setup, select a local project library, and enable **Preferences → System → General → External scripting using → Local**. The app checks your installed Resolve with a small native multicam save/export/reimport test before attempting the full conversion. A version number alone is not proof of compatibility.

**Create New Resolve Project produces a fresh native DRP on every run.** Choose the recording root, scan it, and click Create. Each run writes to its own dated folder under `Projects` inside your selected results folder. If the requested Resolve project name already exists, the app chooses a unique name. It creates, exports, reopens and validates the new project without reusing earlier exports, saved conversion state or compatibility proofs. Existing projects and source recordings remain unchanged. The export's SHA-256 identifies the exact DRP that was checked. Choose this mode for an editable multicam DRP even when your source camera files are MOVs.

The finished `<project name>_Edit` timeline opens on the Edit page at its first actual camera cut. The media pool has `01 Edit`, `02 Multicam`, `03 Camera Originals` with a bin per camera, `04 Audio ISOs`, and `05 Program Reference`. Open the timeline in `01 Edit` to edit the live cuts; the clips in `02 Multicam` contain the underlying angles.

Optional macOS **Accessibility** permission lets ISO Assemble prepare Resolve's Multicam viewer and fit the timeline to its full length. Project creation and verification work without this permission; you can set those view options manually. Viewer preparation is separate from the saved DRP and does not alter the edit. See the [Resolve viewing instructions](Documentation/Instructions.md#open-the-finished-resolve-edit).

**Premiere:** previously tested with 26.2.2. Quit Premiere before creation. After import, use **File → Save As** to the exact output path shown by the app; native project verification then runs automatically.

If an ATEM project references missing MP4s, project mode can use matching MOV replacements after checking camera/part identity, frame rate, exact duration and timecode or corroborated rollover timing. The original DRP and media remain unchanged. The report records every relink; it does not claim byte identity with unavailable original MP4s.

Multicam conversion preserves native editable camera selections, live cut positions, verified timing and recording gaps. Captured WAVs can span several video parts when their exact sample lengths match verified camera timing. The selected mix stays independent of camera switching. Premiere creates one multicam per physical camera-file segment; Resolve can group contiguous segments within a recording-session multicam.

Optional Resolve **Mix review** is off by default and requires Studio 21.1 or later plus a successful native transition compatibility check. It reconstructs clear Mix intervals as linear Cross Dissolves and marks ambiguous intervals while retaining every logged camera change. Compare these with the program reference: endpoint records cannot recover a missing manual fader curve. Premiere Mix conversion, keys, fades and other unsupported effects still stop with an explanation.

Accepted ATEM project modes are progressive 1080p at 23.976, 24, 25, 29.97, 30, 50, 59.94 and 60 fps. 29.97 and 59.94 accept drop-frame or non-drop-frame timecode; other rates use non-drop-frame. See the validation report for editor-specific coverage. These project-mode capabilities do not imply that every recording is eligible for strict shared-audio mapping.

Read the [full instructions](Documentation/Instructions.md). Camera labels come from the selected ATEM project. No private recordings or production projects are included in the repository or release package.

## Source and development

Application source and build scripts are in [Source](Source). Read the [build instructions](Source/README.md). Run the standard-library test suite with:

```sh
python3 -B -m unittest discover -s Source/engine -v
```

The app bundles Python, FFmpeg and ffprobe. Complete dependency source archives, licenses and the runtime rebuild recipe are included in the app under `Contents/Resources/Legal`.

## License and package layout

ISO Assemble application code is [MIT licensed](LICENSE). Python and FFmpeg retain their respective PSF and LGPL licenses. DaVinci Resolve and Adobe Premiere are separately installed third-party products; this project is not affiliated with Blackmagic Design or Adobe.

The complete ZIP contains Installer, Documentation, Source, Licenses and Checksums folders. All Markdown documents also have plain-text `.txt` copies. Start with `README.txt` or `Documentation/Instructions.txt`.
