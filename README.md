# piano-fingering-lab

Local-first offline experiments extracting **observed** piano fingerings (`L`/`R`, fingers `1..5`) from overhead/angled performance video and synchronizing them with a vector sheet-music PDF.

## Scope & Principles

- **Observed, not theoretical, fingering**: Finger labels estimate the pianist's choice from fingertip geometry near audio attacks. The high/low tiers are heuristic support levels, not calibrated correctness probabilities or proof of key contact.
- **Honest uncertainty**: Occluded, off-camera, unaligned, or ambiguous attacks abstain explicitly (`unknown` / `?`) with machine-readable reasons rather than guessing.
- **Non-destructive provenance**: Automatic predictions (`provenance="auto"`) are preserved alongside any optional `.local/overrides.json` adjustments (`provenance="manual_override"`).
- **Privacy & local inference**: All private inputs, caches, diagnostic frames, and generated media live under `.local/` (gitignored). No media is uploaded to hosted services by the pipeline.

Development review used local image tools that placed private rendered diagnostics into the implementation and review assistants' multimodal contexts. That inspection was separate from offline pipeline execution and was not local-model-only review. Explicit approval for hosted image disclosure is not established in the available record; local file storage and git exclusion do not establish such approval. See [review provenance](docs/review.md). Further hosted private-image inspection requires explicit operator approval.

See [HANDOFF.md](HANDOFF.md) for the proof-of-concept specification, [AGENTS.md](AGENTS.md) for experiment rules, [docs/design.md](docs/design.md) for the reviewed system architecture, and [docs/experiment-log.md](docs/experiment-log.md) for sanitized aggregate experiment results.

## Mac desktop alpha

Fingering Studio adds a native drop area, portable projects, video/PDF review,
per-note corrections, media updates and atomic export. It bundles the local
runtime and model; no API key or recipient development setup is needed.
See [desktop build, use and limits](docs/desktop.md), the
[reviewed implementation plan](docs/desktop-plan.md), and [validation record](docs/experiment-log.md).
The initial internal build targets Apple Silicon/macOS 14+, with ad-hoc signing;
second-Mac qualification, Developer ID/notarization and public binary
redistribution clearance remain outstanding.

## Environment Setup

Requires macOS (for Apple `Vision` hand-pose extraction via `swiftc`) and Python 3.11 managed with [`uv`](https://docs.astral.sh/uv/):

```sh
uv sync --extra dev
```

## Input Manifest (`.local/inputs.json`)

Create an untracked `.local/inputs.json` pointing to a local performance video (with audio) and a vector score PDF (the proof-of-concept PDF parser currently targets `Doremi`-engraved 5-line grand-staff vector PDFs; SMuFL/Bravura and scanned raster PDFs are outside this initial scope):

```json
{
  "video": "path/to/local/performance_video.mp4",
  "score": "path/to/local/vector_score.pdf"
}
```

Optional non-destructive manual overrides can be placed in `.local/overrides.json`:

```json
{
  "finger_overrides": {
    "sn_0012": { "hand": "R", "finger": "2" }
  },
  "measure_timing_overrides": {
    "4": { "t_start_sec": 6.10, "t_end_sec": 8.05 }
  }
}
```

## Running the Pipeline

Run all seven stages offline and generate deliverables in `.local/out/`:

```sh
MPLCONFIGDIR="$PWD/.local/cache/mpl" XDG_CACHE_HOME="$PWD/.local/cache" uv run piano-fingering
```

During iterative rendering development, complete Stage 1–5 caches can be reused with `--reuse-cached` when input, code, dependency and output hashes match. Old, partial or mismatched caches fail with instructions to run without that flag:

```sh
MPLCONFIGDIR="$PWD/.local/cache/mpl" XDG_CACHE_HOME="$PWD/.local/cache" uv run piano-fingering --reuse-cached
```

### Generated Local Deliverables (`.local/out/`)

- `teaching_video.mp4`: `1920x1080` VFR-faithful split-screen video (180°-rotated Pianist-POV hands with upright attack badges on the left, measure-highlighted annotated score on the right, muxed with original audio).
- `annotated_score.pdf` & `annotated_excerpt.png`: Vector PDF overlay and high-DPI cropped excerpt image with confidence-tiered finger labels (`n` likely auto, `(n?)` uncertain auto, `?` unknown, `n*` manual override); unplayed measures are left blank.
- `predictions.csv` & `predictions.json`: Per-event review table with candidate diagnostics, abstention reasons, provenance, and blank `musician_verdict`, `musician_corrected_finger`, and `musician_notes` columns for pianist evaluation.
- `sanitized_summary.json`: Aggregate stage metrics stripped of local paths and source-derived musical content.

## Testing & Privacy Verification

Run the synthetic unit test suite and the two-tier repository privacy guard:

```sh
MPLCONFIGDIR="$PWD/.local/cache/mpl" XDG_CACHE_HOME="$PWD/.local/cache" uv run pytest -v
```

## License Note

The current geometry route requires a visible bass cheek block in a hand-free reference frame and this camera orientation; unsupported calibration fails explicitly. The elevated black-key mapping uses a fixed reference correction during camera movement and remains approximate. Local score parsing and alignment are heuristics for this input format. Alignment residuals are in-sample fit diagnostics; no musician ground truth has been supplied.

Repository code is MIT-licensed ([LICENSE](LICENSE)). The project license does not grant rights to third-party models, packages, datasets, or copyrighted musical works. Do not commit recordings, purchased scores, checkpoints, or source-derived media.
