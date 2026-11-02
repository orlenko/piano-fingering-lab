"""Stage 3: Exact-MIDI-pitch subsequence excerpt alignment and measure timing."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from .models import MeasureTiming, PerfNote, ScoreMeasure, ScoreNote


@dataclass
class AlignedPair:
    """Note-level alignment result across the analyzed score excerpt."""

    alignment_status: str  # "matched" | "unmatched_score" | "unmatched_perf"
    perf_note: PerfNote | None
    score_note: ScoreNote | None
    expected_time_sec: float | None
    timing_residual_sec: float | None


def _build_cumulative_beats(
    measures: list[ScoreMeasure],
) -> dict[int, float]:
    """Map measure number -> cumulative starting quarter-note beat (0.0 at first measure)."""
    cum: dict[int, float] = {}
    acc = 0.0
    for m in sorted(measures, key=lambda x: x.measure):
        cum[m.measure] = acc
        acc += float(m.beats_per_bar) * (4.0 / float(m.beat_unit))
    return cum


def align_performance_to_score(
    perf_notes: list[PerfNote],
    measures: list[ScoreMeasure],
    score_notes: list[ScoreNote],
    out_json_path: str | Path | None = None,
) -> tuple[list[AlignedPair], list[MeasureTiming], dict[str, Any]]:
    """Locate the played score subsequence without Measure-1 or full-score assumptions.

    Uses exact MIDI pitches + inter-beat rhythmic progression (no octave-folded chroma)
    to disambiguate quasi-repeated verses/choruses in different meters or octaves.
    """
    if not perf_notes or not measures or not score_notes:
        raise ValueError("Cannot align empty performance notes or empty parsed score.")

    attack_notes = [n for n in score_notes if not n.is_tied_continuation]
    cum_beats = _build_cumulative_beats(measures)
    measure_by_num = {m.measure: m for m in measures}

    # Attach global cumulative quarter-note beat g_beat to each attack note
    note_gbeats = np.array(
        [
            cum_beats[n.measure]
            + (n.beat - 1.0) * (4.0 / float(measure_by_num[n.measure].beat_unit))
            for n in attack_notes
        ],
        dtype=np.float64,
    )
    note_pitches = np.array([n.midi_pitch for n in attack_notes], dtype=np.int32)

    perf_onsets = np.array([p.onset_sec for p in perf_notes], dtype=np.float64)
    perf_pitches = np.array([p.midi_pitch for p in perf_notes], dtype=np.int32)

    # Group score attack notes by unique global beat positions b_0 < b_1 < ... < b_{K-1}
    unique_beats = np.unique(np.round(note_gbeats, 4))
    beat_pitches: list[list[int]] = []
    beat_measures: list[int] = []
    for gb in unique_beats:
        mask = np.abs(note_gbeats - gb) < 1e-3
        idxs = np.where(mask)[0]
        beat_pitches.append([int(note_pitches[i]) for i in idxs])
        beat_measures.append(attack_notes[int(idxs[0])].measure)

    # Candidate subsequence search:
    # Test starting at any measure start beat (or pickup beat) mapped to an early performance onset,
    # with candidate initial beat durations tau in [0.45, 1.15] s/quarter-beat, tracking local rubato.
    early_perf_times = sorted({round(float(t), 2) for t in perf_onsets if t <= perf_onsets[0] + 2.5})
    if not early_perf_times:
        early_perf_times = [float(perf_onsets[0])]

    measure_start_beat_indices: list[int] = []
    seen_m: set[int] = set()
    for b_idx, m_num in enumerate(beat_measures):
        if m_num not in seen_m:
            seen_m.add(m_num)
            measure_start_beat_indices.append(b_idx)

    tau_grid = np.linspace(0.26, 1.15, 36)

    def _trace_candidate(
        start_b_idx: int,
        t0: float,
        tau_init: float,
    ) -> tuple[float, int, list[tuple[int, float]]]:
        """Greedy-elastic beat tracker scoring exact MIDI pitch hits minus missed score notes."""
        t_pred = t0
        tau = tau_init
        total_score = 0.0
        beat_time_anchors: list[tuple[int, float]] = []
        last_matched_b_idx = start_b_idx
        consecutive_empty_beats = 0
        used_perf: set[int] = set()

        for k in range(start_b_idx, len(unique_beats)):
            if k > start_b_idx:
                db = float(unique_beats[k] - unique_beats[k - 1])
                t_pred += db * tau

            if t_pred > float(perf_onsets[-1]) + 0.45:
                break

            expected_ps = beat_pitches[k]
            matched_times: list[float] = []
            hits = 0
            for ep in expected_ps:
                # Find closest unused perf note with exact MIDI pitch within +-0.32s
                cands = [
                    p_i
                    for p_i in range(len(perf_notes))
                    if p_i not in used_perf
                    and int(perf_pitches[p_i]) == ep
                    and abs(float(perf_onsets[p_i]) - t_pred) <= 0.32
                ]
                if cands:
                    best_pi = min(cands, key=lambda p_i: abs(float(perf_onsets[p_i]) - t_pred))
                    used_perf.add(best_pi)
                    matched_times.append(float(perf_onsets[best_pi]))
                    hits += 1

            misses = len(expected_ps) - hits
            if hits > 0:
                # Use median matched time (robust to upward rolled-chord spread) to update clock & local tempo
                t_obs = float(np.median(matched_times))
                if beat_time_anchors:
                    prev_k, prev_t = beat_time_anchors[-1]
                    db_span = float(unique_beats[k] - unique_beats[prev_k])
                    dt_span = t_obs - prev_t
                    if db_span >= 0.5 and dt_span > 0.05:
                        inst_tau = dt_span / db_span
                        if 0.22 <= inst_tau <= 1.45:
                            # Mild rubato penalty + exponential smoothing
                            total_score -= 0.25 * abs(math.log(inst_tau / tau))
                            tau = 0.72 * tau + 0.28 * inst_tau
                t_pred = 0.35 * t_pred + 0.65 * t_obs
                beat_time_anchors.append((k, t_obs))
                last_matched_b_idx = k
                consecutive_empty_beats = 0
                total_score += 1.0 * hits - 0.30 * misses
            else:
                consecutive_empty_beats += 1
                total_score -= 0.30 * misses
                if consecutive_empty_beats >= 6:
                    break

        return total_score, last_matched_b_idx, beat_time_anchors

    candidate_by_start_measure: dict[int, tuple[float, int, int, float, list[tuple[int, float]]]] = {}
    for start_b_idx in measure_start_beat_indices:
        m_start_num = beat_measures[start_b_idx]
        best_for_m: tuple[float, int, int, float, list[tuple[int, float]]] | None = None
        for t0 in early_perf_times:
            for tau0 in tau_grid:
                sc, end_b_idx, anchors = _trace_candidate(start_b_idx, t0, float(tau0))
                if best_for_m is None or sc > best_for_m[0]:
                    best_for_m = (sc, start_b_idx, end_b_idx, float(tau0), anchors)
        if best_for_m is not None:
            candidate_by_start_measure[m_start_num] = best_for_m

    ranked_starts = sorted(
        candidate_by_start_measure.items(),
        key=lambda kv: kv[1][0],
        reverse=True,
    )
    best_m_start, (best_score, best_b_start, best_b_end, best_tau, best_anchors) = ranked_starts[0]
    best_m_end = beat_measures[best_b_end]

    # Compute top-2 non-overlapping candidate score for disambiguation audit
    top2_entry: tuple[int, int, float] | None = None
    for cand_m, (cand_sc, cb0, cb1, _ctau, _canc) in ranked_starts[1:]:
        cm1 = beat_measures[cb1]
        if cm1 < best_m_start or cand_m > best_m_end:
            top2_entry = (cand_m, cm1, cand_sc)
            break

    if not best_anchors:
        raise RuntimeError("Failed to establish score-to-performance alignment anchors.")

    # Build monotonic piecewise-linear beat -> time interpolation over [gb_start, gb_end]
    anchor_gbeats = np.array([unique_beats[k] for k, _t in best_anchors], dtype=np.float64)
    anchor_times = np.maximum.accumulate(
        np.array([t for _k, t in best_anchors], dtype=np.float64)
    )
    if len(anchor_gbeats) >= 2:
        avg_tau = float(
            (anchor_times[-1] - anchor_times[0])
            / max(anchor_gbeats[-1] - anchor_gbeats[0], 1e-3)
        )
    else:
        avg_tau = best_tau

    def beat_to_time(gb: float) -> float:
        if gb <= anchor_gbeats[0]:
            return float(anchor_times[0] + (gb - anchor_gbeats[0]) * avg_tau)
        if gb >= anchor_gbeats[-1]:
            return float(anchor_times[-1] + (gb - anchor_gbeats[-1]) * avg_tau)
        return float(np.interp(gb, anchor_gbeats, anchor_times))

    gb_min = cum_beats[best_m_start]
    gb_max = float(unique_beats[best_b_end]) + 0.01

    excerpt_score_indices = [
        i
        for i, n in enumerate(attack_notes)
        if best_m_start <= n.measure <= best_m_end and gb_min - 1e-3 <= note_gbeats[i] <= gb_max
    ]

    # Optimal 1-to-1 per-pitch bipartite matching between excerpt score attacks and perf_notes
    matched_score_to_perf: dict[int, int] = {}
    matched_perf_set: set[int] = set()

    distinct_pitches = sorted({attack_notes[i].midi_pitch for i in excerpt_score_indices})
    for pitch in distinct_pitches:
        s_idxs = [i for i in excerpt_score_indices if attack_notes[i].midi_pitch == pitch]
        p_idxs = [j for j, pn in enumerate(perf_notes) if pn.midi_pitch == pitch]
        if not s_idxs or not p_idxs:
            continue

        big_cost = 1e6
        cost_mat = np.full((len(s_idxs), len(p_idxs)), big_cost, dtype=np.float64)
        for r_i, s_i in enumerate(s_idxs):
            sn = attack_notes[s_i]
            t_exp = beat_to_time(float(note_gbeats[s_i]))
            tol = 0.34 if sn.is_arpeggiated else 0.26
            for c_j, p_j in enumerate(p_idxs):
                dt = abs(perf_notes[p_j].onset_sec - t_exp)
                if dt <= tol:
                    cost_mat[r_i, c_j] = dt

        row_ind, col_ind = linear_sum_assignment(cost_mat)
        for r_i, c_j in zip(row_ind, col_ind):
            if cost_mat[r_i, c_j] < 1.0:
                matched_score_to_perf[s_idxs[r_i]] = p_idxs[c_j]
                matched_perf_set.add(p_idxs[c_j])

    # Refine beat_to_time from final 1-to-1 matched pairs
    refined_by_gb: dict[float, list[float]] = {}
    for s_i, p_j in matched_score_to_perf.items():
        gb_key = round(float(note_gbeats[s_i]), 4)
        refined_by_gb.setdefault(gb_key, []).append(perf_notes[p_j].onset_sec)
    if len(refined_by_gb) >= 2:
        r_gbs = sorted(refined_by_gb.keys())
        # Use 30th-percentile onset on each beat so upward rolled chords anchor near beat start
        r_ts = np.maximum.accumulate(
            np.array([float(np.percentile(refined_by_gb[g], 30)) for g in r_gbs], dtype=np.float64)
        )
        anchor_gbeats = np.array(r_gbs, dtype=np.float64)
        anchor_times = r_ts
        avg_tau = float(
            (anchor_times[-1] - anchor_times[0])
            / max(anchor_gbeats[-1] - anchor_gbeats[0], 1e-3)
        )

    # Assemble unified AlignedPair list across the excerpt
    aligned_pairs: list[AlignedPair] = []
    residuals: list[float] = []
    for s_i in excerpt_score_indices:
        sn = attack_notes[s_i]
        t_exp = round(beat_to_time(float(note_gbeats[s_i])), 6)
        if s_i in matched_score_to_perf:
            pn = perf_notes[matched_score_to_perf[s_i]]
            res = round(pn.onset_sec - t_exp, 6)
            residuals.append(abs(res))
            aligned_pairs.append(
                AlignedPair(
                    alignment_status="matched",
                    perf_note=pn,
                    score_note=sn,
                    expected_time_sec=t_exp,
                    timing_residual_sec=res,
                )
            )
        else:
            aligned_pairs.append(
                AlignedPair(
                    alignment_status="unmatched_score",
                    perf_note=None,
                    score_note=sn,
                    expected_time_sec=t_exp,
                    timing_residual_sec=None,
                )
            )

    for p_j, pn in enumerate(perf_notes):
        if p_j not in matched_perf_set:
            aligned_pairs.append(
                AlignedPair(
                    alignment_status="unmatched_perf",
                    perf_note=pn,
                    score_note=None,
                    expected_time_sec=None,
                    timing_residual_sec=None,
                )
            )

    # Sort aligned pairs chronologically
    def _pair_sort_key(ap: AlignedPair) -> tuple[float, int]:
        t = (
            ap.perf_note.onset_sec
            if ap.perf_note is not None
            else (ap.expected_time_sec or 0.0)
        )
        p = (
            ap.score_note.midi_pitch
            if ap.score_note is not None
            else (ap.perf_note.midi_pitch if ap.perf_note is not None else 0)
        )
        return (t, p)

    aligned_pairs.sort(key=_pair_sort_key)

    # Build monotonic MeasureTiming intervals for [best_m_start .. best_m_end]
    last_matched_onset = max(
        (ap.perf_note.onset_sec for ap in aligned_pairs if ap.alignment_status == "matched" and ap.perf_note),
        default=float(perf_onsets[-1]),
    )
    measure_timings: list[MeasureTiming] = []
    for m_num in range(best_m_start, best_m_end + 1):
        sm = measure_by_num[m_num]
        m_gb0 = cum_beats[m_num]
        m_gb1 = m_gb0 + float(sm.beats_per_bar) * (4.0 / float(sm.beat_unit))
        t_s = beat_to_time(m_gb0)
        t_e = beat_to_time(m_gb1)
        if m_num == best_m_end:
            # Terminate highlight cleanly shortly after final played beat rather than running into post-play silence
            t_e = min(t_e, last_matched_onset + avg_tau * 1.1)
        m_matched = sum(
            1
            for ap in aligned_pairs
            if ap.alignment_status == "matched"
            and ap.score_note is not None
            and ap.score_note.measure == m_num
        )
        if m_matched == 0 and t_s > last_matched_onset + 0.1:
            continue
        measure_timings.append(
            MeasureTiming(
                measure=m_num,
                page_index=sm.page_index,
                system_index=sm.system_index,
                t_start_sec=round(t_s, 4),
                t_end_sec=round(max(t_e, t_s + 0.1), 4),
                matched_note_count=m_matched,
                provenance="auto",
            )
        )

    included_measures = {mt.measure for mt in measure_timings}
    if included_measures:
        aligned_pairs = [
            ap
            for ap in aligned_pairs
            if ap.score_note is None or ap.score_note.measure in included_measures
        ]
        excerpt_score_indices = [
            i for i in excerpt_score_indices if attack_notes[i].measure in included_measures
        ]

    # Ensure exact boundary continuity between consecutive measures
    for idx in range(len(measure_timings) - 1):
        mid = round(
            0.5 * (measure_timings[idx].t_end_sec + measure_timings[idx + 1].t_start_sec),
            4,
        )
        measure_timings[idx].t_end_sec = mid
        measure_timings[idx + 1].t_start_sec = mid

    actual_m_end = measure_timings[-1].measure if measure_timings else best_m_end
    matched_count = sum(1 for ap in aligned_pairs if ap.alignment_status == "matched")
    unmatched_score_count = sum(
        1 for ap in aligned_pairs if ap.alignment_status == "unmatched_score"
    )
    unmatched_perf_count = sum(
        1 for ap in aligned_pairs if ap.alignment_status == "unmatched_perf"
    )

    top2_score_val = top2_entry[2] if top2_entry is not None else 0.0
    # Heuristic ambiguity diagnostic, not a calibrated probability of excerpt correctness.
    alignment_ambiguous = top2_entry is not None and (
        best_score - top2_score_val < 3.0
        or (top2_score_val > 0 and best_score / top2_score_val < 1.10)
    )
    meta: dict[str, Any] = {
        "alignment_ambiguous": alignment_ambiguous,
        "ambiguity_comparison_available": top2_entry is not None,
        "matched_measure_range": [best_m_start, actual_m_end],
        "matched_page_indices": sorted({mt.page_index for mt in measure_timings}),
        "estimated_tempo_bpm": round(60.0 / avg_tau, 2),
        "top1_alignment_score": round(best_score, 3),
        "top2_non_overlapping_range": (
            [top2_entry[0], top2_entry[1]] if top2_entry is not None else None
        ),
        "top2_alignment_score": round(top2_score_val, 3),
        "top1_minus_top2_margin": round(best_score - top2_score_val, 3),
        "top1_to_top2_ratio": (
            round(best_score / top2_score_val, 3) if top2_score_val > 0 else None
        ),
        "excerpt_score_attack_count": len(excerpt_score_indices),
        "matched_note_count": matched_count,
        "unmatched_score_note_count": unmatched_score_count,
        "unmatched_perf_note_count": unmatched_perf_count,
        "score_recall_in_excerpt": round(
            matched_count / max(len(excerpt_score_indices), 1), 4
        ),
        "median_abs_timing_residual_sec": (
            round(float(np.median(residuals)), 4) if residuals else None
        ),
        "p95_abs_timing_residual_sec": (
            round(float(np.percentile(residuals, 95)), 4) if residuals else None
        ),
    }

    if out_json_path is not None:
        out_p = Path(out_json_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(
            json.dumps(
                {
                    "metadata": meta,
                    "measure_timings": [mt.to_dict() for mt in measure_timings],
                    "pairs": [
                        {
                            "alignment_status": ap.alignment_status,
                            "perf_event_id": (
                                ap.perf_note.perf_event_id if ap.perf_note else None
                            ),
                            "score_note_id": (
                                ap.score_note.score_note_id if ap.score_note else None
                            ),
                            "onset_sec": ap.perf_note.onset_sec if ap.perf_note else None,
                            "expected_time_sec": ap.expected_time_sec,
                            "timing_residual_sec": ap.timing_residual_sec,
                            "midi_pitch": (
                                ap.score_note.midi_pitch
                                if ap.score_note
                                else (ap.perf_note.midi_pitch if ap.perf_note else None)
                            ),
                            "measure": ap.score_note.measure if ap.score_note else None,
                            "beat": ap.score_note.beat if ap.score_note else None,
                            "staff": ap.score_note.staff if ap.score_note else None,
                        }
                        for ap in aligned_pairs
                    ],
                },
                indent=2,
            )
        )

    return aligned_pairs, measure_timings, meta
