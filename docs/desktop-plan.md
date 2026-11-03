# Fingering Studio desktop implementation

Status: design for independent hostile review before implementation, 2026-11-03.
The direct product request authorizes planning and implementing a usable Mac app
from the supplied synthetic design. Existing privacy/review rules still apply.

## Goal and acceptance

A musician opens a local `.app`, drops a recording and PDF (or uses file choosers),
creates a portable project, runs the existing local analysis, reviews the actual
video/PDF and event table, optionally records corrections, and exports real files.
Opening/retrying/reopening/cancelling must preserve originals and the last usable
result. No terminal, Python installation, API key, account or hosted inference is
required on the recipient's machine. App source and sanitized records are public;
builds, projects, private inputs/results and diagnostics remain ignored.

Acceptance is a functioning native app plus self-contained local Apple Silicon
build, tested after relocation with sanitized environment and no checkout imports,
with native UI inspection using synthetic fixtures and local backend validation.
Do not call an ad-hoc signed internal build notarized or publicly release-cleared.
Developer ID signing/notarization and actual second-machine/minimum-OS qualification
remain distinct distribution gates if the necessary identity/hardware is unavailable.

## Designer claims to change

- The supplied HTML is a synthetic interaction proposal, not application code or
  evidence of preflight, cancellation, packaging, compatibility or accessibility.
- Modern notation-software export is not a reliable remedy for an unsupported PDF.
  Detect the actual Doremi noteheads/staves and fail with honest compatibility text.
- High confidence means heuristic support, not proof of pressing a key. Use
  “Likely”, “Uncertain”, “Unknown”, and “Your correction”; describe evidence carefully.
  A missing transcription match is not proof the pianist did not play a note.
- Drop the invented 90 MB download. Existing dependencies occupy about 1.3 GB and
  weights about 56 MB. Bundle a verified local runtime/model and report actual size.
- Hand tracking precedes keyboard calibration in the real pipeline. Show actual
  stage transitions and elapsed time; no fabricated percentage/remaining-time clock.
- Playing the already-rendered composite avoids inventing a second live video
  compositor. A separate annotated-PDF tab and linked note table provide inspection.
- Corrections are optional and saved separately. They do not magically change a
  previously encoded MP4: show dirty state until an explicit update/export succeeds.
- Closing/stopping requires actual owned worker cleanup, not just changing screens.
  No labels, cached results or musician evaluation are prerequisites to first output.

## Architecture and user flow

Use native SwiftUI/AppKit with AVKit and PDFKit, built using the existing Swift SDK.
Three primary views match the design: input drop/chooser, real processing, results.
Native sheets cover project destination/name, stop confirmation and export choices.
Recents and Finder document opening are local. Inputs must remain usable with only
keyboard/file choosers; labels and status text carry meaning independent of color.

The Swift shell spawns the bundled Python worker directly by argv, never a shell.
The worker exposes inspect, create/open project, analyze, set/remove correction,
render-update and export operations; JSON-lines protocol v1 has bounded event sizes.
Pipeline stdout/debug output goes to private job logs; stdout carries structured
stage/result/error events. An additive pipeline progress callback reflects real
stages, including render time. No UI command invokes uv, pip, a compiler or a server.

Preflight decodes the recording to establish actual dimensions/frame count/timing,
checks audio is decodable, and parses the selected score with the actual parser.
It does not claim visible hands or cheap calibration from invented heuristics.
For this first release use conservative explicit caps: 30 seconds, 1080p and
1,000 decoded frames; reject larger input before inference with an actionable
experimental-limit message. These protect the current all-frame geometry stage;
they are not a validated performance promise for every supported Mac. Minimum
target is Apple Silicon/macOS 14 based on the installed wheel tags, subject to
native API/binary deployment-target verification. Intel is not advertised.
The camera guidance must state the supported behind-music-desk orientation and
visible bass-end reference requirement, rather than promise arbitrary camera views.

Projects are versioned `.fingeringproject` directory bundles. The manifest contains
relative paths, a UUID/name, state and current successful run ID. Inputs are copied
into fixed owned names. Each analysis/render attempt uses a new run directory;
publish its current-run pointer atomically only after all outputs pass validation.
Failed/cancelled attempts and logs stay private; the previous successful run remains
available. A full reanalysis starts a new correction set and preserves older history.

