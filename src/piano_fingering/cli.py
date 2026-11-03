"""Offline CLI orchestrator for the local piano fingering proof-of-concept pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable

from .align import AlignedPair, align_performance_to_score
from .assign import assign_fingerings
from .hand_pose import extract_full_rate_hand_poses
from .keyboard import calibrate_and_track_keyboard
from .models import (
    FrameCalibration,
    FramePose,
    HandObservation,
    MeasureTiming,
    PerfNote,
    ScoreMeasure,
    ScoreNote,
)
from .render import (
    apply_manual_overrides,
    export_prediction_tables,
    render_annotated_score,
    render_teaching_video,
)
from .score_pdf import parse_vector_score_pdf
from .transcribe import transcribe_video_audio


CACHED_STAGE_FILES = (
    "transcribed_notes.json", "parsed_score.json", "alignment.json",
    "hand_poses.json", "keyboard_calibration.json",
)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_identity(video: Path, score: Path, device: str) -> dict[str, Any]:
    """Bind cached stages to input bytes, implementation, dependencies and inference device."""
    package_dir = Path(__file__).resolve().parent
    repo_dir = package_dir.parents[1]
    implementation = {p.name: _file_digest(p) for p in sorted(package_dir.glob("*.py"))}
    dependencies = {
        name: _file_digest(repo_dir / name)
        for name in ("pyproject.toml", "uv.lock") if (repo_dir / name).is_file()
    }
    packaged_identity = package_dir / "runtime_identity.json"
    if packaged_identity.is_file():
        dependencies["packaged_runtime"] = _file_digest(packaged_identity)
    return {
        "schema": 1, "video_sha256": _file_digest(video), "score_sha256": _file_digest(score),
        "implementation": implementation, "dependencies": dependencies, "device": device,
    }


def _validate_cached_stages(out_dir: Path, identity: dict[str, Any]) -> None:
    """Reject old, partial or mismatched caches before reading any stage output."""
    try:
        manifest = json.loads((out_dir / "cache_manifest.json").read_text(encoding="utf-8"))
        valid = manifest["identity"] == identity and manifest["outputs"] == {
            name: _file_digest(out_dir / name) for name in CACHED_STAGE_FILES
        }
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise ValueError("Cached stages are incomplete or incompatible. Run without --reuse-cached.")


def _save_cache_manifest(out_dir: Path, identity: dict[str, Any]) -> None:
    manifest = {
        "identity": identity,
        "outputs": {name: _file_digest(out_dir / name) for name in CACHED_STAGE_FILES},
    }
    temporary = out_dir / "cache_manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(out_dir / "cache_manifest.json")


def _resolve_inputs(inputs_json_path: Path) -> tuple[Path, Path]:
    if not inputs_json_path.exists():
        raise FileNotFoundError(
            f"Input manifest not found: {inputs_json_path}. "
            "Create an untracked .local/inputs.json with 'video' and 'score' paths."
        )
    data = json.loads(inputs_json_path.read_text(encoding="utf-8"))
    video_raw = data.get("video") or data.get("video_path") or data.get("performance_video")
    score_raw = data.get("score") or data.get("score_path") or data.get("score_pdf_path")
    if not video_raw or not score_raw:
        raise ValueError("Input manifest must define both 'video' and 'score' file paths.")
    video_p = Path(str(video_raw)).expanduser()
    score_p = Path(str(score_raw)).expanduser()
    if not video_p.exists():
        raise FileNotFoundError("Configured performance video path does not exist.")
    if not score_p.exists():
        raise FileNotFoundError("Configured score PDF path does not exist.")
    return video_p, score_p


def _load_cached_perf_notes(path: Path) -> tuple[list[PerfNote], dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    notes = [PerfNote(**n) for n in raw["notes"]]
    return notes, raw["metadata"]


def _load_cached_score(path: Path) -> tuple[list[ScoreMeasure], list[ScoreNote], dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    measures = [ScoreMeasure(**m) for m in raw["measures"]]
    notes = []
    for n in raw["notes"]:
        n_copy = dict(n)
        n_copy["bbox_pt"] = tuple(n_copy["bbox_pt"])
        notes.append(ScoreNote(**n_copy))
    return measures, notes, raw["metadata"]


def _load_cached_poses(path: Path) -> tuple[list[FramePose], dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    poses = [
        FramePose(
            frame_index=int(f["frame_index"]),
            pts_sec=float(f["pts_sec"]),
            width=int(f["width"]),
            height=int(f["height"]),
            hands=[
                HandObservation(
                    det_index=int(h["det_index"]),
                    detector_chirality=str(h["detector_chirality"]),
                    resolved_hand=str(h["resolved_hand"]),
                    palm_cross=float(h["palm_cross"]),
                    hand_confidence=float(h["hand_confidence"]),
                    landmarks={
                        k: (float(v[0]), float(v[1]), float(v[2])) if v is not None else None
                        for k, v in h["landmarks"].items()
                    },
                )
                for h in f["hands"]
            ],
        )
        for f in raw["frames"]
    ]
    return poses, raw["metadata"]


def _load_cached_calibrations(path: Path) -> tuple[list[FrameCalibration], dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cals = [FrameCalibration(**c) for c in raw["frames"]]
    return cals, raw["metadata"]


def _load_cached_alignment(
    path: Path,
    perf_notes: list[PerfNote],
    score_notes: list[ScoreNote],
) -> tuple[list[AlignedPair], list[MeasureTiming], dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    perf_by_id = {p.perf_event_id: p for p in perf_notes}
    score_by_id = {s.score_note_id: s for s in score_notes}
    timings = [MeasureTiming(**mt) for mt in raw["measure_timings"]]
    pairs: list[AlignedPair] = []
    for pr in raw["pairs"]:
        pid = pr.get("perf_event_id")
        sid = pr.get("score_note_id")
        pairs.append(
            AlignedPair(
                alignment_status=str(pr["alignment_status"]),
                perf_note=perf_by_id.get(pid) if pid else None,
                score_note=score_by_id.get(sid) if sid else None,
                expected_time_sec=pr.get("expected_time_sec"),
                timing_residual_sec=pr.get("timing_residual_sec"),
            )
        )
    return pairs, timings, raw["metadata"]


def run_pipeline(
    inputs_path: Path,
    out_dir: Path,
    cache_dir: Path,
    overrides_path: Path | None,
    reuse_cached: bool = False,
    device: str = "cpu",
    rotate_hands_180: bool = True,
    hand_pose_helper: Path | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Execute Stages 1-7 locally and write all artifacts into out_dir."""
    t_total = time.perf_counter()
    video_path, score_pdf_path = _resolve_inputs(inputs_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    diag_dir = out_dir / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)
    cache_identity = _cache_identity(video_path, score_pdf_path, device)
    if reuse_cached:
        _validate_cached_stages(out_dir, cache_identity)
    else:
        # An interrupted fresh run must never authorize a mixture of old and new stages.
        (out_dir / "cache_manifest.json").unlink(missing_ok=True)

    # Stage 1: Audio transcription
    if progress:
        progress(1, "Listening to the recording")
    p_trans = out_dir / "transcribed_notes.json"
    if reuse_cached and p_trans.exists():
        print("[Stage 1/7] Reusing cached audio transcription...")
        perf_notes, meta_trans = _load_cached_perf_notes(p_trans)
    else:
        print("[Stage 1/7] Transcribing performance audio locally (Transkun 2.0)...")
        perf_notes, meta_trans = transcribe_video_audio(
            video_path=video_path,
            out_json_path=p_trans,
            device=device,
        )

    # Stage 2: Vector score PDF extraction
    if progress:
        progress(2, "Reading the score")
    p_score = out_dir / "parsed_score.json"
    if reuse_cached and p_score.exists():
        print("[Stage 2/7] Reusing cached vector score parse...")
        measures, score_notes, meta_score = _load_cached_score(p_score)
    else:
        print("[Stage 2/7] Parsing vector score PDF geometry & notation...")
        measures, score_notes, meta_score = parse_vector_score_pdf(
            pdf_path=score_pdf_path,
            out_json_path=p_score,
            diagnostics_dir=diag_dir,
        )

    # Stage 3: Subsequence excerpt alignment & measure timing
    if progress:
        progress(3, "Finding where you played in the score")
    p_align = out_dir / "alignment.json"
    if reuse_cached and p_align.exists():
        print("[Stage 3/7] Reusing cached audio-to-score subsequence alignment...")
        aligned_pairs, measure_timings, meta_align = _load_cached_alignment(
            p_align, perf_notes, score_notes
        )
    else:
        print("[Stage 3/7] Aligning transcribed performance subsequence to score...")
        aligned_pairs, measure_timings, meta_align = align_performance_to_score(
            perf_notes=perf_notes,
            measures=measures,
            score_notes=score_notes,
            out_json_path=p_align,
        )

    # Stage 5 (run prior to Stage 4 to provide hand exclusion masks during keyboard tracking)
    if progress:
        progress(4, "Following your hands")
    p_poses = out_dir / "hand_poses.json"
    if reuse_cached and p_poses.exists():
        print("[Stage 4/7] Reusing cached full-rate two-hand pose landmarks...")
        frame_poses, meta_poses = _load_cached_poses(p_poses)
    else:
        print("[Stage 4/7] Extracting full-rate two-hand poses (Apple Vision)...")
        frame_poses, meta_poses = extract_full_rate_hand_poses(
            video_path=video_path,
            out_json_path=p_poses,
            cache_dir=cache_dir,
            helper_path=hand_pose_helper,
        )

    # Stage 4: Dual-plane keyboard calibration & backward/forward camera tracking
    if progress:
        progress(5, "Locating the keyboard")
    p_cal = out_dir / "keyboard_calibration.json"
    if reuse_cached and p_cal.exists():
        print("[Stage 5/7] Reusing cached dual-plane keyboard calibration...")
        frame_calibrations, meta_cal = _load_cached_calibrations(p_cal)
    else:
        print("[Stage 5/7] Calibrating dual-plane 88-key homographies & tracking camera...")
        frame_calibrations, meta_cal = calibrate_and_track_keyboard(
            video_path=video_path,
            frame_poses=frame_poses,
            out_json_path=p_cal,
            diagnostics_dir=diag_dir,
        )

    if not reuse_cached:
        _save_cache_manifest(out_dir, cache_identity)

    # Stage 6: Attack-window dual-plane candidate scoring & order-constrained chord DP
    if progress:
        progress(6, "Estimating fingerings")
    print("[Stage 6/7] Solving attack-window dual-plane finger assignments...")
    p_pred_json = out_dir / "predictions.json"
    predictions, meta_assign = assign_fingerings(
        aligned_pairs=aligned_pairs,
        frame_poses=frame_poses,
        frame_calibrations=frame_calibrations,
        out_json_path=None,
        alignment_ambiguous=bool(meta_align.get("alignment_ambiguous", False)),
    )

    # Stage 7: Non-destructive manual overrides + CSV/JSON + PDF/PNG + VFR split-screen MP4
    if progress:
        progress(7, "Preparing the video and score")
    print("[Stage 7/7] Applying overrides (if any) and rendering PDF/PNG/CSV/MP4 deliverables...")
    override_counts = apply_manual_overrides(
        predictions=predictions,
        measure_timings=measure_timings,
        overrides_path=overrides_path,
    )
    total_manual = override_counts["finger_overrides"] + override_counts["measure_timing_overrides"]

    p_pred_csv = out_dir / "predictions.csv"
    export_meta = {
        **meta_assign,
        "manual_overrides": override_counts,
        "matched_measure_range": meta_align.get("matched_measure_range"),
        "alignment_ambiguous": meta_align.get("alignment_ambiguous", False),
        "measure_timings": [mt.to_dict() for mt in measure_timings],
    }
    export_prediction_tables(
        predictions=predictions,
        csv_path=p_pred_csv,
        json_path=p_pred_json,
        summary_meta=export_meta,
    )

    p_ann_pdf = out_dir / "annotated_score.pdf"
    p_ann_png = out_dir / "annotated_excerpt.png"
    meta_score_render = render_annotated_score(
        score_pdf_path=score_pdf_path,
        measures=measures,
        score_notes=score_notes,
        predictions=predictions,
        measure_timings=measure_timings,
        out_pdf_path=p_ann_pdf,
        out_excerpt_png_path=p_ann_png,
        manual_override_count=total_manual,
        alignment_ambiguous=bool(meta_align.get("alignment_ambiguous", False)),
    )

    p_video_out = out_dir / "teaching_video.mp4"
    meta_video_render = render_teaching_video(
        video_path=video_path,
        annotated_pdf_path=p_ann_pdf,
        measures=measures,
        score_notes=score_notes,
        predictions=predictions,
        measure_timings=measure_timings,
        frame_poses=frame_poses,
        frame_calibrations=frame_calibrations,
        out_mp4_path=p_video_out,
        temp_dir=cache_dir,
        manual_override_count=total_manual,
        rotate_hands_180_to_pianist_pov=rotate_hands_180,
        alignment_ambiguous=bool(meta_align.get("alignment_ambiguous", False)),
    )

    # Build strictly sanitized aggregate summary (zero local paths, filenames, titles, or pitch lists)
    sanitized_summary: dict[str, Any] = {
        "pipeline_runtime_sec": round(time.perf_counter() - t_total, 3),
        "transcription": {
            "model": meta_trans.get("model"),
            "note_count": meta_trans.get("note_count"),
            "pedal_cc_event_count": meta_trans.get("pedal_cc_event_count"),
            "onset_range_sec": meta_trans.get("onset_range_sec"),
            "audio_minus_video_offset_sec": round(
                float(meta_trans.get("clock", {}).get("audio_minus_video_offset_sec", 0.0)), 6
            ),
            "video_frame_count": int(meta_trans.get("clock", {}).get("video_frame_count", 0)),
        },
        "score_parse": {
            "measure_count": meta_score.get("measure_count"),
            "total_notehead_count": meta_score.get("total_notehead_count"),
            "attack_note_count": meta_score.get("attack_note_count"),
            "tied_continuation_count": meta_score.get("tied_continuation_count"),
            "arpeggiated_note_count": meta_score.get("arpeggiated_note_count"),
            "printed_measure_anchor_matches": (
                f"{meta_score.get('printed_measure_anchor_matches')}/"
                f"{meta_score.get('printed_measure_anchor_checks')}"
            ),
            "staff_measure_beat_consistent": (
                f"{meta_score.get('staff_measure_beat_consistent')}/"
                f"{meta_score.get('staff_measure_beat_checks')}"
            ),
        },
        "alignment": {
            "alignment_ambiguous": meta_align.get("alignment_ambiguous"),
            "ambiguity_comparison_available": meta_align.get("ambiguity_comparison_available"),
            "matched_measure_range": meta_align.get("matched_measure_range"),
            "matched_page_indices": meta_align.get("matched_page_indices"),
            "played_time_window_sec": (
                [measure_timings[0].t_start_sec, measure_timings[-1].t_end_sec]
                if measure_timings
                else None
            ),
            "estimated_tempo_bpm": meta_align.get("estimated_tempo_bpm"),
            "top1_to_top2_ratio": meta_align.get("top1_to_top2_ratio"),
            "excerpt_score_attack_count": meta_align.get("excerpt_score_attack_count"),
            "matched_note_count": meta_align.get("matched_note_count"),
            "unmatched_score_note_count": meta_align.get("unmatched_score_note_count"),
            "unmatched_perf_note_count": meta_align.get("unmatched_perf_note_count"),
            "score_recall_in_excerpt": meta_align.get("score_recall_in_excerpt"),
            "median_abs_timing_residual_sec": meta_align.get("median_abs_timing_residual_sec"),
            "p95_abs_timing_residual_sec": meta_align.get("p95_abs_timing_residual_sec"),
        },
        "hand_pose": {
            "backend": meta_poses.get("backend"),
            "frame_count": meta_poses.get("frame_count"),
            "two_hand_frames": meta_poses.get("two_hand_frames"),
            "one_hand_frames": meta_poses.get("one_hand_frames"),
            "zero_hand_frames": meta_poses.get("zero_hand_frames"),
            "palm_cross_agreement_rate": meta_poses.get("palm_cross_agreement_rate"),
            "ambiguous_hand_instances": meta_poses.get("ambiguous_hand_instances"),
        },
        "keyboard_calibration": {
            "reference_frame_index": meta_cal.get("reference_frame_index"),
            "reference_frame_pts_sec": meta_cal.get("reference_frame_pts_sec"),
            "reliable_calibrated_frames": meta_cal.get("reliable_calibrated_frames"),
            "total_frames": meta_cal.get("total_frames"),
            "reliable_frame_ratio": meta_cal.get("reliable_frame_ratio"),
            "median_residual_kw": meta_cal.get("median_residual_kw"),
            "p95_residual_kw": meta_cal.get("p95_residual_kw"),
        },
        "fingering_assignment": meta_assign,
        "manual_overrides": override_counts,
        "rendering": {
            "placed_score_label_count": meta_score_render.get("placed_score_label_count"),
            "encoded_frame_count": meta_video_render.get("encoded_frame_count"),
            "muxed_frame_count": meta_video_render.get("muxed_frame_count"),
            "max_vfr_pts_error_ms": meta_video_render.get("max_vfr_pts_error_ms"),
            "av_offset_error_ms": meta_video_render.get("av_offset_error_ms"),
        },
    }

    (out_dir / "sanitized_summary.json").write_text(
        json.dumps(sanitized_summary, indent=2),
        encoding="utf-8",
    )
    print("[Done] Sanitized pipeline summary:")
    print(json.dumps(sanitized_summary, indent=2))
    return sanitized_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="piano-fingering",
        description="Local offline observed piano fingering & score-highlighting pipeline.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["run"],
        default="run",
        help="Optional subcommand ('run', default when omitted).",
    )
    parser.add_argument(
        "--inputs",
        type=Path,
        default=Path(".local/inputs.json"),
        help="Path to untracked JSON manifest defining 'video' and 'score' paths.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(".local/out"),
        help="Output directory for generated media and prediction tables.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".local/cache"),
        help="Local cache directory for temporary helper binaries and streams.",
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        default=Path(".local/overrides.json"),
        help="Optional non-destructive manual overrides JSON file.",
    )
    parser.add_argument(
        "--reuse-cached",
        action="store_true",
        help="Reuse existing Stage 1-5 JSON outputs in --out-dir when available.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        help="PyTorch device for local audio transcription (default: cpu).",
    )
    parser.add_argument(
        "--raw-camera-orientation",
        action="store_true",
        help="Keep raw camera orientation in left video pane instead of 180-deg Pianist POV.",
    )
    args = parser.parse_args(argv)

    run_pipeline(
        inputs_path=args.inputs,
        out_dir=args.out_dir,
        cache_dir=args.cache_dir,
        overrides_path=args.overrides,
        reuse_cached=args.reuse_cached,
        device=args.device,
        rotate_hands_180=not args.raw_camera_orientation,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
