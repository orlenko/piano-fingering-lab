# Manual review supplement adoption

Status: explicit manual source-process procedure. The integration commit binds
final source acceptance as described below. This adds no runtime enforcement or
completed feature-review claim.

## Source and bounded design

Adopt the shared [manual workflow](https://github.com/orlenko/software-quality/blob/36b0b858b293e14af726e0adf58af476334ccd5d/docs/review-workflow.md)
and [role instructions](https://github.com/orlenko/software-quality/blob/36b0b858b293e14af726e0adf58af476334ccd5d/docs/review-roles.md)
from source `36b0b858b293e14af726e0adf58af476334ccd5d`, tree
`133f8d9130d8fbe12a90e8167d86b63813f14433`. Those exact Git objects were
read locally. This is a manual supplement to the existing pinned standard, not
a replacement runtime policy, artifact build source or automatic fleet update.
Role instructions remain centralized at those immutable links.

Problem: make future substantial work use explicit independent review roles and
source-bound finding resolution while retaining the experiment's privacy and
musician-evaluation requirements. The smallest useful change is one discoverable
AGENTS reference, this local procedure/record, and a cross-reference in the
existing quality setup document. No scripts, copied personas, dependency changes,
model downloads, API calls, bot/controller, app restart or live-review activation.

One documentation increment starts from `eceb83b`, the reviewed desktop source
already integrated on main. Acceptance: instructions point to exact shared source;
review/context capabilities and gaps are truthful; the normal design/code/fix/
integration procedure is discoverable; independent design/document review and
separate adjudication are recorded; actual staged public bytes and links are
checked. The existing disabled config/lock and all product source stay unchanged.

There is no concurrent product edit to reconcile: the product working tree was
clean at this base. One local integrator owns this repository across worktrees;
the older quality proposal worktree is left untouched. Other sessions provide
review/support and do not introduce competing setup branches or duplicate state.
Future overlap requires exact source/ownership reconciliation, never reset/clean,
force push or overwriting unrelated work.

## Normal feature procedure

Use the pinned workflow and checklists rather than copying them into the repo.
For each future change, record:

1. The user problem, observable acceptance, smallest working alternative, data/
   store effects, failures/recovery, checks and self-contained working increments.
   Aim for about 500 authored additions plus deletions and strongly prefer fewer
   than 1,000, counting handwritten tests/config/docs against an explicit base.
   These are recommendations, not new size gates. Explain coherent larger changes;
   identify generated/vendor/mechanical portions separately without hiding risk.
2. Independent skeptical general design review before substantial code, plus
   risk-selected specialist contexts/reports at **both design and code stages**.
   Select security/privacy, data integrity, reliability/performance and product/
   domain/accessibility where relevant, with reasons for inapplicable lenses.
   Relevant but unavailable review stays required and incomplete. A separate
   adjudicator reconciles design reports before implementation; the owner records
   accepted/rejected advice and rationale before writing substantial code.
3. At finished code, a fresh independent general bug hunt forms its findings
   against exact source and acceptance before seeing author/peer conclusions.
   Record previous exposure; a new label/model is not proof of independence.
   Specialists trace the actual changed boundaries and dependencies separately.
4. A separate adjudicator, neither implementer nor author of the reports being
   reconciled, receives original reports and completeness records. Preserve every
   original report/finding ID, location, reachable scenario and consequence.
   Group only true duplicates; classify by evidence, impact and dependencies.
   Name next owners/actions and preserve disputed claims for the named owner.
   Required-review completeness remains separate from finding disposition.
5. Fix accepted blockers, retain stable IDs/source-bound dispositions and obtain
   affected re-review/checks on the fixes. Missing review, a majority, a preferred
   model, elapsed rounds or a summary cannot waive a valid blocker. A rejected
   claim needs evidence and the approved report/owner reconciliation route.
6. Before source integration, complete the full applicable canonical/integration
   gate on the real final tree and actual index, including interaction checks for
   combined increments. Bind incremental/stack evidence to immutable parents and
   heads; restacks/base changes invalidate affected evidence. Do not manufacture
   an index, reviewer attestation or toolkit pass. Keep release/installation/
   observed runtime adoption separate from reviewed source integration.

## Actual routes, ownership and stronger rules

The available review route is native separate-agent contexts in this coding
session, with public source/diff and explicitly scoped read-only instructions.
No approved optional live API/controller/provider/account route is established
by this adoption. Source may enter the coding assistant's inference context;
this is not a local-model-only review claim. No private score, recording, derived
labels, diagnostics, credentials or unrelated consulting documents may enter
reviewer context. No private fixture is needed for this documentation increment.

Native contexts have broader tools available; read-only/path/network restrictions
are instructed rather than mechanically enforced. Their actual inspected scope
and observed actions must be recorded. Fresh contexts and distinct report authors
can support manual source review; they do not prove authenticated independent
identities or satisfy the enforced-boundary attestations absent from the disabled
runtime setup. A required route needing unavailable containment remains incomplete.

The local source integrator coordinates exact revisions across checkouts. A
separate native review-adjudication context is the first dispute/reconciliation
route; record its actual task/identity per change, not merely a permanent label.
The operator is the named final owner for unresolved scope/authority disputes.
An unavailable independent adjudicator is a missing review, not permission for
the implementer or conductor to act as an independent judge of their own report.

[AGENTS](../AGENTS.md), [HANDOFF](../HANDOFF.md), and the
[existing setup record](quality-adoption.md) remain stronger local constraints:
no gold-label prerequisite; preserve uncertainty and auto/manual provenance;
explicit approval for source-media disclosure; local processing/stage/media
inspection and musician assessment remain separate; independent pre-code and
finished review cover execution, measurement validity and privacy; fix/re-review
blockers; publish only cleared/synthetic examples. Earlier image-disclosure
history in [review.md](review.md) remains unchanged. This prospective supplement
does not retroactively satisfy missing historical review chronology.

Use main for this early experiment and push reviewed source/sanitized records.
Existing staged-whitespace, actual-index/static privacy and separately authorized
dynamic-private obligations retain their own exact evidence. Documentation-only
checks do not authorize private scans, consumer tests, provisioning or uploads.
The canonical suite remains applicable to changes requiring that runtime gate;
never substitute partial checks for a required full gate. Report precise missing
effects/capability authorization instead of silently changing the gate.

The tooling/runtime/artifact pins in `.quality/config.json` and `.quality/lock.json`
stay unchanged, including disabled consumer execution. This record is neither a
`recorded-v1` envelope nor a new schema or controller qualification. Existing doctor
incompleteness and absent enforced reviewer attestations are not closed here.

## Review plan for this documentation increment

General design review checks minimality, acceptance, ownership, chronology and
compatibility. A separate security/privacy specialist checks authority, source
visibility, instructed versus enforced boundaries and public-data scope at design
and finished-document stages. Data-integrity and reliability specialists are not
selected: no product store, schema, transaction, worker, budget or runtime changes.
Product/domain/accessibility is not selected: no musician workflow/output or app
interaction changes; its existing human-evaluation obligations stay explicit.
These choices apply only to this documentation increment, not future features.

Separate design adjudication precedes implementation, and the owner records its
accepted/rejected design decisions. A new finished-document general reviewer first
reads exact candidate source without peer conclusions. A separate adjudicator then reconciles original findings and
required-review completeness. No actual feature walkthrough or live route is
claimed. Checks are public Markdown/reference/source-diff/staged-whitespace and
actual public index/static-privacy inspection, with no private dynamic scan or
pipeline rerun for this documentation-only change. Record exact sources, original
finding IDs, dispositions, checks and final integration below after they occur.


## Adoption evidence and disposition

Comparison base: `eceb83b1164088ba4f2fb05d2923724da884ee7d`, tree
`2a27da349e7986fcb3e40ad474ae4f36b1b5983e`. The design proposal was public
blob `ff34a0e89c28ec22ef5508d089640d3572d5575e` (SHA-256
`3d4f7e5c5c6e0343bb3e5e1a2f893d43f8c2d47ad64d4f25a010fd4cabf8af3d`).
Its hash was observed before the AGENTS/setup edits; this does not invent an
already-stored Git object or a historical feature review.

General design context `manual_design_general` reported no blocker and original
finding **DG-001**: explicitly place design adjudication before implementation,
rather than leave sequencing implied by the central link. Privacy context
`manual_privacy`, report **SP-DESIGN-01**, found no issue in its declared design
scope. Separate `manual_adjudicator` verified both original reports/completeness
and classified DG-001 as a confirmed improvement. Owner decision: accept; spell
out pre-implementation reconciliation and recorded owner decisions in both the
normal procedure and this increment plan. The candidate now contains that fix.
No design advice was rejected and no blocker was waived.

These are actual native task/context labels for this increment, not authenticated
identities or ongoing guarantees of route availability. The adjudicator authored
neither input report. The privacy reviewer may examine finished documentation in
the same specialist context with design exposure disclosed; it cannot count as
the fresh finished general reviewer. Final reports, affected re-review, checks
and source integration are bound in the closing evidence below and the integration
commit message.


Finished-document privacy report **SP-FINISHED-01** inspected all three candidate
files with no finding; its design exposure was disclosed. Initial general context
`manual_finished_general` disclosed premature design-ledger exposure as original
**FG-001**, a required-review completeness gap; it was not counted as the fresh
review and that original record is retained. Replacement `manual_fresh_bug_hunt`
used a separate fresh context, sent its independent findings/completeness before
reading the ledger, then completed factual-status review with no finding. This
fills the missing route rather than reclassifying or erasing FG-001. General and
privacy reports bind candidate blobs `d48115035c3983ec0df0a490a7ec6394b347bdf8`
(AGENTS), `d484e00b156fea80f450c6da0981081aaa63257d` (existing setup record),
and `63b8901169c58ed553e2179080a5e62bd19bc180` (procedure before this evidence
leaf). DG-001's original design reviewer verified the clarification in that
candidate and marked only the affected design finding resolved.

The original reviewed candidate is 192 authored additions across three Markdown
files against the stated base, counted with `git diff --cached --numstat`, with
no generated/vendor exclusions. This closing evidence leaf is counted in the
final integration diff too; no size gate or historical size waiver is created.
The previous larger product change is not retroactively claimed to follow this
new procedure or its planned increment guidance.

Owner-observed checks on that candidate: working/index bytes matched; all nine
relative Markdown targets and three pinned shared-source file links resolved;
actual staged whitespace passed; the existing static privacy guard passed
**one selected test** on the real public working/index bytes using the existing
isolated environment with plugin autoload and pytest cache disabled. It did not
read the private input manifest/PDF, run the dynamic test or run the canonical
suite/pipeline. Public source and index checks are appropriate to this docs-only
increment; they are not a full runtime gate. No package provisioning, model/API
call, app/monitor restart or private-data operation was performed for adoption.

Config/lock remain byte-for-byte equal to the base: Git blobs
`c914c8d3a9b52209fc971d01805d2d17fe350512` and
`26da61596e3fe92b25e48d56b321f49b8cc6e553`, respectively. Product files and the
other worktree are unchanged. Source, docs, review records and public static
checks are the only effects of this increment.

Affected final-record reviews and separate finished adjudication must inspect the
closing evidence and repeat the public/index checks before source integration.
The commit containing this adoption records their final disposition, the exact
final tree, authored diff count and check result in its commit message; ordinary
Git metadata supplies the final source identity without a self-referential tree
hash inside this file. Until those events occur, integration stays incomplete.
This remains manual documentation adoption, with live API/controller, enforced
reviewer attestation, runtime execution/full adoption and prior-feature walkthrough
claims explicitly absent. Future required routes must be provisioned only within
their own approval; unavailability remains incomplete.
