# Shared quality setup

Status: source/configuration setup with consumer execution disabled. Owner acceptance
uses normal reviewed main integration; it does not enable runtime gates or establish
verified full adoption. [AGENTS.md](../AGENTS.md) and [HANDOFF.md](../HANDOFF.md) remain
binding. Shared policy stays in the [pinned standard](https://github.com/orlenko/software-quality/blob/db120201d3f38d1c6e444bc4d1ca9586c3d8eee0/docs/development-standard.md).

## Design and acceptance

Problem: use one shared pinned tool while preserving real experiment/privacy/review
obligations. Reuse the reviewed three-file proposal at `fe273cb47e6230c6ac9b59634e64dfb6c77590e4`;
its proposal-only installation/integration restrictions were historical, not current
rollout authority. The smallest useful change is source acceptance, verified external
installation and a documented metadata invocation. No per-project policy engine,
wrapper framework, copied toolkit code or global command registration is introduced.

Piano is the sole setup integrator across checkouts; the operator adjudicates scope
and disputes. Source acceptance, local install, metadata execution, consumer-gate
execution and full verified adoption are separate states. Keeping unsupported stages
disabled permits useful source setup without inventing missing evidence or a waiver.

The historical manual public/synthetic subset belongs to source
`df9a730d509943f5b400cef8fd2849a8ec68b783`, tree
`26ebd9e09a73de95e3a629ecf8b1f39a27dab968`; its evidence remains private. It is not
a new full-suite result, context-bound review or receipt for this setup.

## Immutable tooling and local installation

Publisher `orlenko/software-quality`, R2 core `0.1.2`, policy `0.1`, schema `1`,
recorded-review protocol `1`. Build source:
`db120201d3f38d1c6e444bc4d1ca9586c3d8eee0`; archive
`software-quality-0.1.2-root-alias.pyz`, SHA-256
`7b87b9c23fbaf43941729f8bb2b0e1969fbf6872b02d8dbd23e074714bc526b0`.

- `quality_launch.py`: `14d77ae4dd7a9fa69197f970fc7c98a716b65c1e7486ceb668b7b8f7a621aaf6`
- `quality_trust.py`: `4c3ebc346b1428e1d226180ecbb05a249c90de48ae25cdc8438b89bb901f6c2e`

The unchanged archive, all 29 inventory members and both bootstrap files were
verified before loading; the isolated shared installer completed successfully in
new private outside-consumer storage. Actual paths, command/log hashes and immutable
inventory evidence stay private. This is observed local installation, not a portable
claim about every checkout or permission to select another artifact by version.
Current shared-source heads and the old pilot table are not archive build sources.
No optional adapter, live source-review controller or model was installed.

The tooling interpreter is existing CPython 3.14.7 on Darwin arm64, with `-I -S`;
site startup is excluded. Consumer Python 3.11 remains separate and is not selected
for tooling metadata; no new capability result for that interpreter is claimed. Retain the shared
waitid/WNOWAIT and default-SIGCHLD guards, benign capability probe and owned-process
finalization. A symbol check alone is not successful process-capability qualification.

## Documented metadata entry point

Use independently approved outside-target paths: `QUALITY_PYTHON` is the tooling
interpreter, `QUALITY_BOOTSTRAP` the verified bootstrap directory, `QUALITY_CACHE`
the installed immutable archive cache, and `QUALITY_STATE` the private per-repo
state root. Keep bootstrap, cache, state and private review evidence separate from
one another and the consumer. Paths and authentication do not come from target head.
Use one canonical `QUALITY_REPO` and shared state route across this owner's worktrees;
reconcile other machine/session setups through the sole owner instead of duplicating.

After reviewed main integration, choose full accepted commits containing this
config/lock as `QUALITY_BASE` and `QUALITY_HEAD`. Equal values inspect the setup;
they do not demonstrate a representative code change or the media pipeline.

```sh
"$QUALITY_PYTHON" -I -S "$QUALITY_BOOTSTRAP/quality_launch.py" doctor \
  --repo "$QUALITY_REPO" --base "$QUALITY_BASE" --head "$QUALITY_HEAD" \
  --identity orlenko/piano-fingering-lab \
  --cache "$QUALITY_CACHE" --state "$QUALITY_STATE"
```

This invokes trusted toolkit code and its benign interpreter probe/owned runner
subprocess, reads public committed Git/config/lock data and writes private reports.
It imports no consumer code and requests no gate, model, private-input or provider
execution. No `--execute-trusted` or fabricated review envelope is supplied.
Inspect the actual report: exit 2 with completed inspection/source/artifact evidence
and missing command/snapshot/output/review stages is expected incompleteness.
Pre-report refusal, capability failure, cancellation or uncertain cleanup can also
return 2 and are not a completed metadata run. Bind evidence to exact base/head/tree,
config/lock/artifact/toolkit identities; later source/status commits are outside that
context. Keep raw logs and reports private. No doctor outcome is assumed by this note.

## Required versus observed

| Obligation | Requirement and current limit |
| --- | --- |
| Canonical suite | Existing documented `uv run pytest -v` is declared as required; no new run here. uv can provision dependencies. The historical subset does not cover the full suite. |
| Actual-index/static privacy | Inspect real tracked/staged/unignored bytes; exported or synthetic indexes cannot substitute. |
| Dynamic private privacy | Existing local manifest/PDF phrase scan needs its own authorization. An absent manifest causes a skip; a present invalid/missing score fails. A skip is incomplete, not passing this obligation. |
| Staged gate | Explicit staged-whitespace requirement alongside actual-byte/privacy integration review; immutable-range whitespace alone is insufficient. Historical checks do not create a universal fresh-runtime policy. |
| Design and finished review | Separate-agent critique before nontrivial implementation, then finished review covering execution, measurement validity and privacy; fix blockers and re-review. Chronology remains an external obligation. |
| Experiment and musician | Preserve stage/protocol/output inspection, uncertainty, auto/manual provenance and musician evaluation. Correctness remains unverified; operator-written gold labels are not a prerequisite. |

`trusted_local: false` and `isolation: unavailable` remain unchanged. The argv
requirements do not authorize uv provisioning, dependency/environment/cache writes,
private metadata in diagnostics or real-index access through raw snapshots. Snapshot
exports omit Git metadata/private inputs, and editable environments can import a
different tree. Schema 1 cannot enforce no-skip/private-availability policy, actual
index selection, pre-code chronology, output inspection or human assessment. The
600-second per-check cap stays binding; partial timing cannot prove full coverage.
Runtime enablement needs an approved exact dependency/import/effects/wrapper route.
Fresh HOME/XDG roots are not platform-store, filesystem or network containment.

Both review routes name the actual separate draft reviewer's short task label,
`quality_requirements_review`; this is neither authentication nor future availability.
The same reviewer may cover both phases without inventing two identities. Required
read-only/enforced tracked-source tools are not observed native enforcement; no
matching attestation, producer/controller envelope or executed-stage record exists.
Required `network: false` concerns reviewer tool egress; `disclosure: public-source`
acknowledges assistant inference on public source, not a local model. The newer
shared source-review controller is not live-qualified or an automatic attestation.
Private artifacts stay excluded. Earlier pre-implementation history remains
unavailable; [the disclosure correction](review.md) remains unchanged.

## Review, integration and remaining gates

The original separate design and final three-file reviews cleared the disabled
requirements proposal. Wording fixes distinguished absent-manifest skip from failure
and existing commands from proposed requirements. One reviewer `git write-tree`
operation was disclosed as metadata writing; final exact-byte re-review used reads
only. Native review evidence is not the missing enforced-boundary attestation.

Before this rollout implementation, separate design critique accepted reuse, verified
external install and metadata-only inspection. Dispositions distinguish all setup
states, include probe/runner effects, distinguish report incompleteness from launcher
refusal, bind exact integrated context and use one canonical target/state route.
Independent finished rollout source/schema/link/publication review found no blocker.
Disposition: narrow interpreter wording to the actually selected tooling route rather
than claim a new consumer-Python capability observation. The reviewer inspected only
public source/diffs/metadata; archive verification and installer exit are owner-observed
private evidence, not independently executed review results. No doctor result is
established by source review. Final exact-byte re-review covers this record too.

Normal integration requires real staged-byte/privacy inspection, appropriate static
checks, independent final review and exact-tree stability. No runtime/private gate
is claimed by those checks. Resolve actual wrapper/index/no-skip/reviewer gaps and
obtain fresh required evidence before gate enablement or verified full adoption.
Do not replay the old baseline, backfill history, manufacture an index/receipt or
silently change policy. Dirty/moving source, stale evidence or uncertain cleanup
stays incomplete; preserve its owned report and resolve with the integrator.


## Prospective manual review supplement

The separate [manual procedure and adoption record](quality-manual-review.md)
selects centralized workflow/roles source
`36b0b858b293e14af726e0adf58af476334ccd5d` for future manual reviews.
That source pin is distinct from the unchanged R2 runtime/artifact build source,
config/lock and policy pins above. It adds explicit role selection, independent
reports and separate adjudication without enabling execution or claiming an
attestation, live controller, prior-feature walkthrough or full runtime adoption.
The local record names actual native review capabilities and remaining gaps;
stronger experiment/privacy requirements and historical incompleteness remain.
