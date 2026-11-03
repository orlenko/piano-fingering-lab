# Fingering Studio desktop alpha

A native SwiftUI/AppKit macOS application around the existing offline research
pipeline. Drop a recording and a score, create a portable project, review the
composite video or annotated PDF, correct individual notes, update the media,
and export a new folder containing MP4, PDF, PNG and CSV.

The app makes no OpenAI or other hosted inference calls. The local Transkun
model, Apple Vision and the existing geometry/alignment code do the processing.
PDF support remains limited to the Doremi-family vector notation understood by
the experiment; scans and generic notation-software exports are not supported.
Automatic Likely/Uncertain tiers are heuristic estimates, not measured accuracy.

## Build and open

On the Apple Silicon development Mac, with Xcode command-line tools and the
project's isolated Python 3.11 environment:

```sh
uv sync --extra dev
.venv/bin/python tools/build_desktop.py
open '.local/dist/Fingering Studio.app'
```

This copies the existing standalone Python and locked packages, bundles weights,
compiles the Vision helper and native UI, preserves nested third-party notices,
records a runtime identity, and signs the result locally with an ad-hoc signature.
The recipient does not need Python, uv, Xcode, a terminal, or an API key. The app
bundle is approximately 1.2 GB before compression. Developer rebuilds may use
`--reuse-runtime`; create release candidates from a clean build instead.

The initial target is Apple Silicon with macOS 14 or later, based on dependency
wheel requirements and compiler deployment targets. Execution has been tested
on the development Mac only. Intel, the minimum macOS version on physical
hardware, and the musician's separate laptop have not been qualified.

This is an **internal evaluation alpha**, not a public distributable release.
It has no Developer ID signature or notarization. Public distribution also needs
component-specific redistribution review: the bundled ffmpeg binary reports
GPL v2 or later, and its corresponding-source obligations are not satisfied by
the Python wrapper's BSD license. The model/package licenses and nested Torch,
PDFium and other notices remain separate from this project's MIT license.
No public binary release is published by this change.

## Using a project

Choose a MOV/MP4 recording with piano audio and a supported PDF. This version
bounds inputs to 30 seconds, 1080p, 1,000 decoded video frames, 512 MB video,
31 seconds of at most stereo/96 kHz audio, and a 10 MB / 12-page score. PDF
geometry and primitive/note counts are also checked before model processing.
Unsupported inputs fail with an explanation. A clear hand-free view of the bass
end in this camera orientation is still required by the current calibration.

Choose where the `.fingeringproject` package will live. It contains copied
originals, immutable completed runs, and saved correction revisions. These are
private user data. Repository development uses `.local/`; project packages and
media are also ignored globally by this repository's git rules. Outside this
checkout, the user chooses the project location and is responsible for backups.

Select a note to seek playback or locate its score position. The inspector keeps
the automatic estimate visible alongside a manual correction. Unknown notes
start with unset correction controls. Save corrections explicitly, then choose
**Update video & score**. Export remains disabled while corrections are pending.
Reset removes only that note's manual override. **Analyze again** creates a fresh
automatic result after pending edits have been rendered; prior runs stay inside
the project. There is no previous-run browser in this first alpha.

Export creates a dated folder and refuses any existing destination name. It
copies only the completed, current outputs. It does not overwrite unrelated
files. A private job log can be revealed when an operation fails; logs are bounded
and stored under the user's Application Support/Fingering Studio/Jobs directory.
They can contain local paths and should not be posted publicly without review.

Stop terminates the owned worker group and waits for cleanup. A persistent job
lease blocks subsequent writes if the app crashes or cleanup is uncertain.
Reopening never sends signals to a PID remembered on disk. Once the previous
worker has exited, **Make recovery copy** copies inputs and the last completed
result into a new project, leaving the original intact. Incomplete run folders
and abandoned staging folders are not automatically erased.

## Validation

```sh
.venv/bin/python -m pytest
swiftc -swift-version 5 desktop/Sources/JobRunner.swift desktop/Tests/main.swift -o .local/supervisor-tests
.local/supervisor-tests .venv/bin/python
swiftc -swift-version 5 desktop/Sources/JobRunner.swift desktop/Sources/AppModel.swift desktop/Tests/ModelChecks.swift -o .local/model-tests
.local/model-tests
```

For an explicitly authorized local media check, build the native supervisor
harness, then supply a private input manifest. The driver relocates the app
outside the checkout and uses only bundled components and a minimal environment.
It exercises full analysis, correction provenance, cached rendering, export,
cancellation, and decoded frame counts; all detailed output stays in `.local/`.
The validation's one deliberate correction is a transaction test, not ground truth.

```sh
swiftc -swift-version 5 desktop/Sources/JobRunner.swift desktop/Tests/WorkerHarness.swift -o .local/worker-harness
.venv/bin/python tools/check_desktop.py --inputs .local/inputs.json
```

`tools/create_desktop_demo.py` creates wholly synthetic UI fixtures. They are not
supported-score/inference examples or accuracy evidence. Internal `--project`,
`--snapshot`, `--ui-state`, and `--ui-check` app arguments support own-window UI
checks without screen capture of other applications. Use only synthetic fixtures
for assistant image inspection. Snapshots exercise the controls and layout;
embedded layer-backed media views are checked separately through native APIs.
Run the four synthetic launch/render/normal-quit regressions with:

```sh
.venv/bin/python tools/create_desktop_demo.py
.venv/bin/python tools/check_desktop_ui.py
```

See [experiment-log.md](experiment-log.md) for the exact completed checks and
[review.md](review.md) for the independent source-review boundary.
