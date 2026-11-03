# Quality requirements proposal

Status: unfinished work-branch proposal; execution disabled. This is neither an
accepted configuration base, an installation nor verified adoption. Existing
[experiment rules](../AGENTS.md) and [output goal](../HANDOFF.md) remain binding.

## Design before configuration

Problem: record this consumer's actual checks and review obligations without
turning a public synthetic subset or a configuration requirement into evidence.
The smallest alternative is to retain prose only; three proposed files make the
requirements and candidate pin inspectable while leaving execution disabled.
Acceptance for this draft is public-source/schema/privacy review, not a runtime
gate pass. No installation, tests, private-input access or media processing is
part of this change; existing outputs and the main checkout are untouched.

Selected source: `df9a730d509943f5b400cef8fd2849a8ec68b783`, tree
`26ebd9e09a73de95e3a629ecf8b1f39a27dab968`. The historical manual baseline at
that source covered a public/synthetic subset; its detailed evidence remains private.
It is not context-bound evidence for this draft or the full canonical suite.

The proposed R2 core pin is `orlenko/software-quality` engine `0.1.2`, policy
`0.1`, schema `1`, recorded-review protocol `1`. Build source:
`db120201d3f38d1c6e444bc4d1ca9586c3d8eee0`; artifact SHA-256:
`7b87b9c23fbaf43941729f8bb2b0e1969fbf6872b02d8dbd23e074714bc526b0`.
The corresponding launcher/trust source hashes are:

- `quality_launch.py`: `14d77ae4dd7a9fa69197f970fc7c98a716b65c1e7486ceb668b7b8f7a621aaf6`
- `quality_trust.py`: `4c3ebc346b1428e1d226180ecbb05a249c90de48ae25cdc8438b89bb901f6c2e`

These are proposed identities, not artifact-byte verification or install approval.
The old pilot-contract identity table is historical; the build-source lock schema
and explicit R2 selection govern this proposal. No held artifact is selected.

## Required versus observed

| Obligation | Requirement and current limit |
| --- | --- |
| Canonical suite | Existing documented `uv run pytest -v`, proposed as required by this configuration; no new run here. uv can provision dependencies. The historical subset does not cover the full suite. |
| Actual-index/static privacy | Inspect real tracked/staged/unignored bytes; exported or synthetic indexes cannot substitute. |
| Dynamic private privacy | Existing manifest/PDF phrase scan remains local and separately authorized. A missing-input skip is incomplete, never proof of passing this obligation. |
| Staged gate | Proposed explicit staged-whitespace command alongside actual-byte/privacy integration review; immutable-range whitespace alone is insufficient. Historical checks are not a newly inferred universal runtime policy. |
| Design and finished review | Separate-agent critique before nontrivial implementation, then finished-code review covering execution, measurement validity and privacy; fix blockers and re-review. Chronology remains an external obligation. |
| Experiment and musician | Retain stage/protocol/output inspection, uncertainty, auto/manual provenance and musician evaluation. Correctness remains unverified; no operator-written gold labels are a prerequisite. |

The same separate reviewer may perform design and finished reviews; this does not
create two independent identities. Both `reviewer_id` values use the current separate
draft reviewer's actual short task name, `quality_requirements_review`; this label
is not authentication or a promise of future availability. Adoption must establish
the actual independent identity for fresh required review records. Proposed source-review boundaries are required
properties only: actual native tools are broadly capable, so tracked-source-only
read-only enforcement is unavailable. No matching enforced-boundary attestation,
producer/controller envelope, reviewer authentication or executed-stage record is
created. Public-source assistant inference is disclosure, not local-model review;
private artifacts remain excluded. The required `network: false` prohibits reviewer
tool egress; `disclosure: public-source` acknowledges assistant inference on public
source. Neither field asserts that the assistant model runs locally. Earlier pre-implementation review history is
unavailable; [the disclosure correction](review.md) remains unchanged.

The first schema cannot express no-skip/private-availability policy, real-index
selection, pre-code chronology, media inspection or human assessment as enforced
stages. Declaring these requirements does not fill those gaps or create waivers.
Raw snapshots have no Git metadata, editable environment or private inputs; uv may
download/build, while reusing an editable environment may import the wrong tree.
There is no approved consumer wrapper, dependency environment, isolation route or
reviewer enforcement for toolkit execution. The per-check cap is 600 seconds;
partial/cached timing cannot establish complete whole-gate coverage.

## Acceptance and effects

Piano is the integrator; the operator adjudicates disputes and new permission.
The configuration keeps `trusted_local: false` and `isolation: unavailable`.
Its argv entries name listed existing commands and proposed requirements, not permission to
execute them in a snapshot or against private inputs. Credentials, platform stores
and network are not isolated by fresh HOME/XDG roots. Future artifact cache, state,
review evidence and approved bootstrap/environment must be outside the consumer
and mutually separated as required by the toolkit; no such installation is made.

Before actual acceptance: resolve the wrapper/import/index/private/no-skip gaps,
establish actual reviewer permissions and evidence, independently approve pins,
review a clean exact candidate and satisfy all applicable real integration gates.
Any future run needs fresh base/head/tree/config/lock identities; this branch and
historical subset are not a fabricated accepted base or retroactive receipt.
Dirty/moving source or stale evidence stays incomplete and returns to the owner;
no reset, policy relaxation or automatic fallback. Installation, main integration,
pin migration, execution and broader disclosure require separately scoped work.

## Review record

Separate-agent design critique accepted this disabled three-file approach before
configuration was written. Dispositions: keep all four check requirements separate,
list provisioning/private-log effects, preserve no-skip/index/snapshot gaps, use one
actual source-review label without invented independence, and distinguish proposed
staged requirements from historical observations. These are incorporated.

Independent three-file factual/policy/schema/publication review found no blocker.
Dispositions applied: only an absent manifest triggers the private test skip; a
present manifest with missing/invalid score fails. Existing commands and proposed
requirements are distinguished. JSON structure against the pinned public schemas,
references/links, staged-versus-working public bytes and staged whitespace were
checked without importing toolkit or consumer code. No runtime/private gate is
represented as passed. Final exact-byte re-review covers this record too.

Review limits: the native reviewer used public source/diffs and invoked
`git write-tree` once, which may write Git tree-object metadata; staged/working
source content stayed unchanged. This was broader than pure reading and is no
evidence of enforced read-only tools. Final re-review uses source/diff reads only.
