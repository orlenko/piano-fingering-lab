"""Synthetic regressions for failures identified during independent review."""

from fractions import Fraction
import json

import av
import numpy as np
import pytest

from piano_fingering.cli import (
    CACHED_STAGE_FILES, _cache_identity, _save_cache_manifest, _validate_cached_stages,
)
from piano_fingering.models import MeasureTiming
from piano_fingering.render import _validate_output_timing, apply_manual_overrides


def test_cache_rejects_changed_inputs_partial_and_modified_stage_outputs(tmp_path):
    video, score = tmp_path / "source.bin", tmp_path / "score.bin"
    video.write_bytes(b"synthetic video")
    score.write_bytes(b"synthetic score")
    identity = _cache_identity(video, score, "cpu")
    with pytest.raises(ValueError, match="incompatible"):
        _validate_cached_stages(tmp_path, identity)
    for name in CACHED_STAGE_FILES:
        (tmp_path / name).write_text("{}")
    _save_cache_manifest(tmp_path, identity)
    _validate_cached_stages(tmp_path, identity)
    video.write_bytes(b"another video")
    with pytest.raises(ValueError, match="incompatible"):
        _validate_cached_stages(tmp_path, _cache_identity(video, score, "cpu"))
    changed_code = {**identity, "implementation": {"changed": "digest"}}
    with pytest.raises(ValueError, match="incompatible"):
        _validate_cached_stages(tmp_path, changed_code)
    (tmp_path / CACHED_STAGE_FILES[0]).write_text('{"changed":true}')
    with pytest.raises(ValueError, match="incompatible"):
        _validate_cached_stages(tmp_path, identity)
    (tmp_path / CACHED_STAGE_FILES[0]).unlink()
    with pytest.raises(ValueError, match="incompatible"):
        _validate_cached_stages(tmp_path, identity)


def test_timing_gate_on_decoded_synthetic_vfr_video(tmp_path):
    media = tmp_path / "synthetic.mp4"
    source_pts = [0.0, 0.04, 0.09, 0.12]
    with av.open(str(media), "w") as container:
        stream = container.add_stream("libx264", rate=25)
        stream.width, stream.height = 64, 48
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 1000)
        stream.codec_context.time_base = Fraction(1, 1000)
        for t in source_pts:
            frame = av.VideoFrame.from_ndarray(np.zeros((48, 64, 3), dtype=np.uint8), format="rgb24")
            frame.pts, frame.time_base = round(t * 1000), Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    with av.open(str(media)) as container:
        decoded = [float(f.pts * f.time_base) for f in container.decode(video=0)]
    assert _validate_output_timing(source_pts, decoded, 0.0) < 1.0
    with pytest.raises(RuntimeError, match="frame count"):
        _validate_output_timing(source_pts, decoded[:-1], 0.0)
    with pytest.raises(RuntimeError, match="timestamps"):
        _validate_output_timing(source_pts, [t + 0.01 for t in decoded], 0.0)
    with pytest.raises(RuntimeError, match="clock offset"):
        _validate_output_timing(source_pts, decoded, 6.0)


@pytest.mark.parametrize("entry", [
    {"t_start_sec": float("nan")}, {"t_end_sec": 0.5}, {"t_end_sec": 4.0},
])
def test_reject_invalid_or_overlapping_manual_timings(tmp_path, entry):
    timings = [MeasureTiming(1, 0, 0, 1.0, 2.0, 1), MeasureTiming(2, 0, 0, 2.0, 3.0, 1)]
    sidecar = tmp_path / "overrides.json"
    sidecar.write_text(json.dumps({"measure_timing_overrides": {"1": entry}}))
    with pytest.raises(ValueError, match="timings must be finite"):
        apply_manual_overrides([], timings, sidecar)


def test_manual_timing_preserves_automatic_intervals(tmp_path):
    timings = [MeasureTiming(1, 0, 0, 1.0, 2.0, 1)]
    sidecar = tmp_path / "overrides.json"
    sidecar.write_text(json.dumps({"measure_timing_overrides": {"1": {"t_start_sec": 1.1}}}))
    apply_manual_overrides([], timings, sidecar)
    assert timings[0].auto_t_start_sec == 1.0
    assert timings[0].auto_t_end_sec == 2.0
    assert timings[0].t_start_sec == 1.1
    assert timings[0].provenance == "manual_override"


def test_reference_pattern_fit_cannot_fall_back_to_identity(monkeypatch):
    from piano_fingering import keyboard

    # Synthetic bright white apron and periodic black-key strip; no source imagery.
    image = np.full((500, 1920, 3), 240, dtype=np.uint8)
    image[:, 1800:] = 0
    strip = np.full((400, 2000), 240.0, dtype=np.float32)
    for x in range(30, 1900, 70):
        strip[30:220, x:x+22] = 10
    monkeypatch.setattr(keyboard, "_detect_red_felt_and_white_front_lines", lambda _: ((0, 100), (0, 300), 50))
    monkeypatch.setattr(keyboard.cv2, "warpPerspective", lambda *a, **kw: strip)
    monkeypatch.setattr(keyboard, "_fit_1d_projective", lambda *a: np.array([np.nan] * 3))
    with pytest.raises(RuntimeError, match="No accepted reference key-pattern fit"):
        keyboard._calibrate_unoccluded_reference(image)


def test_repeated_excerpt_flags_ambiguity_and_preserves_candidate_abstention(monkeypatch):
    from piano_fingering.align import AlignedPair, align_performance_to_score
    from piano_fingering import assign
    from piano_fingering.models import CandidateFinger, PerfNote, ScoreMeasure, ScoreNote

    measures, notes = [], []
    for m in (1, 2):
        measures.append(ScoreMeasure(m, 0, 0, 20, 20, 200, 100, 20, 40, 80, 100, 5, 4, 4))
        for beat, pitch in enumerate((60, 64, 67, 72), 1):
            notes.append(ScoreNote(f"s{m}_{beat}", 0, 0, m, beat, 1, "treble", 1,
                                   pitch, "synthetic", 40 + beat * 20, 30, (35, 25, 45, 35), f"c{m}_{beat}"))
    perf = [PerfNote(f"p{i}", 1.0 + i * 0.7, 1.3 + i * 0.7, p, 80)
            for i, p in enumerate((60, 64, 67, 72))]
    _, _, metadata = align_performance_to_score(perf, measures, notes)
    assert metadata["alignment_ambiguous"] is True
    candidate = CandidateFinger("R", 1, 0.05, 0.02, 0.5, 0, 0.95, 4)
    monkeypatch.setattr(assign, "score_candidates_for_attack", lambda **kw: ([candidate], None, [1.0], 0.02))
    pair = AlignedPair("matched", perf[0], notes[0], 1.0, 0.0)
    records, summary = assign.assign_fingerings([pair], [], [], alignment_ambiguous=True)
    assert records[0].auto_finger == "unknown"
    assert records[0].abstain_reason == "ambiguous_score_alignment"
    assert records[0].candidate_fingers == [candidate]
    assert summary["emitted_predictions_total"] == 0
