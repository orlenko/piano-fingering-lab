# Experiment rules

This is a public, open-source experiment. Keep personal recordings, purchased scores, source-derived notes, labels, frames, manifests with local paths, and generated videos out of git. Use `.local/` for private inputs and results. Do not copy private consulting documents into this repo.

Read `HANDOFF.md` before implementation. The immediate goal is a best-effort fingering/highlighting video from the supplied materials for a musician to evaluate. Do not make operator-written musical reference labels a prerequisite. Preserve uncertain predictions and distinguish automatic results from manual adjustments.

Prefer local inference in an isolated environment. Python 3.11 with `uv` is the proposed research environment; confirm model/package compatibility before selecting exact dependencies. This is an offline media experiment, with no web app required. Keep model downloads and caches out of git. Never print credentials or upload source media to hosted services without the operator's explicit approval for that action.

Write a concrete design and have a separate agent review it before non-trivial code. Have a separate agent review finished code before push; fix blockers and re-review fixes. Reviews must cover measurement validity and privacy as well as execution. Record decisions and sanitized experiment results durably. Test the processing stages and inspect the resulting media before declaring success.

Use `main` for this early experiment. Push reviewed code and sanitized records before ending the session; preserve unfinished work as a pushed branch if necessary. Only release permission-cleared or synthetic examples publicly. The project license does not grant rights to third-party models, code, datasets, or musical works.


## Manual review procedure

For future work, adopt the shared manual review supplement and centralized role
instructions at source `36b0b858b293e14af726e0adf58af476334ccd5d` through
[the local procedure and capability record](docs/quality-manual-review.md).
This augments the experiment rules above; it does not advance runtime/artifact
pins, activate tooling or attest to historical reviews. Stronger privacy,
measurement, real-index, review and integration obligations remain binding.
