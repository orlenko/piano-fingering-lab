"""Stage 6: Attack-window dual-plane candidate scoring and order-constrained chord DP solver."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .align import AlignedPair
from .hand_pose import FINGERTIP_JOINTS
from .models import (
    CandidateFinger,
    FrameCalibration,
    FramePose,
    PredictionRecord,
    is_black_key,
    midi_to_canonical_u_center,
    midi_to_name,
)

# Ordered anatomical fingers from low pitch to high pitch within each hand:
# L5(0), L4(1), L3(2), L2(3), L1(4) | R1(5), R2(6), R3(7), R4(8), R5(9)
ORDERED_FINGERS: tuple[tuple[str, int], ...] = (
    ("L", 5),
    ("L", 4),
    ("L", 3),
    ("L", 2),
    ("L", 1),
    ("R", 1),
    ("R", 2),
    ("R", 3),
    ("R", 4),
    ("R", 5),
)

ATTACK_PRE_SEC = 0.070
ATTACK_POST_SEC = 0.100
MIN_TIP_CONF = 0.45
MAX_LATERAL_GATE_KW = 0.85
ABSTAIN_PENALTY = 0.98
AMBIGUITY_MARGIN_KW = 0.12
HIGH_CONF_MARGIN_KW = 0.28


def project_homography(h_mat: list[list[float]] | np.ndarray, x: float, y: float) -> tuple[float, float]:
    """Project image pixel (x, y) through 3x3 planar homography H -> (u, v)."""
    h = np.asarray(h_mat, dtype=np.float64)
    denom = h[2, 0] * x + h[2, 1] * y + h[2, 2]
    if abs(denom) < 1e-9:
        return (float("nan"), float("nan"))
    u = (h[0, 0] * x + h[0, 1] * y + h[0, 2]) / denom
    v = (h[1, 0] * x + h[1, 1] * y + h[1, 2]) / denom
    return (float(u), float(v))


def _longitudinal_v_penalty(v_med: float, black: bool) -> float | None:
    """Return longitudinal penalty >= 0 if v_med is valid for key type, else None (hard reject)."""
    if math.isnan(v_med) or v_med < -0.10 or v_med > 1.10:
        return None
    if black:
        # Black keys span v in [0.0, ~0.64] on the black-key top plane; allow slight pad overhang to 0.78
        if v_med > 0.78:
            return None
        if v_med > 0.64:
            return 0.6 * (v_med - 0.64)
        if v_med < 0.0:
            return 0.5 * (-v_med)
        return 0.0
    else:
        # White keys span v in [0.0, 1.0]; most natural contact is v in [0.25, 0.98]
        if v_med < 0.0:
            return 0.5 * (-v_med)
        if v_med > 1.0:
            return 0.5 * (v_med - 1.0)
        return 0.0


def score_candidates_for_attack(
    midi_pitch: int,
    onset_sec: float,
    staff: str | None,
    window_frames: list[tuple[FramePose, FrameCalibration]],
) -> tuple[list[CandidateFinger], str | None, list[float], float | None]:
    """Evaluate all 10 anatomical fingers in the attack window around onset_sec.

    Returns:
        (ranked_candidates, immediate_abstain_reason_if_no_candidates, supporting_pts, median_calib_residual)
    """
    if not window_frames:
        return [], "no_frames_in_attack_window", [], None

    reliable_frames = [(fp, fc) for fp, fc in window_frames if fc.reliable]
    if not reliable_frames:
        return [], "calibration_unreliable", [], None

    calib_res = float(np.median([fc.residual_kw for _fp, fc in reliable_frames]))
    supp_pts = [round(fp.pts_sec, 4) for fp, _fc in reliable_frames]

    total_hands = sum(len(fp.hands) for fp, _fc in reliable_frames)
    if total_hands == 0:
        return [], "no_hand_detected", supp_pts, round(calib_res, 4)

    black = is_black_key(midi_pitch)
    u_target = midi_to_canonical_u_center(midi_pitch)
    expected_hand = "R" if staff == "treble" else ("L" if staff == "bass" else None)

    any_confident_tip = False
    candidates: list[CandidateFinger] = []

    for hand_code, finger_num in ORDERED_FINGERS:
        joint_name = FINGERTIP_JOINTS[finger_num]
        obs_t: list[float] = []
        obs_u: list[float] = []
        obs_v: list[float] = []
        obs_c: list[float] = []
        obs_w: list[float] = []

        for fp, fc in reliable_frames:
            h_mat = fc.h_black if black else fc.h_white
            if h_mat is None:
                continue
            for h_obs in fp.hands:
                if h_obs.resolved_hand != hand_code:
                    continue
                lm = h_obs.landmarks.get(joint_name)
                if lm is None or lm[2] < MIN_TIP_CONF:
                    continue
                any_confident_tip = True
                u_val, v_val = project_homography(h_mat, lm[0], lm[1])
                if math.isnan(u_val) or math.isnan(v_val):
                    continue
                dt = fp.pts_sec - onset_sec
                w = math.exp(-0.5 * (dt / 0.055) ** 2)
                obs_t.append(fp.pts_sec)
                obs_u.append(u_val)
                obs_v.append(v_val)
                obs_c.append(lm[2])
                obs_w.append(w)

        if not obs_u:
            continue

        w_arr = np.asarray(obs_w, dtype=np.float64)
        w_sum = float(np.sum(w_arr))
        u_arr = np.asarray(obs_u, dtype=np.float64)
        v_arr = np.asarray(obs_v, dtype=np.float64)
        c_arr = np.asarray(obs_c, dtype=np.float64)

        u_est = float(np.sum(w_arr * u_arr) / w_sum)
        v_est = float(np.sum(w_arr * v_arr) / w_sum)
        mean_conf = float(np.mean(c_arr))

        delta_u = abs(u_est - u_target)
        if delta_u > MAX_LATERAL_GATE_KW:
            continue

        v_pen = _longitudinal_v_penalty(v_est, black=black)
        if v_pen is None:
            continue

        # Lateral slip velocity |du/dt| in white-key widths per second
        if len(obs_t) >= 2 and (max(obs_t) - min(obs_t)) >= 0.025:
            t_arr = np.asarray(obs_t, dtype=np.float64)
            slope = float(np.polyfit(t_arr - onset_sec, u_arr, 1)[0])
            slip = abs(slope)
        else:
            slip = 0.0

        staff_pen = (
            0.12 if (expected_hand is not None and hand_code != expected_hand) else 0.0
        )
        single_frame_pen = 0.08 if len(obs_u) == 1 else 0.0

        cost = (
            1.00 * delta_u
            + 0.05 * min(slip, 6.0)
            + v_pen
            + 0.18 * (1.0 - mean_conf)
            + staff_pen
            + single_frame_pen
        )

        candidates.append(
            CandidateFinger(
                hand=hand_code,
                finger=finger_num,
                cost=round(cost, 4),
                delta_u_kw=round(delta_u, 4),
                v_norm=round(v_est, 4),
                slip_kw_per_s=round(slip, 4),
                mean_tip_conf=round(mean_conf, 4),
                supporting_frames=len(obs_u),
            )
        )

    candidates.sort(key=lambda c: c.cost)
    if not candidates:
        reason = "no_finger_within_gate" if any_confident_tip else "low_landmark_confidence"
        return [], reason, supp_pts, round(calib_res, 4)

    return candidates, None, supp_pts, round(calib_res, 4)


def solve_order_constrained_cluster(
    note_pitches: list[int],
    note_candidates: list[list[CandidateFinger]],
    abstain_penalty: float = ABSTAIN_PENALTY,
    forbidden: tuple[int, int] | None = None,
) -> tuple[float, list[int | None]]:
    """Exact 36-state order-constrained DP over ORDERED_FINGERS + per-note unknown (None).

    Notes MUST be pre-sorted in non-decreasing MIDI pitch order:
        note_pitches[0] <= note_pitches[1] <= ... <= note_pitches[k-1].

    Enforces:
        - Intra-hand strict pitch monotonicity: within hand L (indices 0..4) and within
          hand R (indices 5..9), strictly higher finger index is required as pitch increases.
        - Mutual exclusion: no finger index in 0..9 can be used more than once in the cluster.
        - Partial-chord abstention: any individual note may take state None at cost abstain_penalty.

    Args:
        forbidden: optional (note_idx, finger_order_idx_or_neg1_for_unknown) to exclude when
                   computing exact cluster-consistent cost margins.
    """
    k = len(note_pitches)
    if k == 0:
        return 0.0, []

    # Map each note's candidates to ORDERED_FINGERS index 0..9
    finger_to_idx = {hf: idx for idx, hf in enumerate(ORDERED_FINGERS)}
    unary: list[dict[int, float]] = []
    for cands in note_candidates:
        d: dict[int, float] = {}
        for c in cands:
            f_idx = finger_to_idx[(c.hand, c.finger)]
            d[f_idx] = c.cost
        unary.append(d)

    # DP state: (last_L_idx in {-1, 0, 1, 2, 3, 4}, last_R_idx in {4, 5, 6, 7, 8, 9})
    # last_L_pitch and last_R_pitch are strictly increasing when finger index strictly increases,
    # except we also forbid assigning two identical-pitch notes in the cluster to the same hand.
    inf = 1e12
    # state key: (last_L, last_R, last_L_pitch, last_R_pitch) -> cost
    dp: dict[tuple[int, int, int, int], float] = {(-1, 4, -1, -1): 0.0}
    back: list[dict[tuple[int, int, int, int], tuple[tuple[int, int, int, int], int | None]]] = []

    for i in range(k):
        p_i = note_pitches[i]
        ndp: dict[tuple[int, int, int, int], float] = {}
        nback: dict[tuple[int, int, int, int], tuple[tuple[int, int, int, int], int | None]] = {}

        for state, cur_cost in dp.items():
            last_l, last_r, pitch_l, pitch_r = state

            # Option A: abstain (None)
            if forbidden != (i, -1):
                c_unk = cur_cost + abstain_penalty
                if c_unk < ndp.get(state, inf):
                    ndp[state] = c_unk
                    nback[state] = (state, None)

            # Option B: Left-hand finger f_idx in 0..4
            for f_idx in range(last_l + 1, 5):
                if forbidden == (i, f_idx):
                    continue
                if f_idx not in unary[i]:
                    continue
                if pitch_l == p_i:
                    continue
                nstate = (f_idx, last_r, p_i, pitch_r)
                ncost = cur_cost + unary[i][f_idx]
                if ncost < ndp.get(nstate, inf):
                    ndp[nstate] = ncost
                    nback[nstate] = (state, f_idx)

            # Option C: Right-hand finger f_idx in 5..9
            for f_idx in range(last_r + 1, 10):
                if forbidden == (i, f_idx):
                    continue
                if f_idx not in unary[i]:
                    continue
                if pitch_r == p_i:
                    continue
                nstate = (last_l, f_idx, pitch_l, p_i)
                ncost = cur_cost + unary[i][f_idx]
                if ncost < ndp.get(nstate, inf):
                    ndp[nstate] = ncost
                    nback[nstate] = (state, f_idx)

        dp = ndp
        back.append(nback)
        if not dp:
            return inf, [None] * k

    best_end_state = min(dp, key=lambda s: dp[s])
    best_total_cost = dp[best_end_state]

    choices: list[int | None] = [None] * k
    cur = best_end_state
    for i in range(k - 1, -1, -1):
        prev_state, choice = back[i][cur]
        choices[i] = choice
        cur = prev_state

    return float(best_total_cost), choices


def _cluster_matched_indices(matched_pairs: list[AlignedPair]) -> list[list[int]]:
    """Group matched attacks by |dt| <= 45ms OR shared score chord_group_id with |dt| <= 250ms."""
    n = len(matched_pairs)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        pi = matched_pairs[i].perf_note
        si = matched_pairs[i].score_note
        assert pi is not None and si is not None
        for j in range(i + 1, n):
            pj = matched_pairs[j].perf_note
            sj = matched_pairs[j].score_note
            assert pj is not None and sj is not None
            dt = abs(pi.onset_sec - pj.onset_sec)
            if dt > 0.260:
                # Pairs are sorted chronologically, so no later j can be within 260ms
                if pj.onset_sec - pi.onset_sec > 0.260:
                    break
                continue
            if dt <= 0.045 or (si.chord_group_id == sj.chord_group_id and dt <= 0.250):
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def assign_fingerings(
    aligned_pairs: list[AlignedPair],
    frame_poses: list[FramePose],
    frame_calibrations: list[FrameCalibration],
    out_json_path: str | Path | None = None,
    alignment_ambiguous: bool = False,
) -> tuple[list[PredictionRecord], dict[str, Any]]:
    """Run Stage 6 attack-window joint finger assignment across all excerpt events."""
    if len(frame_poses) != len(frame_calibrations):
        raise ValueError("frame_poses and frame_calibrations must have identical frame count.")

    pts_arr = np.array([fp.pts_sec for fp in frame_poses], dtype=np.float64)

    def _get_window(t0: float) -> list[tuple[FramePose, FrameCalibration]]:
        lo = int(np.searchsorted(pts_arr, t0 - ATTACK_PRE_SEC, side="left"))
        hi = int(np.searchsorted(pts_arr, t0 + ATTACK_POST_SEC, side="right"))
        return [(frame_poses[k], frame_calibrations[k]) for k in range(lo, hi)]

    # Separate matched pairs for joint chord/roll DP solving
    matched_indices = [
        idx for idx, ap in enumerate(aligned_pairs) if ap.alignment_status == "matched"
    ]
    matched_pairs = [aligned_pairs[idx] for idx in matched_indices]

    # Pre-score unary candidates for every matched attack in its own individual attack window
    matched_cands: list[list[CandidateFinger]] = []
    matched_reasons: list[str | None] = []
    matched_pts: list[list[float]] = []
    matched_res: list[float | None] = []

    for ap in matched_pairs:
        assert ap.perf_note is not None and ap.score_note is not None
        win = _get_window(ap.perf_note.onset_sec)
        cands, reason, s_pts, c_res = score_candidates_for_attack(
            midi_pitch=ap.score_note.midi_pitch,
            onset_sec=ap.perf_note.onset_sec,
            staff=ap.score_note.staff,
            window_frames=win,
        )
        matched_cands.append(cands)
        matched_reasons.append(reason)
        matched_pts.append(s_pts)
        matched_res.append(c_res)

    # Solve clusters via exact order-constrained DP
    clusters = _cluster_matched_indices(matched_pairs)
    matched_results: dict[int, tuple[str, str, str, float | None, str | None]] = {}

    for cl_member_idxs in clusters:
        # Sort cluster members by ascending (midi_pitch, onset_sec)
        cl_sorted = sorted(
            cl_member_idxs,
            key=lambda m_i: (
                matched_pairs[m_i].score_note.midi_pitch,  # type: ignore[union-attr]
                matched_pairs[m_i].perf_note.onset_sec,    # type: ignore[union-attr]
            ),
        )
        pitches = [matched_pairs[m_i].score_note.midi_pitch for m_i in cl_sorted]  # type: ignore[union-attr]
        cands_list = [matched_cands[m_i] for m_i in cl_sorted]

        opt_cost, opt_choices = solve_order_constrained_cluster(pitches, cands_list)

        for pos_in_cl, m_i in enumerate(cl_sorted):
            choice = opt_choices[pos_in_cl]
            if choice is None:
                reason = matched_reasons[m_i] or "chord_order_or_gate_abstention"
                matched_results[m_i] = ("unknown", "unknown", "unknown", None, reason)
                continue

            hand_code, finger_num = ORDERED_FINGERS[choice]
            # Compute exact cluster-consistent alternative cost forbidding this finger on this note
            alt_cost, _ = solve_order_constrained_cluster(
                pitches,
                cands_list,
                forbidden=(pos_in_cl, choice),
            )
            margin = round(max(0.0, alt_cost - opt_cost), 4)

            chosen_cand = next(
                c
                for c in matched_cands[m_i]
                if c.hand == hand_code and c.finger == finger_num
            )

            if margin < AMBIGUITY_MARGIN_KW:
                matched_results[m_i] = (
                    "unknown",
                    "unknown",
                    "unknown",
                    margin,
                    "ambiguous_candidates",
                )
            elif (
                margin >= HIGH_CONF_MARGIN_KW
                and chosen_cand.delta_u_kw <= 0.45
                and chosen_cand.mean_tip_conf >= 0.65
            ):
                matched_results[m_i] = (
                    hand_code,
                    str(finger_num),
                    "high",
                    margin,
                    None,
                )
            else:
                matched_results[m_i] = (
                    hand_code,
                    str(finger_num),
                    "low",
                    margin,
                    None,
                )

    if alignment_ambiguous:
        for m_i, (_hand, _finger, _tier, margin, _reason) in matched_results.items():
            matched_results[m_i] = (
                "unknown", "unknown", "unknown", margin, "ambiguous_score_alignment"
            )

    # Assemble full PredictionRecord list preserving matched, unmatched_score, and unmatched_perf
    matched_pos_lookup = {orig_i: m_i for m_i, orig_i in enumerate(matched_indices)}
    records: list[PredictionRecord] = []

    for idx, ap in enumerate(aligned_pairs):
        ev_id = f"ev_{idx:04d}"
        if ap.alignment_status == "matched":
            m_i = matched_pos_lookup[idx]
            pn = ap.perf_note
            sn = ap.score_note
            assert pn is not None and sn is not None
            ah, af, atier, margin, reason = matched_results[m_i]
            records.append(
                PredictionRecord(
                    event_id=ev_id,
                    alignment_status="matched",
                    perf_event_id=pn.perf_event_id,
                    score_note_id=sn.score_note_id,
                    onset_sec=pn.onset_sec,
                    offset_sec=pn.offset_sec,
                    midi_pitch=sn.midi_pitch,
                    pitch_name=sn.pitch_name,
                    page_index=sn.page_index,
                    measure=sn.measure,
                    beat=sn.beat,
                    staff=sn.staff,
                    chord_group_id=sn.chord_group_id,
                    auto_hand=ah,
                    auto_finger=af,
                    auto_confidence_tier=atier,
                    cost_margin=margin,
                    abstain_reason=reason,
                    candidate_fingers=matched_cands[m_i],
                    supporting_frame_pts=matched_pts[m_i],
                    calibration_residual_kw=matched_res[m_i],
                    final_hand=ah,
                    final_finger=af,
                    final_confidence_tier=atier,
                    provenance="auto",
                )
            )
        elif ap.alignment_status == "unmatched_score":
            sn = ap.score_note
            assert sn is not None
            records.append(
                PredictionRecord(
                    event_id=ev_id,
                    alignment_status="unmatched_score",
                    perf_event_id=None,
                    score_note_id=sn.score_note_id,
                    onset_sec=ap.expected_time_sec,
                    offset_sec=None,
                    midi_pitch=sn.midi_pitch,
                    pitch_name=sn.pitch_name,
                    page_index=sn.page_index,
                    measure=sn.measure,
                    beat=sn.beat,
                    staff=sn.staff,
                    chord_group_id=sn.chord_group_id,
                    auto_hand="unknown",
                    auto_finger="unknown",
                    auto_confidence_tier="unknown",
                    cost_margin=None,
                    abstain_reason="no_transcribed_onset",
                    final_hand="unknown",
                    final_finger="unknown",
                    final_confidence_tier="unknown",
                    provenance="auto",
                )
            )
        else:
            pn = ap.perf_note
            assert pn is not None
            records.append(
                PredictionRecord(
                    event_id=ev_id,
                    alignment_status="unmatched_perf",
                    perf_event_id=pn.perf_event_id,
                    score_note_id=None,
                    onset_sec=pn.onset_sec,
                    offset_sec=pn.offset_sec,
                    midi_pitch=pn.midi_pitch,
                    pitch_name=midi_to_name(pn.midi_pitch),
                    page_index=None,
                    measure=None,
                    beat=None,
                    staff=None,
                    chord_group_id=None,
                    auto_hand="unknown",
                    auto_finger="unknown",
                    auto_confidence_tier="unknown",
                    cost_margin=None,
                    abstain_reason="unmatched_audio_onset",
                    final_hand="unknown",
                    final_finger="unknown",
                    final_confidence_tier="unknown",
                    provenance="auto",
                )
            )

    score_events = [r for r in records if r.alignment_status in ("matched", "unmatched_score")]
    high_cnt = sum(1 for r in score_events if r.auto_confidence_tier == "high")
    low_cnt = sum(1 for r in score_events if r.auto_confidence_tier == "low")
    unk_cnt = sum(1 for r in score_events if r.auto_confidence_tier == "unknown")

    reason_counts: dict[str, int] = {}
    for r in score_events:
        if r.auto_confidence_tier == "unknown":
            key = r.abstain_reason or "unspecified"
            reason_counts[key] = reason_counts.get(key, 0) + 1

    meta: dict[str, Any] = {
        "excerpt_score_attacks_total": len(score_events),
        "matched_score_attacks": sum(1 for r in score_events if r.alignment_status == "matched"),
        "emitted_predictions_total": high_cnt + low_cnt,
        "emitted_high_confidence": high_cnt,
        "emitted_low_confidence": low_cnt,
        "abstained_unknown_total": unk_cnt,
        "emitted_coverage_over_excerpt_score_attacks": round(
            (high_cnt + low_cnt) / max(len(score_events), 1), 4
        ),
        "emitted_coverage_over_matched_attacks": round(
            (high_cnt + low_cnt)
            / max(sum(1 for r in score_events if r.alignment_status == "matched"), 1),
            4,
        ),
        "abstain_reasons_breakdown": reason_counts,
        "unmatched_perf_events": sum(1 for r in records if r.alignment_status == "unmatched_perf"),
    }

    if out_json_path is not None:
        out_p = Path(out_json_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(
            json.dumps(
                {
                    "metadata": meta,
                    "predictions": [r.to_dict() for r in records],
                },
                indent=2,
            )
        )

    return records, meta
