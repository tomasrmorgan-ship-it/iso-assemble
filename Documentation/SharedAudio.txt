# Camera files with shared audio

This mode, introduced in ISO Assemble 1.4 and included in 1.4.4, puts one chosen ATEM audio source on every camera angle. It writes new MOV files containing each camera's unchanged compressed video, original timecode and the selected WAV audio as 24-bit PCM. It does not need Resolve, Premiere or a DRP. Version 1.4.4's Resolve timeline-audio change is separate from this camera-file mode; its mapping and output contract remain the same.

## Choose the folder and audio source

Under **What would you like to create?**, select **Camera files with shared audio** before choosing the recording root. On first launch the app requires an explicit output choice; later launches restore your last selected mode. The folder should contain:

```text
My Recording/
  Video ISO Files/
    My Recording CAM 1 01.mp4
    My Recording CAM 1 02.mp4
    ...
  Audio Source Files/
    My Recording CAM 8 01.wav
    My Recording CAM 8 02.wav
    ...
```

Camera files may use `.mp4` or `.mov`; having both extensions for the same camera and part is an ambiguity and is rejected. Choose **Camera files with shared audio**, then choose the captured WAV source that contains the sound you want. Only that source is attached to the new camera files. The app replaces their old embedded audio; it does not sum camera audio with the chosen mix or infer the correct source by listening.

Click **Check Audio Mapping** before **Create Camera Files**. Review the mapping report before starting a large export. The check reads source information and writes its plan and report under `Attached Audio` inside your chosen output folder; it does not create MOVs or edit the originals. Creation writes the MOVs and verification report into that same job folder. Human-readable reports are `Attach Audio Plan.txt` and `Attach Audio Verification.txt`, with JSON copies for exact values. Keep the hidden ownership and resume-state files as well.

## Why matching file suffixes is unsafe

ATEM video and WAV files can split at different points. For example, WAV `02` can cover both video `02` and video `03`. A BWF timestamp can also describe a later video rollover rather than the beginning of that WAV. This mode therefore ignores BWF timestamps for alignment, while retaining them in the report for reference.

The app orders each camera's video parts and the chosen source's WAV parts by part number. It computes the exact audio length of each video part using:

```text
samples = video frames × audio sample rate ÷ exact video frame rate
```

At 30000/1001 fps and 48 kHz, one frame represents exactly 1601.6 samples. The calculation uses fractions, not floating-point rounding. A part's resulting boundary must be a whole sample.

Consecutive video parts are assigned to the current WAV until their total length exactly equals the WAV's length. The next WAV starts at sample zero. The same verified mapping is used for each camera.

An example of unequal splitting, expressed as sample ranges with the end excluded:

| Video part | Chosen WAV part | Start sample | End sample |
|---|---|---:|---:|
| 01 | 01 | 0 | 56,056 |
| 02 | 02 | 0 | 498,642,144 |
| 03 | 02 | 498,642,144 | 517,573,056 |

These are illustrative mapping values, not a promise that another recording has the same lengths. Every recording is checked from its own files.

## Conditions that stop creation

The mapping must consume all selected WAVs and all video parts exactly, with no leftover audio, overrun or rounding. Every camera being processed must have the same part set and matching durations, frame rates and timecodes. A video part that would span two WAVs is rejected by this mode. Missing or duplicate part identifiers, unsupported media, mismatched cameras, nonuniform frame timing and ambiguous timecodes also stop creation.

Video timecodes must be continuous within each WAV group. A gap or overlap within that group is rejected. A real recording pause can remain between groups only after one WAV has been consumed exactly and the next WAV begins; the app does not remove that pause or stretch audio to bridge it.

Do not rename files just to force a rejected match, trim audio to fit, or assume that a successful length match proves independently recorded sources are synchronized. This feature relies on the common start/stop behavior of the ATEM ISO recording. It does not synchronize unrelated cameras, estimate sound delay, read slates, stretch audio or repair capture dropouts.

The accepted audio source is signed 24-bit PCM, 48 kHz stereo WAV, with 24-bit PCM output. Accepted video is progressive H.264 in MP4 or MOV; the original picture dimensions are preserved, and corresponding camera parts must have matching dimensions. Accepted video rates are 23.976 (24000/1001), 24, 25, 29.97 (30000/1001), 30, 50, 59.94 (60000/1001) and 60 fps. Every part still needs exact whole-sample boundaries. Variable-rate or held-frame timing is rejected even when the average rate looks correct; no frame interpolation or audio resampling is used to force a match.

## Creation and verification

The video is stream-copied, so there is no video re-encoding. MOV is used because it supports the 24-bit PCM audio required by this mode. Each output receives a proper timecode track from its source video. The media timescale must preserve the original video timing.

For every output, verification compares:

- The compressed video payload with the original camera file.
- The decoded 24-bit PCM audio with exactly the assigned source-WAV sample range.
- Video frame count and audio sample count with the planned lengths.
- Output timecode with the source camera timecode.

A failed check is reported as a failure; the output must not be treated as a verified deliverable. Keep the mapping and verification reports with the MOVs. See `Validation.md` for which implementation tests have actually been completed.

The source recordings are never overwritten. Keep the entire `Attached Audio` job folder so its saved plan can identify completed files. A resumed job can reuse unchanged completed outputs only after verification; a changed input, different audio choice, tampered output or unrecognized destination file is refused. Choose a fresh destination when the app reports a conflict. Do not replace an original MP4 with a renamed MOV.

## Disk space and time

Allow space for another copy of every camera's compressed video, plus shared audio on each output camera. Stereo 24-bit 48 kHz PCM uses **288,000 bytes per second**, about **3.11 GB per three hours per camera**, before container overhead. Eight cameras therefore add about 24.9 GB of PCM audio for three hours, in addition to their copied video.

Creation and full verification read large amounts of data. Drive speed and competing transfers dominate processing time even though video is not re-encoded. A small successful check does not predict a fixed completion time for a full recording. Keep both drives connected and ensure the destination has enough free space.

## Use the results

Import the new MOVs manually into Resolve, Premiere or another compatible editor. The ATEM DRP is untouched and still references its original media paths. If its MP4 references need MOV replacements, the separate project mode can relink a complete matching set after verifying camera/part identity, frame counts, rate and timing. Each relink is reported; unavailable original MP4 contents cannot be compared. No live cuts, multicam sequence or editor relinking is performed by shared-audio mode. Use the separate multicam-project mode when you need supported live switching reconstructed as an editable project.
