"""Synthetic unit tests for chirality, order-constrained chord DP, and subsequence alignment."""

from __future__ import annotations

import math

from piano_fingering.align import align_performance_to_score
from piano_fingering.assign import (
    ORDERED_FINGERS,
    solve_order_constrained_cluster,
)
from piano_fingering.hand_pose import compute_dorsal_palm_cross, resolve_hand_chirality
from piano_fingering.models import (
    CandidateFinger,
    PerfNote,
    ScoreMeasure,
    ScoreNote,
    midi_to_canonical_u_center,
    midi_to_name,
)


def _rotate_2d(pt: tuple[float, float], angle_rad: float, cx: float = 500.0, cy: float = 500.0) -> tuple[float, float, float]:
    dx, dy = pt[0] - cx, pt[1] - cy
    rx = cx + dx * math.cos(angle_rad) - dy * math.sin(angle_rad)
    ry = cy + dx * math.sin(angle_rad) + dy * math.cos(angle_rad)
    return (rx, ry, 0.95)


def test_dorsal_palm_cross_rotation_and_thumb_crossing_invariance() -> None:
    # Canonical pianist-POV (+x right, +y down, fingers pointing UP toward -y):
    # Right hand: wrist at (500, 600), middle_mcp at (500, 500), index_mcp on left (470, 505), little_mcp on right (535, 510)
    base_right = {
        "wrist": (500.0, 600.0),
        "middle_mcp": (500.0, 500.0),
        "index_mcp": (470.0, 505.0),
        "little_mcp": (535.0, 510.0),
        # Even if thumb crosses FAR right past index/middle under palm, MCP arch is unchanged:
        "thumb_tip": (525.0, 480.0),
    }
    # Left hand: mirrored across x=500 -> index_mcp on right (530, 505), little_mcp on left (465, 510)
    base_left = {
        "wrist": (500.0, 600.0),
        "middle_mcp": (500.0, 500.0),
        "index_mcp": (530.0, 505.0),
        "little_mcp": (465.0, 510.0),
    }

    # Test across 0 deg (pianist POV), 180 deg (behind-music-desk view), and +-25 deg diagonal camera tilt
    for deg in (0.0, 180.0, 25.0, -155.0, 90.0):
        rad = math.radians(deg)
        lm_r = {k: _rotate_2d(v, rad) for k, v in base_right.items()}
        lm_l = {k: _rotate_2d(v, rad) for k, v in base_left.items()}

        raw_r, norm_r = compute_dorsal_palm_cross(lm_r)
        raw_l, norm_l = compute_dorsal_palm_cross(lm_l)

        assert raw_r > 0 and norm_r > 0.5, f"Right hand failed at {deg} deg: {norm_r}"
        assert raw_l < 0 and norm_l < -0.5, f"Left hand failed at {deg} deg: {norm_l}"
        assert resolve_hand_chirality("R", norm_r) == "R"
        assert resolve_hand_chirality("L", norm_l) == "L"


def _cand(hand: str, finger: int, cost: float) -> CandidateFinger:
    return CandidateFinger(
        hand=hand,
        finger=finger,
        cost=cost,
        delta_u_kw=cost,
        v_norm=0.5,
        slip_kw_per_s=0.0,
        mean_tip_conf=0.9,
        supporting_frames=4,
    )


def test_order_constrained_dp_enforces_monotonicity_and_mutual_exclusion() -> None:
    # 2nd-interval cluster: Bb3 (58), C4 (60), E4 (64).
    # Suppose R2 has slightly lowest unary cost on BOTH Bb3 and C4 (classic greedy duplicate-finger trap),
    # and R3 is slightly closer to Bb3 than C4 if unconstrained (crossing trap).
    pitches = [58, 60, 64]
    cands = [
        [_cand("R", 2, 0.15), _cand("R", 1, 0.22), _cand("R", 3, 0.20)],  # Bb3
        [_cand("R", 2, 0.14), _cand("R", 1, 0.45), _cand("R", 3, 0.35)],  # C4
        [_cand("R", 4, 0.18), _cand("R", 5, 0.25)],                       # E4
    ]
    total_cost, choices = solve_order_constrained_cluster(pitches, cands)
    picked = [ORDERED_FINGERS[c] if c is not None else None for c in choices]
    # Optimal monotonic non-duplicate assignment must be R1 (0.22) < R2 (0.14) < R4 (0.18)
    assert picked == [("R", 1), ("R", 2), ("R", 4)]
    assert abs(total_cost - (0.22 + 0.14 + 0.18)) < 1e-6