Each successful run is immutable, including its captured manual-overrides snapshot.
Pending edits live in the atomically written project manifest, scoped to the current
run, with a monotonically increasing revision. Render captures that revision and
snapshot; publish only if the revision still matches. All mutations acquire the
same nonblocking on-disk flock, including corrections, analysis/render, finalization
and export snapshots. Stale UI writes must supply expected run/revision and fail.
Each run retains automatic predictions plus its captured manual overrides sidecar.
The note inspector requires an explicit valid hand/finger pair before saving;
changing hand alone never invents a finger. Remove Correction restores the automatic
value. Applying corrections updates the review table and dirty indicator immediately;
Update Video or Export rebuilds outputs from compatible cached stages into a new
run, with no transcription/model inference. Preserve automatic fields and original
abstention evidence. New-engine cache mismatch fails closed and offers reanalysis,
leaving prior results intact. Cache identity must include packaged dependency/helper
identity as well as source/input/stage-output hashes.

Export copies only selected completed outputs to a newly named folder in a selected
parent. Stage the whole folder, then use an exclusive atomic rename; refuse
collisions and never replace an arbitrary existing directory. Dirty
projects update rendering first; cancellation/failure cannot export stale results
as current. Refuse colliding names and publish the complete new folder; no input
or unrelated destination files are removed. Project reopening handles failed/stopped
runs and missing/corrupt assets without reprocessing or silent source relinking.

## Boundaries and failure handling

Project/manifests are untrusted data: validate version/types/run UUIDs and fixed
relative paths, reject traversal and symlink component escapes before reads/writes,
bound JSON/event/file sizes, and never import/execute project files. This is normal
stable-owner path validation, not adversarial OS containment. Workers have a minimal
environment, isolated Python startup, package-only imports and project-owned cache/
temp locations. Suppress external plugin/config autoload; no analytics/network code.
No private diagnostic pixels or score text is sent to reviewers or hosted tools.
UI screenshots/reviewer contexts use synthetic fixtures only.

Native worker ownership uses posix_spawn with a new process group, pipe capture,
native waitid/WNOWAIT observation, then one explicit waitpid. Retain the unreaped
leader identity while sending TERM/KILL only to that owned group. After reaping,
perform only non-signaling group-absence observation. No PID reuse race, global
process matching, shell supervisor or unrelated signal. Cancellation has a grace
period and leaves incomplete state if cleanup cannot be established. GUI state
changes only after cleanup; child helpers inherit the owned group. Refuse job launch
if the native capability is unavailable; do not reuse Python 3.11's missing wrapper.
Late worker messages are bound to the active job generation and cannot overwrite a
new selection/project. A project permits only one job/correction writer at a time.

## Packaging

Use the existing relocatable python-build-standalone CPython 3.11 distribution and
the existing uv.lock-installed dependencies, rather than add a new freezer. Copy
only code/runtime/package data into an ignored app build; remove editable `.pth`,
bytecode/caches, developer direct URLs, tests and local path-bearing project metadata.
Install the first-party package as ordinary bundled source and verify its origin.
Keep bundled dependency/version identity and third-party licenses/notices; the repo
MIT license does not replace those terms or grant rights to music/source recordings.
Weights remain unmodified with package provenance/notices. No third-party binary,
weights, private project or designer runtime is committed or publicly released here.

Compile the Apple Vision helper at build time and pass its explicit bundled path
to the pipeline. The recipient must not need Xcode/Swift or a global ffmpeg; PyAV
and the packaged ffmpeg path supply codecs/muxing. Bundle native min-OS checks,
app/document Info.plist, icon/metadata, ad-hoc signing and a shareable local archive.
Developer ID/notarization is optional only for the internal test artifact and is
an explicit unresolved gate for smooth general distribution, never bypassed by
disabling Gatekeeper. Verify an app moved outside the checkout with source/Python
path injection absent; no external interpreter/source absolute paths may be required.

## Execution and validation order

1. Obtain hostile design critique; disposition blockers here before nontrivial code.
2. Implement isolated project/worker protocol, project validation, atomic run/export
   lifecycle, honest preflight/progress, cache-compatible corrections and helper path.
