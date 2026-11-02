"""Stage 7: Manual-override layer, collision-aware vector PDF/PNG score overlay, CSV/JSON export, and VFR split-screen MP4 compositor."""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
import subprocess
import time
from typing import Any
import warnings

import av
import cv2
import imageio_ffmpeg
import numpy as np
import pdfplumber
from PIL import Image
from pypdf import PdfReader, PdfWriter
import pypdfium2 as pdfium
from reportlab.lib.colors import Color
from reportlab.pdfgen import canvas

from .hand_pose import FINGERTIP_JOINTS
from .models import (
    FrameCalibration,
    FramePose,
    MeasureTiming,
    PredictionRecord,
    ScoreMeasure,
    ScoreNote,
    is_black_key,
    midi_to_canonical_u_center,
    midi_to_name,
)


def _validate_output_timing(
    source_pts: list[float], output_pts: list[float], av_offset_error_ms: float,
) -> float:
    """Fail closed on dropped frames or failed presentation/audio clock preservation."""
    if not source_pts or len(source_pts) != len(output_pts):
        raise RuntimeError("Output video frame count differs from source or is empty.")
    errors = np.abs(np.asarray(output_pts) - np.asarray(source_pts)) * 1000.0
    max_error = float(np.max(errors))
    if not np.all(np.isfinite(errors)) or max_error >= 1.0:
        raise RuntimeError("Output video presentation timestamps exceed the 1 ms tolerance.")
    if not np.isfinite(av_offset_error_ms) or av_offset_error_ms > 5.0:
        raise RuntimeError("Output audio/video clock offset exceeds the 5 ms tolerance.")
    return max_error


def apply_manual_overrides(
    predictions: list[PredictionRecord],
    measure_timings: list[MeasureTiming],
    overrides_path: str | Path | None = None,
) -> dict[str, int]:
    """Apply optional non-destructive .local/overrides.json without mutating auto_* fields."""
    counts = {"finger_overrides": 0, "measure_timing_overrides": 0}
    if overrides_path is None:
        return counts
    ov_p = Path(overrides_path)
    if not ov_p.exists():
        return counts

    data = json.loads(ov_p.read_text(encoding="utf-8"))
    f_ov = data.get("finger_overrides", {})
    m_ov = data.get("measure_timing_overrides", {})

    valid_hands = {"L", "R", "unknown"}
    valid_fingers = {"1", "2", "3", "4", "5", "unknown"}

    if isinstance(f_ov, dict):
        matched_f_keys: set[str] = set()
        for rec in predictions:
            rec_keys = [
                k for k in (rec.score_note_id, rec.event_id, rec.perf_event_id) if k is not None
            ]
            hit_key = next((k for k in rec_keys if k in f_ov), None)
            if hit_key is not None:
                matched_f_keys.add(hit_key)
                entry = f_ov[hit_key]
                new_hand = str(entry.get("hand", rec.final_hand))
                new_finger = str(entry.get("finger", rec.final_finger))
                if new_hand not in valid_hands or new_finger not in valid_fingers:
                    raise ValueError(
                        f"Invalid manual finger override for {hit_key!r}: "
                        f"hand={new_hand!r}, finger={new_finger!r}"
                    )
                rec.final_hand = new_hand
                rec.final_finger = new_finger
                rec.final_confidence_tier = "manual"
                rec.provenance = "manual_override"
                counts["finger_overrides"] += 1
        unused_f = sorted(set(f_ov.keys()) - matched_f_keys)
        if unused_f:
            warnings.warn(
                f"Unused finger_overrides keys not matching any event: {unused_f}",
                stacklevel=2,
            )

    if isinstance(m_ov, dict):
        matched_m_keys: set[str] = set()
        for mt in measure_timings:
            key = str(mt.measure)
            if key in m_ov:
                matched_m_keys.add(key)
                entry = m_ov[key]
                if mt.auto_t_start_sec is None:
                    mt.auto_t_start_sec = mt.t_start_sec
                    mt.auto_t_end_sec = mt.t_end_sec
                if "t_start_sec" in entry:
                    mt.t_start_sec = float(entry["t_start_sec"])
                if "t_end_sec" in entry:
                    mt.t_end_sec = float(entry["t_end_sec"])
                mt.provenance = "manual_override"
                counts["measure_timing_overrides"] += 1
        unused_m = sorted(set(m_ov.keys()) - matched_m_keys)
        if unused_m:
            warnings.warn(
                f"Unused measure_timing_overrides keys not matching any measure: {unused_m}",
                stacklevel=2,
            )

    previous_end = -float("inf")
    for mt in measure_timings:
        if (not math.isfinite(mt.t_start_sec) or not math.isfinite(mt.t_end_sec)
                or mt.t_end_sec <= mt.t_start_sec or mt.t_start_sec < previous_end):
            raise ValueError("Measure timings must be finite, ordered, positive-duration and nonoverlapping.")
        previous_end = mt.t_end_sec

    return counts