def test_order_constrained_dp_allows_partial_chord_abstention() -> None:
    # 4-note chord where the 3rd note is occluded (empty candidate list):
    # Should emit R1, R2, None (?), R5 rather than failing the whole chord.
    pitches = [58, 62, 65, 70]
    cands = [
        [_cand("R", 1, 0.12)],
        [_cand("R", 2, 0.16)],
        [],  # occluded inner chord tone
        [_cand("R", 5, 0.15)],
    ]
    _cost, choices = solve_order_constrained_cluster(pitches, cands)
    picked = [ORDERED_FINGERS[c] if c is not None else None for c in choices]
    assert picked == [("R", 1), ("R", 2), None, ("R", 5)]


def test_subsequence_alignment_disambiguates_meter_and_octave_without_stretching() -> None:
    # Build synthetic 6-measure score:
    # mm. 1-2: 3/4 time (pitches 60, 64, 67)
    # mm. 3-4: 4/4 time (pitches 60, 64, 67, 72 + bass 48) -> target excerpt!
    # mm. 5-6: 4/4 time shifted +12 semitones higher (72, 76, 79, 84 + bass 60)
    measures: list[ScoreMeasure] = []
    notes: list[ScoreNote] = []

    for m_num in range(1, 7):
        bpb = 3 if m_num <= 2 else 4
        measures.append(
            ScoreMeasure(
                measure=m_num,
                page_index=1,
                system_index=(m_num - 1) // 2,
                x0_pt=50.0,
                y0_pt=50.0,
                x1_pt=250.0,
                y1_pt=120.0,
                treble_top_pt=60.0,
                treble_bot_pt=80.0,
                bass_top_pt=100.0,
                bass_bot_pt=120.0,
                staff_space_pt=5.0,
                beats_per_bar=bpb,
                beat_unit=4,
            )
        )
        shift = 12 if m_num >= 5 else 0
        mel = [60 + shift, 64 + shift, 67 + shift] + ([72 + shift] if bpb == 4 else [])
        for b_i, mp in enumerate(mel):
            notes.append(
                ScoreNote(
                    score_note_id=f"m{m_num}_t_{b_i}",
                    page_index=1,
                    system_index=(m_num - 1) // 2,
                    measure=m_num,
                    beat=float(b_i + 1),
                    duration_beats=1.0,
                    staff="treble",
                    voice=1,
                    midi_pitch=mp,
                    pitch_name=midi_to_name(mp),
                    x_pt=70.0 + b_i * 35.0,
                    y_pt=70.0,
                    bbox_pt=(68.0, 68.0, 73.0, 73.0),
                    chord_group_id=f"m{m_num}_c{b_i}",
                )
            )
        if bpb == 4:
            notes.append(
                ScoreNote(
                    score_note_id=f"m{m_num}_b_0",
                    page_index=1,
                    system_index=(m_num - 1) // 2,
                    measure=m_num,
                    beat=1.0,
                    duration_beats=4.0,
                    staff="bass",
                    voice=1,
                    midi_pitch=48 + shift,
                    pitch_name=midi_to_name(48 + shift),
                    x_pt=70.0,
                    y_pt=110.0,
                    bbox_pt=(68.0, 108.0, 73.0, 113.0),
                    chord_group_id=f"m{m_num}_b0",
                )
            )

    # Simulate performance playing ONLY mm. 3-4 at 0.70 s/beat starting at t = 1.5s
    perf: list[PerfNote] = []
    p_idx = 0
    for m_off in (0, 1):
        t_bar = 1.5 + m_off * 4 * 0.70
        perf.append(PerfNote(f"p{p_idx}", t_bar, t_bar + 2.5, 48, 70))
        p_idx += 1
        for b_i, mp in enumerate([60, 64, 67, 72]):
            t_on = t_bar + b_i * 0.70
            perf.append(PerfNote(f"p{p_idx}", t_on, t_on + 0.6, mp, 75))
            p_idx += 1

    pairs, timings, meta = align_performance_to_score(perf, measures, notes)
    assert meta["matched_measure_range"] == [3, 4]
    assert meta["matched_note_count"] == 10
    assert meta["top1_minus_top2_margin"] > 3.0
    assert len(timings) == 2


