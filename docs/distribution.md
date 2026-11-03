# Installing and signing Fingering Studio

The evaluation app targets an Apple Silicon Mac (M1 or later) on macOS 14+.
It bundles Python, models and media tools. Siri, Apple Intelligence, developer
tools, an API key and an AI subscription are not required. Analysis is offline.
Allow several GB for the app and projects. Normal protected-folder prompts and
macOS first-launch verification can apply. The recipient machine and physical
minimum OS still need qualification; local test results cannot establish them.

[INSTALL.txt](../desktop/INSTALL.txt) is the note included in the disk image.
Open the DMG, copy the app to Applications using Finder drag or keyboard
copy/paste, eject the DMG, then launch the copied app. Do not run security-bypass
commands if macOS assessment fails. App inputs retain the short-video and
supported-score restrictions in [desktop.md](desktop.md).

## Manual release route

Follow the independently reviewed [distribution plan](distribution-plan.md).
Use the existing Xcode/Developer ID Application identity and an existing notary
Keychain profile. Never put passwords, identity details or account names in
source, logs intended for publication, or this documentation. Keep staging and
raw evidence in a new ignored, owner-only `.local/` release directory. Preserve
the original internal app. This workflow adds no automatic release controller.

1. Check copied bundle contents, external symlinks and source/runtime provenance.
2. Sign each nested Mach-O file, then the enclosing app, with the same Developer
   ID identity, secure timestamp and hardened runtime. Do not use `--deep` to
   sign or add blanket entitlement exemptions. Verify all nested signatures.
3. Run existing relocated pipeline, synthetic native UI and Apple media checks
   against this signed copy. Signing changes runtime policy and needs its own
   qualification. These tests do not measure musician accuracy.
4. Stage only the signed app, the installation note and an Applications shortcut.
   Create and sign a compressed read-only DMG with `hdiutil` and `codesign`.
5. Record its digest and a pre-submission checkpoint. Explicitly submit to Apple
   with `xcrun notarytool submit`, selecting the existing Keychain profile; retain
   the returned submission ID. Query that ID with `info`/`log`. No implicit retry.
6. After Apple reports Accepted, use `xcrun stapler staple` and `validate` on the
   DMG. Verify image integrity and Gatekeeper assessment. Mount only at an owned
   private mountpoint, copy out the app, verify and launch the copy, then detach
   only that mountpoint. Preserve incomplete stages and private diagnostics.

UNKNOWN means an upload was attempted without a captured submission ID: reconcile
Apple history and the exact artifact before any new submission. PENDING means a
known ID still needs a status observation. A rejected artifact needs diagnosis
from its retained log before changing/rebuilding/submitting. None is ready for
recipient installation. Observation windows are bounded; a timeout is not an
Apple rejection. Source, signed, accepted, stapled and assessed are separate states.

Signing and notarization do not clear third-party redistribution conditions.
Keep the original bundled notices and model provenance. The operator must resolve
applicable exact-binary source/model conditions before recipient delivery; public
binary publication is a separate gate. This packaging run sends no installer to
a recipient and publishes no binary release.

The actual evaluation outcomes, reviewer scopes and remaining gates are recorded
with this source increment. Public records exclude account/credential identities,
raw notarization logs, local media paths and source-derived musical data.

Primary references: [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution),
[custom workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow),
and [packaging](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution).


## Evaluation outcome (2026-11-03)

The operator authorized the existing Xcode/Developer ID authentication route for
this app and confirmed the recipient has Apple Silicon with macOS 14 or later.
That matches the target, not a completed recipient-machine test.

A separate exclusive ignored release directory with owner-only permissions holds
the candidate/evidence. The original internal app was preserved. Bundle checks
found no external symlinks or private input/project/deliverable filenames; the
model checksum and runtime manifest remained unchanged. All 427 native components
and the enclosing app were signed with one existing Developer ID Application
identity, secure timestamps and hardened runtime, without entitlement exemptions.
Deep strict signature verification passed.

Owner-observed signed qualification passed all four synthetic native UI launches,
a relocated complete analysis/correction/update/export/stop workflow, **667/667**
video frames with relative PTS error below 1 ms, and Apple-native video/PDF decode
checks. The existing driver was used with its app path directed at the signed
copy. Its outer wrapper initially used a stdlib-only interpreter and failed only
at the final PyAV frame comparison, after worker workflow checks had passed; that
comparison was completed separately using project Python 3.11. This was a test
wrapper error, not an app crash or a silently passing driver run. No private
image was opened in assistant context; native UI checks used synthetic fixtures.