3. Implement native job ownership and UI for real states/results/reopen/corrections.
4. Build a self-contained app and package, verify native targets and relocated health.
5. Meaningful synthetic tests cover malformed/traversing projects, transactional
   retries/export, automatic/manual preservation, dirty rendering, real IPC failure,
   cancellation/cleanup, and recipient-style runtime/helper origins. Existing pipeline
   tests remain required, with private-input scans performed locally only when
   authorized; do not upload their contents or claim a skipped check passed.
6. Exercise actual analysis locally using authorized source materials if needed,
   with fresh project/results under `.local/`; inspect media using local mechanical
   checks and avoid hosted private-image inspection. Use synthetic fixtures for
   actual native-window UI snapshots and open/reopen/cancel/export smoke tests.
7. Separate finished-code review covers execution, measurement validity and privacy;
   fix blockers, re-review exact final source, inspect staged public bytes, run
   appropriate checks, then commit/push reviewed code and sanitized decisions on main.
   Preserve unfinished work on a reviewed branch if a genuine distribution gate
   blocks full completion; report an actual usable artifact and its precise limits.

References: [runtime portability](https://gregoryszorc.com/docs/python-build-standalone/main/distributions.html),
[Transkun upstream](https://github.com/Yujia-Yan/Transkun), and Apple SDK availability
annotations/wheel tags inspected locally. No second-machine or musician accuracy
claim follows from local build success.

## Independent review

The separate hostile reviewer found eight pre-code blockers. Dispositions:

1. Bound source files (512 MB video, 10 MB PDF), decoded audio (31 seconds, at
   most stereo/96 kHz), PDF pages (12), dimensions (1,000 by 1,500 points), and
   per-page primitives (30,000) / parsed notes (2,000). Check video header dimensions
   before decoding, then actual frames/timestamps/audio/PDF structures. Preflight
   itself is cancellable and has a finite wall-time limit; native decoder libraries
   are trusted dependencies, not an OS hostile-file sandbox.
2. Use immutable run snapshots and explicit pending edit revisions as described
   above. Recheck captured revision under the project lock before publication.
3. One on-disk flock governs all mutations across app/worker processes. Reads use
   atomic manifests and immutable successful runs. Reject untrusted lock symlinks.
4. Export a new directory by exclusive atomic rename; no multi-file replacement.
5. Native job tests must cover cancel during spawn, exec failure, saturated pipes,
   ignored TERM, child-held stdout and normal-exit descendants, generation fencing
   and cleanup uncertainty. Exactly one native reaper owns each group leader.
   A manifest job lease remains until the app confirms owned-group cleanup and a
   short finalization operation clears the matching job UUID under lock. If the
   app crashes or cleanup is uncertain, another writer cannot silently clear it.
   Offer a recovery copy of immutable inputs/last result into a new project after
   lock availability; never signal a remembered PID or erase the old project.
6. Bound/validate JSON, project versions, UUIDs, records, finite timings/coordinates
   and symlink components on every operation and reopen. Decode IPC/files off the
   UI thread. No arbitrary paths/configuration/model imports from project data.
7. Change visible PDF/video confidence legends to Likely/Uncertain too, preserving
   raw high/low automatic tiers. Include heuristic/unknown/manual disclosure.
8. Packaging identity includes source/dependencies/helper/model, independent of
   location. Keep nested notices (including Torch/PDFium); inspect actual bundled
   ffmpeg license instead of inferring it from imageio-ffmpeg's Python license.
   Local alpha generation is separate from public redistribution clearance.

These accepted amendments resolve the design blockers; the reviewer will verify
their concrete implementation and meaningful tests before final push. No private
artifact or target code was accessed/executed by the design reviewer.


## Implementation disposition

Implemented as the native internal alpha documented in [desktop.md](desktop.md).
The separate finished-code reviewer approved source execution, measurement and
privacy boundaries after fixes; see [review.md](review.md). The full relocated
analysis/correction/render/export/stop workflow passed on the authorized sample,
with the original musician deliverables unchanged. Four native synthetic UI
launches passed after the documented AVKit integration fix. Source tests passed
43 cases plus seven supervisor scenarios and the correction-state check.

Initial alpha limits are deliberate: supported score/camera family, short clips,
Apple Silicon, no previous-run browser, four-output export, and no calibrated
fingering probabilities. Physical macOS 14 and second-Mac testing, musician label
assessment, Developer ID/notarization and public binary redistribution clearance
remain open delivery/research gates. An ad-hoc signed local app is not evidence
that those gates have been satisfied.