def test_canonical_u_monotonic_across_88_keys() -> None:
    us = [midi_to_canonical_u_center(p) for p in range(21, 109)]
    assert all(us[i] < us[i + 1] for i in range(len(us) - 1))
    assert 0.0 < us[0] < 1.0
    assert 51.0 < us[-1] < 52.0


def test_homography_step_consistency_rejects_octave_jumps() -> None:
    import numpy as np

    from piano_fingering.keyboard import _is_homography_step_consistent

    # Behind-music-desk linear mapping: x in [100..1820] -> u in [38..2], y in [340..540] -> v in [1..0]
    # u = -0.0209 * x + 40.09, v = -0.005 * y + 2.70
    h_prev = np.array(
        [
            [-0.0209, 0.0, 40.09],
            [0.0, -0.005, 2.70],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )

    # Smooth inter-frame pan (+0.55 white keys) -> must pass
    shift_ok = np.array([[1.0, 0.0, 0.55], [0.0, 1.0, 0.02], [0.0, 0.0, 1.0]], dtype=np.float64)
    assert _is_homography_step_consistent(shift_ok @ h_prev, h_prev, 1920, 1080) is True

    # 1-octave (-7.0 kw) and 2-octave (-14.0 kw) periodic slips -> must reject
    for oct_slip in (-7.0, 7.0, -14.0):
        shift_bad = np.array([[1.0, 0.0, oct_slip], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
        assert _is_homography_step_consistent(shift_bad @ h_prev, h_prev, 1920, 1080) is False


def test_manual_overrides_are_non_destructive_and_render_synthetic_pdf(tmp_path) -> None:
    import csv
    import json

    from reportlab.pdfgen import canvas

    from piano_fingering.models import MeasureTiming, PredictionRecord
    from piano_fingering.render import (
        apply_manual_overrides,
        export_prediction_tables,
        render_annotated_score,
    )

    # Create synthetic 2-page PDF (page 0 cover/unplayed, page 1 played)
    synth_pdf = tmp_path / "synthetic_score.pdf"
    c = canvas.Canvas(str(synth_pdf), pagesize=(612.0, 792.0))
    c.drawString(72.0, 720.0, "Synthetic Cover Page")
    c.showPage()
    c.line(60.0, 600.0, 300.0, 600.0)
    c.showPage()
    c.save()

    measures = [
        ScoreMeasure(
            measure=1,
            page_index=1,
            system_index=0,
            x0_pt=60.0,
            y0_pt=180.0,
            x1_pt=300.0,
            y1_pt=260.0,
            treble_top_pt=180.0,
            treble_bot_pt=200.0,
            bass_top_pt=240.0,
            bass_bot_pt=260.0,
            staff_space_pt=5.0,
            beats_per_bar=4,
            beat_unit=4,
        )
    ]
    notes = [
        ScoreNote(
            score_note_id="sn_1",
            page_index=1,
            system_index=0,
            measure=1,
            beat=1.0,
            duration_beats=1.0,
            staff="treble",
            voice=1,
            midi_pitch=60,
            pitch_name="C4",
            x_pt=100.0,
            y_pt=205.0,
            bbox_pt=(97.0, 202.0, 103.0, 208.0),
            chord_group_id="cg_1",
        )
    ]
    timings = [
        MeasureTiming(
            measure=1,
            page_index=1,
            system_index=0,
            t_start_sec=1.0,
            t_end_sec=3.0,
            matched_note_count=1,
        )
    ]
    preds = [
        PredictionRecord(
            event_id="ev_0000",
            alignment_status="matched",
            perf_event_id="perf_0000",
            score_note_id="sn_1",
            onset_sec=1.02,
            offset_sec=1.60,
            midi_pitch=60,
            pitch_name="C4",
            page_index=1,
            measure=1,
            beat=1.0,
            staff="treble",
            chord_group_id="cg_1",
            auto_hand="R",
            auto_finger="1",
            auto_confidence_tier="high",
            cost_margin=0.42,
            abstain_reason=None,
            final_hand="R",
            final_finger="1",
            final_confidence_tier="high",
            provenance="auto",
        )
    ]

    ov_file = tmp_path / "overrides.json"
    ov_file.write_text(json.dumps({"finger_overrides": {"sn_1": {"hand": "R", "finger": "2"}}}))
    counts = apply_manual_overrides(preds, timings, ov_file)
    assert counts["finger_overrides"] == 1
    assert preds[0].auto_finger == "1"
    assert preds[0].auto_confidence_tier == "high"
    assert preds[0].final_finger == "2"
    assert preds[0].provenance == "manual_override"

    csv_out = tmp_path / "predictions.csv"
    json_out = tmp_path / "predictions.json"
    export_prediction_tables(preds, csv_out, json_out, {"test": True})
    rows = list(csv.DictReader(csv_out.open()))
    assert len(rows) == 1
    assert rows[0]["auto_finger"] == "1"
    assert rows[0]["final_finger"] == "2"
    assert rows[0]["provenance"] == "manual_override"
    assert "musician_verdict" in rows[0]

    out_pdf = tmp_path / "annotated.pdf"
    out_png = tmp_path / "excerpt.png"
    rmeta = render_annotated_score(
        synth_pdf,
        measures,
        notes,
        preds,
        timings,
        out_pdf,
        out_png,
        manual_override_count=1,
    )
    assert rmeta["placed_score_label_count"] == 1
    assert out_pdf.exists() and out_pdf.stat().st_size > 500
    assert out_png.exists() and out_png.stat().st_size > 500


def test_manual_overrides_event_id_key_and_validation(tmp_path) -> None:
    import json

    import pytest

    from piano_fingering.models import PredictionRecord
    from piano_fingering.render import apply_manual_overrides

    rec = PredictionRecord(
        event_id="ev_0042",
        alignment_status="matched",
        perf_event_id="perf_0010",
        score_note_id="sn_0010",
        onset_sec=2.0,
        offset_sec=2.5,
        midi_pitch=62,
        pitch_name="D4",
        page_index=1,
        measure=2,
        beat=1.0,
        staff="treble",
        chord_group_id="cg_2",
        auto_hand="R",
        auto_finger="2",
        auto_confidence_tier="low",
        cost_margin=0.18,
        abstain_reason=None,
        final_hand="R",
        final_finger="2",
        final_confidence_tier="low",
        provenance="auto",
    )

    ov_by_event = tmp_path / "ov_event.json"
    ov_by_event.write_text(
        json.dumps({"finger_overrides": {"ev_0042": {"hand": "R", "finger": "3"}}})
    )
    counts = apply_manual_overrides([rec], [], ov_by_event)
    assert counts["finger_overrides"] == 1
    assert rec.auto_finger == "2"
    assert rec.final_finger == "3"
    assert rec.provenance == "manual_override"

    ov_invalid = tmp_path / "ov_bad.json"
    ov_invalid.write_text(
        json.dumps({"finger_overrides": {"ev_0042": {"hand": "R", "finger": "9"}}})
    )
    with pytest.raises(ValueError, match="Invalid manual finger override"):
        apply_manual_overrides([rec], [], ov_invalid)


def test_dual_plane_black_key_projection_and_longitudinal_v_gate() -> None:
    from piano_fingering.assign import score_candidates_for_attack
    from piano_fingering.models import FrameCalibration, FramePose, HandObservation

    # F#4 (MIDI 66) is a black key.
    u_fsharp4 = midi_to_canonical_u_center(66)

    # Simulate perspective elevation parallax between Z=0 (h_white) and Z=h_black (h_black):
    # At pixel (500, 420), projecting onto Z=0 lands at v=0.84 (white-key front apron > 0.78 gate),
    # whereas projecting onto the elevated black-key top plane lands cleanly at v=0.52 on the black key.
    h_white = [
        [0.02, 0.0, u_fsharp4 - 10.0],
        [0.0, 0.005, 0.84 - 2.10],
        [0.0, 0.0, 1.0],
    ]
    h_black = [
        [0.02, 0.0, u_fsharp4 - 10.0],
        [0.0, 0.005, 0.52 - 2.10],
        [0.0, 0.0, 1.0],
    ]

    # R2 sits on the F#4 black key top face (500, 420 -> v_black=0.52);
    # R1 sits out on the white-key front apron at the same u (500, 492 -> v_black=0.88 > 0.78 -> gated out!).
    pose = FramePose(
        frame_index=10,
        pts_sec=1.00,
        width=1920,
        height=1080,
        hands=[
            HandObservation(
                det_index=0,
                detector_chirality="R",
                resolved_hand="R",
                palm_cross=0.75,
                hand_confidence=0.95,
                landmarks={
                    "index_tip": (500.0, 420.0, 0.92),
                    "thumb_tip": (500.0, 492.0, 0.92),
                },
            )
        ],
    )
    cal_dual = FrameCalibration(
        frame_index=10,
        pts_sec=1.00,
        h_white=h_white,
        h_black=h_black,
        residual_kw=0.04,
        inlier_count=20,
        reliable=True,
    )
    cands, reason, _pts, _res = score_candidates_for_attack(
        midi_pitch=66,
        onset_sec=1.00,
        staff="treble",
        window_frames=[(pose, cal_dual)],
    )
    assert reason is None
    assert [(c.hand, c.finger) for c in cands] == [("R", 2)]
    assert abs(cands[0].v_norm - 0.52) < 1e-3

    # Verify that without the elevated black-key homography (using h_white for both), parallax causes rejection:
    cal_single_plane = FrameCalibration(
        frame_index=10,
        pts_sec=1.00,
        h_white=h_white,
        h_black=h_white,
        residual_kw=0.04,
        inlier_count=20,
        reliable=True,
    )
    cands_bad, reason_bad, _, _ = score_candidates_for_attack(
        midi_pitch=66,
        onset_sec=1.00,
        staff="treble",
        window_frames=[(pose, cal_single_plane)],
    )
    assert cands_bad == []
    assert reason_bad == "no_finger_within_gate"


def test_synthetic_vector_grand_staff_geometry_and_diatonic_pitch(tmp_path) -> None:
    import pdfplumber
    from reportlab.pdfgen import canvas

    from piano_fingering.score_pdf import (
        BASS_TOP_DIATONIC,
        TREBLE_TOP_DIATONIC,
        _extract_printed_system_measure_numbers,
        _extract_systems_on_page,
        diatonic_to_midi,
    )

    # Treble top line F5 = 77, middle line B4 = 71 (Bb4 = 70), ledger C4 = 60
    assert diatonic_to_midi(TREBLE_TOP_DIATONIC, 0) == 77
    assert diatonic_to_midi(TREBLE_TOP_DIATONIC - 4, -1) == 70
    assert diatonic_to_midi(TREBLE_TOP_DIATONIC - 10, 0) == 60
    # Bass top line A3 = 57, bottom line G2 = 43, F#3 = 54
    assert diatonic_to_midi(BASS_TOP_DIATONIC, 0) == 57
    assert diatonic_to_midi(BASS_TOP_DIATONIC - 8, 0) == 43
    assert diatonic_to_midi(BASS_TOP_DIATONIC - 2, +1) == 54

    # Render synthetic 2-system grand-staff vector PDF in reportlab (bottom-left y_rl = 792 - y_top)
    pdf_p = tmp_path / "grand_staff.pdf"
    page_h = 792.0
    c = canvas.Canvas(str(pdf_p), pagesize=(612.0, page_h))
    c.setLineWidth(0.6)
    for sys_i, sys_top in enumerate((120.0, 280.0)):
        # Treble 5 lines (space = 5.0 pt) and Bass 5 lines (offset +55 pt)
        for line_k in range(5):
            y_tr = page_h - (sys_top + line_k * 5.0)
            y_bs = page_h - (sys_top + 55.0 + line_k * 5.0)
            c.line(60.0, y_tr, 540.0, y_tr)
            c.line(60.0, y_bs, 540.0, y_bs)
        if sys_i == 1:
            # Printed measure number "5" just above system 2's top-left staff start
            c.setFont("Helvetica", 9)
            c.drawString(61.0, page_h - (sys_top - 10.0), "5")
    c.showPage()
    c.save()

    with pdfplumber.open(str(pdf_p)) as pdf:
        systems = _extract_systems_on_page(pdf.pages[0])
        assert len(systems) == 2
        assert abs(systems[0][0].space - 5.0) < 1e-2
        assert abs(systems[1][0].top_y - 280.0) < 1e-2
        m_nums = _extract_printed_system_measure_numbers(pdf.pages[0], systems)
        assert m_nums == {1: 5}