The approximately **646 MB** read-only DMG was signed and its image/signature
verified. Its staged installation note and Applications link were checked. A
read-only mount at an owned private path contained the expected installer files;
the note matched source, the copied-out app's signature verified and its native
launch passed. Only that owned mount was detached. Command deadlines and private
persisted diagnostic limits were applied, not inferred from display truncation.

**Apple notarization completed successfully.** Initially the configured history query
returned valid history, but subsequent credential lookup was unavailable; its
cause is unproven. Xcode also reported `No Accounts`. The operator restored the
existing account, after which the CLI account registry and notary profile were
available again. The direct DMG upload completed and Apple returned a submission
receipt. Apple returned **Accepted**, and its log reported **zero issues**. The
known ID was observed throughout; no blind resubmission occurred.

The earlier Xcode authenticated-export fallback reached its 600-second deadline;
Apple history later showed its separate app-ZIP submission, last observed as
**In Progress/PENDING**. Both IDs were retained and reconciled. No related archive/export process remained. The Xcode timeout is
not an Apple rejection and supplies no acceptance proof; the DMG remains the
canonical installer candidate. Captured command diagnostics have a 4 MB limit.
Xcode also generated larger diagnostic bundles under the OS user-private temporary
root; those native side effects are outside the capture limit, excluded from
public evidence, and not represented as globally bounded/contained tool writes.

The DMG ticket was stapled and validated. Post-stapling image integrity, signature
and Gatekeeper distribution assessment passed. The copied-out app also passed
its Gatekeeper assessment, deep strict signature check and native launch. A
separate LaunchServices `open` check passed on that unmodified copied app, followed
by another successful signature verification. Only the owned read-only mount was
detached. The earlier `Unnotarized Developer ID` assessment is superseded by these
successful final assessments. There is no security bypass or recipient delivery.

The final installer is approximately 646 MB, with SHA-256
`d05bac2704dc7bc606931b0f5a7f6259061f6d6096e453c9cb8f033f2e8eaa8f`.
The app source is `eceb83b1164088ba4f2fb05d2923724da884ee7d`; subsequent
repository changes in this increment are documentation/install-note only. The
Developer ID signing identity and raw receipt/logs remain private; this record
does not present source review as an independent signing attestation.

Review provenance: separate general, security/privacy, reliability and recipient-
installation design contexts inspected the proposal before signing. A separate
adjudicator reconciled findings. Original DG-001 added the missing product lens;
DG-002 retained recipient rights clearance; DG-003/RP-D-003/PD-D-001 preserved
unknown/pending/rejected recovery; DG-004 clarified manual operator checks;
SP-D-001 selected owner-only ignored storage; RP-D-001/002 added real bounds and
ownership; PD-D-002 defined keyboard-capable installer instructions. All advice
was accepted and affected design reviews confirmed plan blob
`789ed801c85b0f0ffa33ba8b57fadd182071b5fa` before signing. No finding was waived.

Fresh general report FG-FINISHED-01 formed its findings before peer conclusions;
separate specialist instruction reports SP-F-001, RP-F-001 and the product report
found no confirmed instruction defect at initial source. Specialist design
exposure was disclosed. The reliability design context also disclosed incidental
security-report exposure after independently identifying its initial boundaries;
it is not counted as fresh general review. Reviewers inspected public source
only and did not execute signing, inspect private logs/runtime artifacts or
independently reproduce owner observations. Native tool boundaries are instructed,
not enforced or authenticated attestations. This outcome leaf requires affected
review and separate adjudication before source integration; their final source,
checks and dispositions are bound in the integration commit message. Final
record findings FG-001 and RP-F-002 both requested the explicit fallback pending
state above; the owner accepted that clarification without changing the canonical
installer or re-submitting either artifact.

Recipient compatibility, physical minimum-OS qualification and applicable
third-party redistribution conditions remain open.
Public binary publication and musician-verified fingering accuracy are separate.
No canonical pipeline/test or runtime-tool adoption claim follows from these
source instruction reviews; no app algorithm or quality runtime/config/pin changed.