def export_prediction_tables(
    predictions: list[PredictionRecord],
    csv_path: str | Path,
    json_path: str | Path,
    summary_meta: dict[str, Any],
) -> None:
    """Write musician-reviewable predictions.csv and full structured predictions.json."""
    csv_p = Path(csv_path)
    json_p = Path(json_path)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    json_p.parent.mkdir(parents=True, exist_ok=True)

    json_p.write_text(
        json.dumps(
            {
                "metadata": summary_meta,
                "predictions": [r.to_dict() for r in predictions],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    fieldnames = [
        "event_id",
        "alignment_status",
        "measure",
        "beat",
        "staff",
        "pitch_name",
        "midi_pitch",
        "onset_sec",
        "final_hand",
        "final_finger",
        "final_confidence_tier",
        "provenance",
        "auto_hand",
        "auto_finger",
        "auto_confidence_tier",
        "cost_margin",
        "abstain_reason",
        "top_candidates",
        "calibration_residual_kw",
        "score_note_id",
        "perf_event_id",
        "musician_verdict",
        "musician_corrected_finger",
        "musician_notes",
    ]
    with csv_p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in predictions:
            top_cands = "; ".join(
                f"{c.label}(du={c.delta_u_kw:.2f},cost={c.cost:.2f})"
                for c in r.candidate_fingers[:3]
            )
            writer.writerow(
                {
                    "event_id": r.event_id,
                    "alignment_status": r.alignment_status,
                    "measure": r.measure if r.measure is not None else "",
                    "beat": r.beat if r.beat is not None else "",
                    "staff": r.staff or "",
                    "pitch_name": r.pitch_name,
                    "midi_pitch": r.midi_pitch,
                    "onset_sec": f"{r.onset_sec:.3f}" if r.onset_sec is not None else "",
                    "final_hand": r.final_hand,
                    "final_finger": r.final_finger,
                    "final_confidence_tier": r.final_confidence_tier,
                    "provenance": r.provenance,
                    "auto_hand": r.auto_hand,
                    "auto_finger": r.auto_finger,
                    "auto_confidence_tier": r.auto_confidence_tier,
                    "cost_margin": f"{r.cost_margin:.3f}" if r.cost_margin is not None else "",
                    "abstain_reason": r.abstain_reason or "",
                    "top_candidates": top_cands,
                    "calibration_residual_kw": (
                        f"{r.calibration_residual_kw:.3f}"
                        if r.calibration_residual_kw is not None
                        else ""
                    ),
                    "score_note_id": r.score_note_id or "",
                    "perf_event_id": r.perf_event_id or "",
                    "musician_verdict": r.musician_verdict,
                    "musician_corrected_finger": r.musician_corrected_finger,
                    "musician_notes": r.musician_notes,
                }
            )


def _boxes_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    pad: float = 0.8,
) -> bool:
    return not (
        a[2] + pad < b[0]
        or b[2] + pad < a[0]
        or a[3] + pad < b[1]
        or b[3] + pad < a[1]
    )


def _format_score_finger_text(rec: PredictionRecord) -> tuple[str, tuple[float, float, float]]:
    """Return (display_string, rgb_0_to_1) for score overlay."""
    if rec.provenance == "manual_override" and rec.final_finger not in ("unknown", ""):
        return f"{rec.final_finger}*", (0.08, 0.50, 0.24)  # green
    if rec.final_confidence_tier == "high" and rec.final_finger not in ("unknown", ""):
        return f"{rec.final_finger}", (0.04, 0.31, 0.61)  # crisp dark blue
    if rec.final_confidence_tier == "low" and rec.final_finger not in ("unknown", ""):
        return f"({rec.final_finger}?)", (0.72, 0.32, 0.04)  # warm amber
    return "?", (0.42, 0.47, 0.54)  # slate gray


def render_annotated_score(
    score_pdf_path: str | Path,
    measures: list[ScoreMeasure],
    score_notes: list[ScoreNote],
    predictions: list[PredictionRecord],
    measure_timings: list[MeasureTiming],
    out_pdf_path: str | Path,
    out_excerpt_png_path: str | Path,
    manual_override_count: int = 0,
    excerpt_dpi: int = 240,
    alignment_ambiguous: bool = False,
) -> dict[str, Any]:
    """Overlay collision-aware fingering labels onto native PDF pages and export cropped excerpt PNG."""
    played_measures = {mt.measure for mt in measure_timings}
    played_pages = sorted({mt.page_index for mt in measure_timings})
    note_by_id = {n.score_note_id: n for n in score_notes}
    measure_by_num = {m.measure: m for m in measures}

    pred_by_score_id = {
        r.score_note_id: r
        for r in predictions
        if r.score_note_id is not None and r.measure in played_measures
    }

    # Collect occupied non-music text boxes, footer boundaries, & notehead boxes per page via pdfplumber
    occupied_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
    page_sizes: dict[int, tuple[float, float]] = {}
    footer_top_by_page: dict[int, float] = {}
    with pdfplumber.open(str(score_pdf_path)) as pdf:
        for p_idx in range(len(pdf.pages)):
            page = pdf.pages[p_idx]
            pw_cur, ph_cur = float(page.width), float(page.height)
            page_sizes[p_idx] = (pw_cur, ph_cur)
            p_ms_all = [m for m in measures if m.page_index == p_idx]
            max_sys_y1 = max((m.y1_pt for m in p_ms_all), default=ph_cur - 52.0)
            footer_tops: list[float] = []
            occ: list[tuple[float, float, float, float]] = []
            for c in page.chars:
                fn = c.get("fontname", "")
                txt = c.get("text", "")
                if "Doremi" not in fn and txt.strip():
                    c_top = float(c["top"])
                    if c_top > max_sys_y1 + 11.0:
                        footer_tops.append(c_top)
                    occ.append(
                        (
                            float(c["x0"]) - 1.0,
                            c_top - 1.0,
                            float(c["x1"]) + 1.0,
                            float(c["bottom"]) + 1.0,
                        )
                    )
            footer_top_by_page[p_idx] = min(footer_tops) if footer_tops else (ph_cur - 34.0)
            for sn in score_notes:
                if sn.page_index == p_idx:
                    occ.append(sn.bbox_pt)
                    if sn.is_arpeggiated:
                        # Reserve wavy arpeggio roll strip (~5 pt immediately left of notehead)
                        occ.append(
                            (
                                sn.bbox_pt[0] - 6.5,
                                sn.y_pt - 3.0,
                                sn.bbox_pt[0] - 1.0,
                                sn.y_pt + 3.0,
                            )
                        )
            occupied_by_page[p_idx] = occ

    reader = PdfReader(str(score_pdf_path))
    writer = PdfWriter()

    m_min = min(played_measures)
    m_max = max(played_measures)
    t_min = min(mt.t_start_sec for mt in measure_timings)
    t_max = max(mt.t_end_sec for mt in measure_timings)

    placed_label_count = 0
    for p_idx, page in enumerate(reader.pages):
        if p_idx not in played_pages:
            writer.add_page(page)
            continue

        pw, ph = page_sizes[p_idx]
        occ = list(occupied_by_page.get(p_idx, []))

        packet = io.BytesIO()
        c = canvas.Canvas(packet, pagesize=(pw, ph))

        # Top disclosure & legend bar on played page
        manual_legend = (
            f"Green n* = Manual ({manual_override_count})"
            if manual_override_count > 0
            else "Manual overrides: 0"
        )
        banner_txt = (
            f"Observed Fingering PoC (mm. {m_min}-{m_max}, {t_min:.1f}-{t_max:.1f}s)  |  "
            f"Blue n = High-conf Auto  |  Amber (n?) = Low-conf Auto  |  Gray ? = Unknown  |  "
            f"{manual_legend}"
        )
        if alignment_ambiguous:
            banner_txt = "AMBIGUOUS SCORE MATCH - candidate measures only | " + banner_txt
        c.setFillColor(Color(0.95, 0.97, 1.0, alpha=0.94))
        c.setStrokeColor(Color(0.20, 0.40, 0.72, alpha=0.6))
        c.setLineWidth(0.6)
        c.roundRect(38.0, ph - 24.0, pw - 76.0, 15.0, 3.0, stroke=1, fill=1)
        c.setFillColor(Color(0.08, 0.18, 0.36, alpha=1.0))
        c.setFont("Helvetica-Bold", 6.7)
        c.drawCentredString(pw * 0.5, ph - 18.8, banner_txt)

        # Group page predictions by chord_group_id in left-to-right order
        page_preds = [
            r
            for r in predictions
            if r.page_index == p_idx
            and r.score_note_id in note_by_id
            and r.measure in played_measures
        ]
        by_chord: dict[str, list[PredictionRecord]] = {}
        for r in page_preds:
            cg = r.chord_group_id or r.score_note_id or r.event_id
            by_chord.setdefault(cg, []).append(r)

        sorted_chords = sorted(
            by_chord.values(),
            key=lambda grp: min(note_by_id[r.score_note_id].x_pt for r in grp if r.score_note_id),  # type: ignore[arg-type]
        )

        for grp in sorted_chords:
            # Sort chord notes from HIGH pitch (smallest y_pt) to LOW pitch (largest y_pt)
            grp_sorted = sorted(
                grp,
                key=lambda r: note_by_id[r.score_note_id].y_pt,  # type: ignore[index]
            )
            first_sn = note_by_id[grp_sorted[0].score_note_id]  # type: ignore[index]
            sm = measure_by_num[first_sn.measure]
            is_chord = len(grp_sorted) >= 2

            if is_chord:
                # Place compact pitch-ordered labels immediately LEFT of the chord (or left of arpeggio roll)
                # at each note's y_pt (enforcing >= 6.4 pt vertical spacing so 2nd-interval labels never touch!)
                min_x0 = min(note_by_id[r.score_note_id].bbox_pt[0] for r in grp_sorted)  # type: ignore[index]
                has_arp = any(note_by_id[r.score_note_id].is_arpeggiated for r in grp_sorted)  # type: ignore[index]
                base_dx = -11.5 if has_arp else -6.5

                # Compute non-overlapping target y positions centered near each notehead's y_pt
                ys_target = [note_by_id[r.score_note_id].y_pt for r in grp_sorted]  # type: ignore[index]
                min_sep = 6.3
                for k_y in range(1, len(ys_target)):
                    if ys_target[k_y] - ys_target[k_y - 1] < min_sep:
                        ys_target[k_y] = ys_target[k_y - 1] + min_sep
                # Re-center stack vertically around mean notehead y
                shift_c = float(np.mean([note_by_id[r.score_note_id].y_pt for r in grp_sorted]) - np.mean(ys_target))  # type: ignore[index]
                ys_target = [y + shift_c for y in ys_target]

                # Choose horizontal offset left of chord that avoids collisions; fallback above/below staff if cramped
                chosen_boxes: list[tuple[float, float, float, float]] | None = None
                for try_dx in (base_dx, base_dx - 5.5, +11.0):
                    cand_boxes = []
                    ok = True
                    for r, yt in zip(grp_sorted, ys_target):
                        txt, _rgb = _format_score_finger_text(r)
                        tw = max(4.6, 3.5 * len(txt))
                        th = 5.8
                        cx = min_x0 + try_dx if try_dx < 0 else (min_x0 + 5.5 + try_dx)
                        bx = (cx - tw * 0.5, yt - th * 0.5, cx + tw * 0.5, yt + th * 0.5)
                        if bx[0] < sm.x0_pt + 1.5 or any(_boxes_overlap(bx, ob, pad=0.4) for ob in occ):
                            ok = False
                            break
                        cand_boxes.append(bx)
                    if ok:
                        chosen_boxes = cand_boxes
                        break

                if chosen_boxes is None:
                    # Fallback: vertical stack above treble staff or below bass staff clearing chord symbols
                    cx = first_sn.x_pt
                    if first_sn.staff == "treble":
                        start_y = min(sm.treble_top_pt - 6.5, ys_target[0] - 8.0)
                        for step_up in range(0, 36, 4):
                            top_base = start_y - step_up - (len(grp_sorted) - 1) * 6.3
                            cboxes = []
                            for idx_g, r in enumerate(grp_sorted):
                                txt, _ = _format_score_finger_text(r)
                                tw = max(4.6, 3.5 * len(txt))
                                yt = top_base + idx_g * 6.3
                                cboxes.append((cx - tw * 0.5, yt - 2.9, cx + tw * 0.5, yt + 2.9))
                            if not any(_boxes_overlap(b, ob, pad=0.4) for b in cboxes for ob in occ):
                                chosen_boxes = cboxes
                                break
                    else:
                        start_y = max(sm.bass_bot_pt + 7.5, ys_target[-1] + 8.0)
                        for step_dn in range(0, 36, 4):
                            bot_base = start_y + step_dn
                            cboxes = []
                            for idx_g, r in enumerate(grp_sorted):
                                txt, _ = _format_score_finger_text(r)
                                tw = max(4.6, 3.5 * len(txt))
                                yt = bot_base + idx_g * 6.3
                                cboxes.append((cx - tw * 0.5, yt - 2.9, cx + tw * 0.5, yt + 2.9))
                            if not any(_boxes_overlap(b, ob, pad=0.4) for b in cboxes for ob in occ):
                                chosen_boxes = cboxes
                                break

                if chosen_boxes is None:
                    chosen_boxes = []
                    for r, yt in zip(grp_sorted, ys_target):
                        txt, _ = _format_score_finger_text(r)
                        tw = max(4.6, 3.5 * len(txt))
                        cx = max(sm.x0_pt + 4.0, min_x0 + base_dx)
                        chosen_boxes.append((cx - tw * 0.5, yt - 2.9, cx + tw * 0.5, yt + 2.9))

                for r, bx in zip(grp_sorted, chosen_boxes):
                    occ.append(bx)
                    _draw_pdf_finger_pill(c, ph, r, bx)
                    placed_label_count += 1
            else:
                # Single note: place cleanly above treble staff/notehead or below bass staff/notehead
                r = grp_sorted[0]
                sn = note_by_id[r.score_note_id]  # type: ignore[index]
                txt, _ = _format_score_finger_text(r)
                tw = max(4.8, 3.6 * len(txt))
                th = 6.0
                cx = sn.x_pt

                chosen_bx: tuple[float, float, float, float] | None = None
                if sn.staff == "treble":
                    y0_try = min(sm.treble_top_pt - 6.8, sn.y_pt - 9.0)
                    for step in range(0, 34, 3):
                        yt = y0_try - step
                        bx = (cx - tw * 0.5, yt - th * 0.5, cx + tw * 0.5, yt + th * 0.5)
                        if not any(_boxes_overlap(bx, ob, pad=0.5) for ob in occ):
                            chosen_bx = bx
                            break
                else:
                    max_label_bot = footer_top_by_page[p_idx] - 2.2
                    y0_try = max(sm.bass_bot_pt + 6.8, sn.y_pt + 8.6)
                    for step in range(0, 34, 3):
                        yt = y0_try + step
                        bx = (cx - tw * 0.5, yt - th * 0.5, cx + tw * 0.5, yt + th * 0.5)
                        if bx[3] > max_label_bot:
                            break
                        if not any(_boxes_overlap(bx, ob, pad=0.5) for ob in occ):
                            chosen_bx = bx
                            break
                    if chosen_bx is None:
                        # Low ledger-line note near bottom page margin: place left of notehead or above bass staff
                        for alt_cx, alt_cy in (
                            (sn.bbox_pt[0] - 5.2 - tw * 0.5, min(sn.y_pt, max_label_bot - th * 0.5)),
                            (cx, sm.bass_top_pt - 7.0),
                        ):
                            bx = (alt_cx - tw * 0.5, alt_cy - th * 0.5, alt_cx + tw * 0.5, alt_cy + th * 0.5)
                            if (
                                bx[0] >= sm.x0_pt + 1.5
                                and bx[3] <= max_label_bot
                                and not any(_boxes_overlap(bx, ob, pad=0.4) for ob in occ)
                            ):
                                chosen_bx = bx
                                break

                if chosen_bx is None:
                    max_label_bot = footer_top_by_page[p_idx] - 2.2
                    yt = (
                        (sm.treble_top_pt - 8.0)
                        if sn.staff == "treble"
                        else min(sm.bass_bot_pt + 7.2, max_label_bot - th * 0.5)
                    )
                    chosen_bx = (cx - tw * 0.5, yt - th * 0.5, cx + tw * 0.5, yt + th * 0.5)

                occ.append(chosen_bx)
                _draw_pdf_finger_pill(c, ph, r, chosen_bx)
                placed_label_count += 1

        c.save()
        packet.seek(0)
        overlay_reader = PdfReader(packet)
        added_page = writer.add_page(page)
        added_page.merge_page(overlay_reader.pages[0])

    out_pdf_p = Path(out_pdf_path)
    out_pdf_p.parent.mkdir(parents=True, exist_ok=True)
    with out_pdf_p.open("wb") as f_out:
        writer.write(f_out)

    # Render cropped excerpt PNG around played systems (excluding bottom-margin purchaser watermarks!)
    scale = excerpt_dpi / 72.0
    doc = pdfium.PdfDocument(str(out_pdf_p))
    cropped_strips: list[Image.Image] = []
    crop_meta_by_page: dict[int, tuple[int, int, int, int, float]] = {}
    try:
        for p_idx in played_pages:
            p_measures = [m for m in measures if m.page_index == p_idx and m.measure in played_measures]
            if not p_measures:
                continue
            pw, ph = page_sizes[p_idx]
            min_y_pt = max(4.0, min(m.y0_pt for m in p_measures) - 36.0)
            if min_y_pt < 150.0:
                min_y_pt = 4.0
            footer_top = footer_top_by_page.get(p_idx, ph - 34.0)
            max_y_pt = min(footer_top - 1.2, max(m.y1_pt for m in p_measures) + 34.0)
            min_x_pt = 28.0
            max_x_pt = pw - 28.0

            pil_full: Image.Image = doc[p_idx].render(scale=scale).to_pil().convert("RGB")
            x0_px = int(round(min_x_pt * scale))
            y0_px = int(round(min_y_pt * scale))
            x1_px = int(round(max_x_pt * scale))
            y1_px = int(round(max_y_pt * scale))
            cropped = pil_full.crop((x0_px, y0_px, x1_px, y1_px))
            cropped_strips.append(cropped)
            crop_meta_by_page[p_idx] = (x0_px, y0_px, x1_px, y1_px, scale)
    finally:
        doc.close()

    out_png_p = Path(out_excerpt_png_path)
    out_png_p.parent.mkdir(parents=True, exist_ok=True)
    if len(cropped_strips) == 1:
        cropped_strips[0].save(out_png_p)
    elif cropped_strips:
        tot_w = max(im.width for im in cropped_strips)
        tot_h = sum(im.height for im in cropped_strips)
        stacked = Image.new("RGB", (tot_w, tot_h), (255, 255, 255))
        y_cur = 0
        for im in cropped_strips:
            stacked.paste(im, (0, y_cur))
            y_cur += im.height
        stacked.save(out_png_p)

    return {
        "annotated_pdf_path": str(out_pdf_p),
        "annotated_excerpt_png_path": str(out_png_p),
        "placed_score_label_count": placed_label_count,
        "crop_meta_by_page": crop_meta_by_page,
    }


def _draw_pdf_finger_pill(
    c: canvas.Canvas,
    page_height: float,
    rec: PredictionRecord,
    bbox_top_left: tuple[float, float, float, float],
) -> None:
    txt, (r_col, g_col, b_col) = _format_score_finger_text(rec)
    x0, y0, x1, y1 = bbox_top_left
    cx = 0.5 * (x0 + x1)
    cy_rl = page_height - 0.5 * (y0 + y1)
    w = x1 - x0
    h = y1 - y0

    # Subtle white knockout halo pill so staff lines or barlines never obscure the digit
    c.setFillColor(Color(1.0, 1.0, 1.0, alpha=0.90))
    c.roundRect(cx - w * 0.5 - 0.5, cy_rl - h * 0.5 - 0.3, w + 1.0, h + 0.6, 1.8, stroke=0, fill=1)

    font_name = "Helvetica-Bold" if rec.final_confidence_tier != "unknown" else "Helvetica"
    font_size = 6.2 if len(txt) <= 2 else 5.4
    c.setFillColor(Color(r_col, g_col, b_col, alpha=1.0))
    c.setFont(font_name, font_size)
    c.drawCentredString(cx, cy_rl - font_size * 0.34, txt)


def render_teaching_video(
    video_path: str | Path,
    annotated_pdf_path: str | Path,
    measures: list[ScoreMeasure],
    score_notes: list[ScoreNote],
    predictions: list[PredictionRecord],
    measure_timings: list[MeasureTiming],
    frame_poses: list[FramePose],
    frame_calibrations: list[FrameCalibration],
    out_mp4_path: str | Path,
    temp_dir: str | Path = ".local/cache",
    manual_override_count: int = 0,
    rotate_hands_180_to_pianist_pov: bool = True,
    alignment_ambiguous: bool = False,
) -> dict[str, Any]:
    """Render 1920x1080 VFR-faithful split-screen teaching video muxed with original audio."""
    t0 = time.perf_counter()
    out_p = Path(out_mp4_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    tmp_p = Path(temp_dir)
    tmp_p.mkdir(parents=True, exist_ok=True)
    video_only_mp4 = tmp_p / "video_only_vfr.mp4"

    played_measures = {mt.measure for mt in measure_timings}
    measure_by_num = {m.measure: m for m in measures}
    note_by_id = {n.score_note_id: n for n in score_notes}

    footer_top_vid: dict[int, float] = {}
    with pdfplumber.open(str(annotated_pdf_path)) as pdf_v:
        for p_idx in range(len(pdf_v.pages)):
            pg_v = pdf_v.pages[p_idx]
            ph_v = float(pg_v.height)
            p_ms_all = [m for m in measures if m.page_index == p_idx]
            max_sys_y1 = max((m.y1_pt for m in p_ms_all), default=ph_v - 52.0)
            ftops = [
                float(c["top"])
                for c in pg_v.chars
                if "Doremi" not in c.get("fontname", "")
                and c.get("text", "").strip()
                and float(c["top"]) > max_sys_y1 + 11.0
            ]
            footer_top_vid[p_idx] = min(ftops) if ftops else (ph_v - 34.0)

    # Pre-render each played score page (tightly cropped to played systems, excluding bottom watermark)
    # onto a 960 x 1080 right-pane RGB canvas with exact PDF-point -> right-pane-pixel transform!
    score_dpi = 240
    pdf_scale = score_dpi / 72.0
    doc = pdfium.PdfDocument(str(annotated_pdf_path))
    right_canvases: dict[int, np.ndarray] = {}
    pt_to_right_px: dict[int, tuple[float, float, float]] = {}  # page_idx -> (s_fit, off_x, off_y)
    try:
        played_pages = sorted({mt.page_index for mt in measure_timings})
        for p_idx in played_pages:
            p_ms = [m for m in measures if m.page_index == p_idx and m.measure in played_measures]
            pil_page = doc[p_idx].render(scale=pdf_scale).to_pil().convert("RGB")
            page_bgr = cv2.cvtColor(np.asarray(pil_page), cv2.COLOR_RGB2BGR)
            ph_pt = pil_page.height / pdf_scale
            pw_pt = pil_page.width / pdf_scale

            min_y_pt = 4.0 if min(m.y0_pt for m in p_ms) < 150.0 else max(4.0, min(m.y0_pt for m in p_ms) - 36.0)
            f_top = footer_top_vid.get(p_idx, ph_pt - 34.0)
            max_y_pt = min(f_top - 1.2, max(m.y1_pt for m in p_ms) + 34.0)
            min_x_pt = 26.0
            max_x_pt = pw_pt - 26.0

            x0_s = int(round(min_x_pt * pdf_scale))
            y0_s = int(round(min_y_pt * pdf_scale))
            x1_s = int(round(max_x_pt * pdf_scale))
            y1_s = int(round(max_y_pt * pdf_scale))
            crop_bgr = page_bgr[y0_s:y1_s, x0_s:x1_s]

            # Fit crop_bgr into 960 x 1080 with 16 px padding
            pane_w, pane_h = 960, 1080
            pad = 14
            fit_scale = min((pane_w - 2 * pad) / crop_bgr.shape[1], (pane_h - 2 * pad) / crop_bgr.shape[0])
            nw = int(round(crop_bgr.shape[1] * fit_scale))
            nh = int(round(crop_bgr.shape[0] * fit_scale))
            resized = cv2.resize(crop_bgr, (nw, nh), interpolation=cv2.INTER_AREA)

            pane_bg = np.full((pane_h, pane_w, 3), 248, dtype=np.uint8)
            ox = (pane_w - nw) // 2
            oy = (pane_h - nh) // 2
            pane_bg[oy : oy + nh, ox : ox + nw] = resized
            # Subtle divider border on left edge of score pane
            cv2.line(pane_bg, (0, 0), (0, pane_h), (195, 200, 210), 2)

            right_canvases[p_idx] = pane_bg
            # Transform from PDF pt (x_pt, y_pt) -> right-pane px:
            # px_x = ox + (x_pt * pdf_scale - x0_s) * fit_scale
            s_comb = pdf_scale * fit_scale
            pt_to_right_px[p_idx] = (s_comb, ox - x0_s * fit_scale, oy - y0_s * fit_scale)
    finally:
        doc.close()

    default_page_idx = sorted(right_canvases.keys())[0]

    # Index matched/score attack records for quick per-frame overlay lookup
    active_preds = [
        r for r in predictions if r.onset_sec is not None and r.alignment_status == "matched"
    ]

    m_min = min(played_measures)
    m_max = max(played_measures)
    emitted_cnt = sum(
        1
        for r in predictions
        if r.alignment_status in ("matched", "unmatched_score")
        and r.final_confidence_tier != "unknown"
    )
    total_score_cnt = sum(
        1 for r in predictions if r.alignment_status in ("matched", "unmatched_score")
    )

    in_container = av.open(str(video_path))
    out_container = av.open(str(video_only_mp4), mode="w")
    in_pts_sec_list: list[float] = []
    out_pts_sec_list: list[float] = []

    try:
        in_v = next(s for s in in_container.streams if s.type == "video")
        src_tb = in_v.time_base
        assert src_tb is not None

        out_v = out_container.add_stream("libx264", rate=in_v.average_rate or 30)
        out_v.width = 1920
        out_v.height = 1080
        out_v.pix_fmt = "yuv420p"
        out_v.time_base = src_tb
        out_v.options = {"crf": "19", "preset": "fast"}

        first_raw_pts: int | None = None

        for idx, frame in enumerate(in_container.decode(in_v)):
            if frame.pts is None:
                continue
            if first_raw_pts is None:
                first_raw_pts = int(frame.pts)
            rel_pts_ticks = int(frame.pts) - first_raw_pts
            t_sec = float(rel_pts_ticks * src_tb)
            in_pts_sec_list.append(t_sec)

            raw_bgr = frame.to_ndarray(format="bgr24")
            src_h, src_w = raw_bgr.shape[:2]
            fp = frame_poses[idx]
            cal = frame_calibrations[idx]

            # --- LEFT PANE (960 x 1080): Full-width aspect-preserving letterbox (960 x 540 at y=270..810) ---
            left_pane = np.full((1080, 960, 3), (22, 25, 32), dtype=np.uint8)
            if rotate_hands_180_to_pianist_pov:
                disp_src = cv2.rotate(raw_bgr, cv2.ROTATE_180)
            else:
                disp_src = raw_bgr

            vid_scaled = cv2.resize(disp_src, (960, 540), interpolation=cv2.INTER_AREA)
            y_vid0 = 270
            left_pane[y_vid0 : y_vid0 + 540, 0:960] = vid_scaled

            def raw_to_left_px(rx: float, ry: float) -> tuple[int, int]:
                if rotate_hands_180_to_pianist_pov:
                    rx = (src_w - 1.0) - rx
                    ry = (src_h - 1.0) - ry
                lx = int(round(rx * (960.0 / src_w)))
                ly = y_vid0 + int(round(ry * (540.0 / src_h)))
                return (lx, ly)

            # Draw subtle calibrated C-octave ticks & currently attacked keys when reliable
            now_attacks = [
                r
                for r in active_preds
                if r.onset_sec is not None and (r.onset_sec - 0.04) <= t_sec <= (r.onset_sec + 0.34)
            ]

            if cal.reliable and cal.h_white is not None and cal.h_black is not None:
                hw_inv = np.linalg.inv(np.asarray(cal.h_white, dtype=np.float64))
                hb_inv = np.linalg.inv(np.asarray(cal.h_black, dtype=np.float64))

                # Subtle octave markers C2..C5 along back of keys
                for c_midi in (36, 48, 60, 72):
                    uc = midi_to_canonical_u_center(c_midi)
                    p_raw = (hw_inv @ np.array([uc, 0.90, 1.0])).ravel()
                    if abs(p_raw[2]) > 1e-9:
                        lx, ly = raw_to_left_px(float(p_raw[0] / p_raw[2]), float(p_raw[1] / p_raw[2]))
                        if 10 <= lx < 950 and y_vid0 + 8 <= ly < y_vid0 + 532:
                            cv2.putText(
                                left_pane,
                                midi_to_name(c_midi),
                                (lx - 11, ly),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.38,
                                (130, 235, 150),
                                1,
                                cv2.LINE_AA,
                            )

                # Highlight currently attacked key contact zones
                for r in now_attacks:
                    uc = midi_to_canonical_u_center(r.midi_pitch)
                    if is_black_key(r.midi_pitch):
                        poly_uv = np.array(
                            [[uc - 0.28, 0.04, 1.0], [uc + 0.28, 0.04, 1.0], [uc + 0.28, 0.60, 1.0], [uc - 0.28, 0.60, 1.0]]
                        )
                        p_px = (hb_inv @ poly_uv.T).T
                    else:
                        poly_uv = np.array(
                            [[uc - 0.44, 0.58, 1.0], [uc + 0.44, 0.58, 1.0], [uc + 0.44, 0.98, 1.0], [uc - 0.44, 0.98, 1.0]]
                        )
                        p_px = (hw_inv @ poly_uv.T).T
                    pts_l = np.array(
                        [raw_to_left_px(float(q[0] / q[2]), float(q[1] / q[2])) for q in p_px],
                        dtype=np.int32,
                    )
                    overlay_k = left_pane.copy()
                    if r.provenance == "manual_override" or r.final_confidence_tier == "manual":
                        k_col = (55, 165, 35)
                    elif r.final_confidence_tier == "high":
                        k_col = (245, 150, 40)
                    elif r.final_confidence_tier == "low":
                        k_col = (40, 175, 245)
                    else:
                        k_col = (120, 125, 135)
                    cv2.fillConvexPoly(overlay_k, pts_l, k_col)
                    cv2.addWeighted(overlay_k, 0.34, left_pane, 0.66, 0, left_pane)

            # Draw subtle anatomical fingertip dots + upright attack badges
            tip_screen_pos: dict[tuple[str, int], tuple[int, int]] = {}
            for h_obs in fp.hands:
                dot_col = (240, 200, 70) if h_obs.resolved_hand == "R" else (110, 165, 250)
                for f_num, j_name in FINGERTIP_JOINTS.items():
                    lm = h_obs.landmarks.get(j_name)
                    if lm is None or lm[2] < 0.35:
                        continue
                    lx, ly = raw_to_left_px(lm[0], lm[1])
                    if 0 <= lx < 960 and y_vid0 <= ly < y_vid0 + 540:
                        cv2.circle(left_pane, (lx, ly), 4, dot_col, -1, cv2.LINE_AA)
                        if h_obs.resolved_hand in ("L", "R"):
                            tip_screen_pos[(h_obs.resolved_hand, f_num)] = (lx, ly)

            # Upright fingertip attack pills during [onset - 0.04s, onset + 0.34s]
            drawn_badge_boxes: list[tuple[int, int, int, int]] = []
            for r in now_attacks:
                if r.final_hand in ("L", "R") and r.final_finger.isdigit():
                    f_i = int(r.final_finger)
                    pos = tip_screen_pos.get((r.final_hand, f_i))
                    if r.provenance == "manual_override" or r.final_confidence_tier == "manual":
                        lbl = f"{r.final_hand}{f_i}*"
                    elif r.final_confidence_tier == "low":
                        lbl = f"{r.final_hand}{f_i}?"
                    else:
                        lbl = f"{r.final_hand}{f_i}"
                else:
                    pos = None
                    lbl = "?"

                if pos is None and cal.reliable and cal.h_white is not None:
                    hw_inv = np.linalg.inv(np.asarray(cal.h_white, dtype=np.float64))
                    uc = midi_to_canonical_u_center(r.midi_pitch)
                    q = (hw_inv @ np.array([uc, 0.65, 1.0])).ravel()
                    if abs(q[2]) > 1e-9:
                        pos = raw_to_left_px(float(q[0] / q[2]), float(q[1] / q[2]))

                if pos is not None:
                    bx_c, by_c = pos[0], pos[1] - 18
                    # Avoid pill stacking collision
                    for _ in range(4):
                        cand_b = (bx_c - 22, by_c - 11, bx_c + 22, by_c + 11)
                        if any(
                            not (cand_b[2] < ob[0] or ob[2] < cand_b[0] or cand_b[3] < ob[1] or ob[3] < cand_b[1])
                            for ob in drawn_badge_boxes
                        ):
                            by_c -= 22
                        else:
                            break
                    by_c = max(y_vid0 + 14, min(y_vid0 + 526, by_c))
                    drawn_badge_boxes.append((bx_c - 22, by_c - 11, bx_c + 22, by_c + 11))

                    if r.provenance == "manual_override" or r.final_confidence_tier == "manual":
                        bg_c = (45, 145, 25)  # BGR rich green
                    elif r.final_confidence_tier == "high":
                        bg_c = (185, 95, 15)  # BGR rich blue
                    elif r.final_confidence_tier == "low":
                        bg_c = (15, 120, 215)  # BGR amber
                    else:
                        bg_c = (105, 110, 120)
                    (tw, th), _ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 2)
                    p0 = (bx_c - tw // 2 - 7, by_c - th // 2 - 5)
                    p1 = (bx_c + tw // 2 + 7, by_c + th // 2 + 5)
                    cv2.rectangle(left_pane, p0, p1, (255, 255, 255), -1)
                    cv2.rectangle(left_pane, (p0[0] + 1, p0[1] + 1), (p1[0] - 1, p1[1] - 1), bg_c, -1)
                    cv2.putText(
                        left_pane,
                        lbl,
                        (bx_c - tw // 2, by_c + th // 2 - 1),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.52,
                        (255, 255, 255),
                        2,
                        cv2.LINE_AA,
                    )

            # Determine active MeasureTiming at t_sec
            active_mt: MeasureTiming | None = None
            for mt in measure_timings:
                if mt.t_start_sec - 0.05 <= t_sec < mt.t_end_sec:
                    active_mt = mt
                    break

            # Top letterbox HUD (y = 0..270)
            cv2.putText(
                left_pane,
                "Observed Piano Fingering — Proof of Concept",
                (28, 52),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.82,
                (242, 245, 250),
                2,
                cv2.LINE_AA,
            )
            pov_str = (
                "View: Pianist POV (180 deg rotated, uncropped)  |  Bass Left -> Treble Right"
                if rotate_hands_180_to_pianist_pov
                else "View: Raw Camera Orientation"
            )
            cv2.putText(
                left_pane,
                pov_str,
                (28, 90),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.53,
                (175, 190, 212),
                1,
                cv2.LINE_AA,
            )

            m_label = (
                f"Measure {active_mt.measure} (mm. {m_min}-{m_max})"
                if active_mt is not None
                else ("Pre-performance" if t_sec < measure_timings[0].t_start_sec else "Post-performance")
            )
            if alignment_ambiguous:
                m_label = "AMBIGUOUS SCORE MATCH | " + m_label
            cv2.putText(
                left_pane,
                f"Time: {t_sec:5.2f} s   |   {m_label}",
                (28, 145),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                (110, 215, 255),
                2,
                cv2.LINE_AA,
            )

            cal_txt = (
                f"Keybed Calibration: OK (residual {cal.residual_kw:.2f} key-widths, {cal.inlier_count} anchors)"
                if cal.reliable
                else f"Keybed Calibration: Abstaining ({cal.reason or 'uncalibrated'})"
            )
            cal_col = (110, 235, 140) if cal.reliable else (95, 165, 250)
            cv2.putText(
                left_pane,
                cal_txt,
                (28, 188),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                cal_col,
                1,
                cv2.LINE_AA,
            )
            prov_txt = (
                f"Coverage: {emitted_cnt}/{total_score_cnt} attacks labeled  |  "
                f"Automatic stages + {manual_override_count} manual overrides"
            )
            cv2.putText(
                left_pane,
                prov_txt,
                (28, 224),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                (165, 178, 195),
                1,
                cv2.LINE_AA,
            )

            # Bottom letterbox HUD (y = 810..1080): Recent attacks readout & color legend
            recent = [
                r
                for r in active_preds
                if r.onset_sec is not None and (t_sec - 0.65) <= r.onset_sec <= (t_sec + 0.04)
            ]
            recent.sort(key=lambda r: (r.onset_sec or 0.0, r.midi_pitch))
            cv2.putText(
                left_pane,
                "Active / Recent Note Attacks:",
                (28, 858),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.58,
                (205, 215, 230),
                1,
                cv2.LINE_AA,
            )
            if recent:
                tokens = []
                for r in recent[-8:]:
                    f_disp = (
                        f"{r.final_hand}{r.final_finger}"
                        if r.final_finger != "unknown"
                        else "?"
                    )
                    if r.provenance == "manual_override" or r.final_confidence_tier == "manual":
                        f_disp += "*"
                    elif r.final_confidence_tier == "low":
                        f_disp += "?"
                    tokens.append(f"{r.pitch_name}[{f_disp}]")
                attack_line = "  ".join(tokens)
            else:
                attack_line = "(none)"
            cv2.putText(
                left_pane,
                attack_line,
                (28, 902),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.64,
                (250, 250, 252),
                2,
                cv2.LINE_AA,
            )

            # Color legend pills at bottom
            legend_items = [
                ("High-conf Auto", (185, 95, 15)),
                ("Low-conf Auto (?)", (15, 120, 215)),
                ("Abstained (?)", (105, 110, 120)),
            ]
            if manual_override_count > 0:
                legend_items.append(("Manual (*)", (45, 145, 25)))
            lx_step = 225 if len(legend_items) >= 4 else 250
            lx_cur = 28
            for lg_txt, lg_col in legend_items:
                cv2.rectangle(left_pane, (lx_cur, 962), (lx_cur + 18, 980), lg_col, -1)
                cv2.putText(
                    left_pane,
                    lg_txt,
                    (lx_cur + 26, 977),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.50,
                    (195, 205, 220),
                    1,
                    cv2.LINE_AA,
                )
                lx_cur += lx_step

            cv2.putText(
                left_pane,
                "Pending musician evaluation — uncertain predictions preserved as '?'",
                (28, 1028),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (140, 152, 170),
                1,
                cv2.LINE_AA,
            )

            # --- RIGHT PANE (960 x 1080): Cropped score with active measure highlight & notehead pulse ---
            cur_page = active_mt.page_index if active_mt is not None else default_page_idx
            right_pane = right_canvases[cur_page].copy()
            s_comb, off_x, off_y = pt_to_right_px[cur_page]

            if active_mt is not None:
                sm = measure_by_num[active_mt.measure]
                rx0 = int(round(sm.x0_pt * s_comb + off_x))
                ry0 = int(round((sm.y0_pt - 4.0) * s_comb + off_y))
                rx1 = int(round(sm.x1_pt * s_comb + off_x))
                ry1 = int(round((sm.y1_pt + 4.0) * s_comb + off_y))

                hl = right_pane.copy()
                # Soft golden-amber measure highlight fill + crisp blue border
                cv2.rectangle(hl, (rx0, ry0), (rx1, ry1), (170, 232, 255), -1)
                cv2.addWeighted(hl, 0.24, right_pane, 0.76, 0, right_pane)
                cv2.rectangle(right_pane, (rx0, ry0), (rx1, ry1), (205, 110, 25), 2)

            # Active notehead ring on score during [onset - 0.04s, onset + 0.30s]
            for r in now_attacks:
                if r.page_index == cur_page and r.score_note_id in note_by_id:
                    sn = note_by_id[r.score_note_id]
                    nx = int(round(sn.x_pt * s_comb + off_x))
                    ny = int(round(sn.y_pt * s_comb + off_y))
                    cv2.circle(right_pane, (nx, ny), 9, (20, 120, 245), 2, cv2.LINE_AA)

            comp_bgr = np.hstack([left_pane, right_pane])
            out_frame = av.VideoFrame.from_ndarray(comp_bgr, format="bgr24")
            out_frame.pts = rel_pts_ticks
            out_frame.time_base = src_tb
            out_pts_sec_list.append(float(out_frame.pts * src_tb))

            for pkt in out_v.encode(out_frame):
                out_container.mux(pkt)

        for pkt in out_v.encode(None):
            out_container.mux(pkt)
    finally:
        in_container.close()
        out_container.close()

    def _measure_av_offset(media_p: Path) -> float:
        c_chk = av.open(str(media_p))
        try:
            vs = next((s for s in c_chk.streams if s.type == "video"), None)
            as_ = next((s for s in c_chk.streams if s.type == "audio"), None)
            vf_pts = 0.0
            af_pts = 0.0
            if vs is not None:
                for fr in c_chk.decode(vs):
                    if fr.pts is not None and fr.time_base is not None:
                        vf_pts = float(fr.pts * fr.time_base)
                        break
        finally:
            c_chk.close()

        c_chk2 = av.open(str(media_p))
        try:
            as_ = next((s for s in c_chk2.streams if s.type == "audio"), None)
            if as_ is not None:
                for fr in c_chk2.decode(as_):
                    if fr.pts is not None and fr.time_base is not None:
                        af_pts = float(fr.pts * fr.time_base)
                        break
        finally:
            c_chk2.close()
        return af_pts - vf_pts

    orig_av_offset = _measure_av_offset(Path(video_path))

    # Mux VFR H.264 video stream with untouched original AAC audio stream via bundled imageio-ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    def _mux_with_itsoffset(audio_itsoffset: float) -> None:
        cmd = [ffmpeg_exe, "-y", "-i", str(video_only_mp4)]
        if abs(audio_itsoffset) > 1e-6:
            cmd.extend(["-itsoffset", f"{audio_itsoffset:.6f}"])
        cmd.extend(
            [
                "-i",
                str(video_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                str(out_p),
            ]
        )
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    _mux_with_itsoffset(0.0)
    muxed_av_offset = _measure_av_offset(out_p)
    if abs(muxed_av_offset - orig_av_offset) > 0.005:
        _mux_with_itsoffset(orig_av_offset - muxed_av_offset)
        muxed_av_offset = _measure_av_offset(out_p)

    av_offset_err_ms = abs(muxed_av_offset - orig_av_offset) * 1000.0

    # Verify VFR presentation timestamp fidelity on muxed output MP4
    muxed_pts: list[float] = []
    ver_c = av.open(str(out_p))
    try:
        vv = next(s for s in ver_c.streams if s.type == "video")
        vtb = vv.time_base
        assert vtb is not None
        p0_ver: int | None = None
        for fr in ver_c.decode(vv):
            if fr.pts is not None:
                if p0_ver is None:
                    p0_ver = int(fr.pts)
                muxed_pts.append(float((int(fr.pts) - p0_ver) * vtb))
    finally:
        ver_c.close()

    max_pts_err_ms = _validate_output_timing(in_pts_sec_list, muxed_pts, av_offset_err_ms)

    elapsed = time.perf_counter() - t0
    return {
        "teaching_video_path": str(out_p),
        "encoded_frame_count": len(out_pts_sec_list),
        "muxed_frame_count": len(muxed_pts),
        "max_vfr_pts_error_ms": round(max_pts_err_ms, 4),
        "av_offset_error_ms": round(av_offset_err_ms, 4),
        "runtime_sec": round(elapsed, 3),
    }
