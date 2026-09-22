# ISO Assemble

A standalone Apple Silicon Mac app that turns ATEM ISO recordings into editable multicam projects for DaVinci Resolve or Adobe Premiere Pro. Processing stays local; no Codex, account, cloud service, Homebrew or separate Python installation is required.

## Download

**[Download version 1.2](https://github.com/tomasrmorgan-ship-it/iso-assemble/releases/tag/v1.2.0)** — choose the DMG for the app, or the complete ZIP for the app, source and instructions.

This is an **ad-hoc signed, non-notarized prerelease**. Gatekeeper may block a downloaded copy. Apple Silicon only; the app requires macOS 13 or later, while your editor may require a newer system. No Intel or Windows build is provided.

## Use

1. Open the DMG and drag ISO Assemble to Applications.
2. Choose the ATEM recording root containing the text-based `.drp`, `Video ISO Files`, and captured audio folders.
3. Select the output folder, editor, project name and primary audio source.
4. Create the project. All captured audio ISOs are retained, while only the selected primary audio plays independently of camera switching.

**Resolve:** tested with Studio 21.0.0.48; enable local scripting. The app creates a separate project, exports it, reopens it and validates the conversion.

**Premiere:** tested with 26.2.2. Quit Premiere before creation. After import, use **File → Save As** to the exact output path shown by the app; native project verification then runs automatically.

See [full instructions](Documentation/Instructions.md) and [validation and limitations](Documentation/Validation.md).

## What it preserves

- Native editable multicam camera selections and original live switch timing.
- Verified source timecodes, recording boundaries and real gaps using integer drop-frame arithmetic.
- Independent stereo primary audio, with captured audio ISOs retained.
- Local media references without unnecessary copying or transcoding.

Validated scope is ATEM 1080p29.97 drop-frame. Unsupported active switcher effects stop conversion instead of silently disappearing. Premiere creates one multicam per physical camera-file segment and may add a same-angle splice at a rollover. Resolve can group contiguous segments within a recording-session multicam. These are native multicam edits, not flattened renders.

Camera labels come from the selected ATEM project. No private recordings or production projects are included in this repository or release package.

## Source and development

Application source and build scripts are in [Source](Source). Read [build instructions](Source/README.md). Run the standard-library test suite with:

```sh
python3 -B -m unittest discover -s Source/engine -v
```

The app bundles Python and a minimal FFmpeg/ffprobe runtime. Complete dependency source archives, licenses and rebuild recipe are included in the app under `Contents/Resources/Legal`.

## License

ISO Assemble application code is [MIT licensed](LICENSE). Python and FFmpeg retain their respective PSF and LGPL licenses. DaVinci Resolve and Adobe Premiere are separately installed third-party products; this project is not affiliated with Blackmagic Design or Adobe.

## Download layout

The complete ZIP contains Installer, Documentation, Source, Licenses and Checksums folders. All Markdown documents also have plain-text (.txt) copies. Start with README.txt or Documentation/Instructions.txt.
