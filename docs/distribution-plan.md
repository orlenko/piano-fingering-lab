# Signed evaluation installer

Problem: another musician should install the existing offline app by dragging it
from a DMG into Applications, without a developer environment or Siri settings.
The operator authorized reuse of the existing Xcode/Developer ID/Keychain notary
setup for this app. Credentials remain in Keychain; no account data is committed.

The smallest first increment is a documented manual release using existing Apple
tools and existing app checks. No new release controller, subprocess runner or
automatic retry system is needed before the first qualified installer. Existing app algorithms/runtime identities
stay unchanged. Target remains Apple Silicon/macOS 14+, qualified on the current
Mac; a recipient-machine test is still required. No microphone, camera, Siri,
Apple Intelligence, API key or internet connection during analysis is required.
Normal file-access prompts can apply to protected folders.

Use the existing internal app, a new ignored .local/ release directory created
exclusively with owner-only permissions, and an explicit existing Keychain profile
for submission. Keep all staging, installers and raw evidence there. Copy
the app into a newly owned private staging folder. Before signing, the operator
must reject existing outputs,
external symlinks, input/result manifests or private deliverable filenames in the
bundle; permit only the existing bundled code/models/licensed package data.
There are no user projects or source media in the copied app. The input app and
existing test artifacts are preserved. Submission is a separate, explicit operator action after local qualification. User authorization for this run includes Apple notarization
of the built app/DMG; it does not permit uploading source media or credentials.

Discover a sole valid Developer ID Application identity locally, or accept an
explicit identity. Do not print certificate/account/credential details. Sign all
nested Mach-O binaries before the enclosing app using the same identity, secure
timestamps and hardened runtime; no --deep signing. Apply no blanket library-
validation or executable-memory exemptions. If dependencies need an exception,
first reproduce and justify the minimal executable-specific entitlement and
obtain affected review. Verify signatures, then run bundled health, native media
and synthetic UI checks on the signed copy before packaging/submission.

Create a compressed read-only DMG containing the app and an Applications link,
plus a short usage/limits note. Sign and verify the DMG, submit it with notarytool
using the existing Keychain profile, and preserve its submission ID/private log.
Submit without an implicit wait/retry, retain the returned ID, then poll bounded
status calls for at most 20 minutes per observation window; a client timeout is not a rejection or permission to
resubmit blindly. Persist a checkpoint before submission: an attempted upload
without a captured ID is UNKNOWN and needs history reconciliation to identify
that exact artifact before any new submit. With a known ID use notarytool info/log
on that ID only; after the observation budget ends retain PENDING for later
status checks. Rejection retains its ID/log and requires diagnosis before a new
artifact/submission. Unknown/pending/rejected artifacts are not recipient-ready.
Accepted status is required before stapling and validating the
DMG ticket. Assess with Apple's distribution/Gatekeeper tools, verify/mount the
DMG read-only at a private owned mountpoint, and check the contained app/signature
and actual copied-out launch. Detach only this owned mountpoint. Never imply a
local launch proves physical minimum-version or recipient compatibility.

Use existing shell/tool sessions and direct argv commands with finite deadlines
(60 seconds per signing/status operation, 10 minutes upload/DMG creation). Bound
private diagnostics to 4 MB per command and stop on overflow. Preserve tool-owned
process ownership; on interruption stop/reconcile that owned command before a
subsequent write. Attach only at an explicit private owned mountpoint; an ambiguous
attach must be reconciled via hdiutil info for that path before any detach. Never
signal remembered PIDs or detach unrelated mounts. Preserve evidence on failure.
Failure preserves the candidate and evidence; no previous installer is overwritten.
Report signed, submitted, accepted, stapled and assessed as separate states.
Notarization is a security/signature check, not musician accuracy or third-party
redistribution clearance. Keep bundled notices/model provenance; this is a private
evaluation installer, with public binary redistribution review still separate.

Reviews: independent skeptical general design; separate security/privacy lens
(credentials, explicit upload boundary, bundle contents, identity/signature), and
reliability lens (command deadlines, notary unknown state, owned staging/mounts,
publication/collision/failure). At finished instructions/evidence use a fresh independent general
review before peer conclusions and separate affected specialist reports, then
an adjudicator distinct from implementer/report authors. Data-integrity specialist
is inapplicable to app data: no project/store/schema/migration changes; artifact
ordering is covered by release reliability review. Product/domain/accessibility is selected at both stages for the recipient
installation workflow; app musical logic and existing UI accessibility are outside
this increment. No new user-store transaction needs a separate data lens.

The included note must say: open DMG, copy app to Applications (drag or ordinary
Finder keyboard copy/paste), eject, launch copied app. State chip/OS target vs
actual qualification, offline analysis and no Siri/Apple Intelligence/API/developer
setup. Never instruct recipients to bypass security assessment. Before recipient
delivery the operator must resolve applicable bundled third-party redistribution
conditions; Apple acceptance alone supplies no rights clearance. No recipient
send or public binary publication is performed by this packaging run.

Acceptance: existing app untouched; existing signed runtime and UI checks pass; DMG integrity verified; installation note checked; Apple
returns Accepted; stapled ticket validates; Gatekeeper assessment succeeds. Record
actual outcomes and gaps without declaring success at a missing stage. Source
integration follows existing actual-index/privacy/review rules. No new feature
code or synthetic orchestration tests are introduced for this manual process. Authored size is
counted against the current accepted base; aim below 500 lines in this increment.

References: [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution),
[custom workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow),
[distribution packaging](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution).
