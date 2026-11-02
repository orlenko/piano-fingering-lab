"""Stage 2: Permissive vector PDF score & coordinate parser (pdfplumber + pypdfium2)."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pdfplumber
from PIL import Image, ImageDraw
import pypdfium2 as pdfium

from .models import ScoreMeasure, ScoreNote, midi_to_name

# Diatonic step 0 = top line of staff:
# Treble top line = F5 (diatonic index: C0=0 -> F5 = 5*7 + 3 = 38)
# Bass top line   = A3 (diatonic index: C0=0 -> A3 = 3*7 + 5 = 26)
DIATONIC_TO_SEMITONE = (0, 2, 4, 5, 7, 9, 11)  # C, D, E, F, G, A, B
TREBLE_TOP_DIATONIC = 5 * 7 + 3  # F5 = 38
BASS_TOP_DIATONIC = 3 * 7 + 5    # A3 = 26

NOTEHEAD_CHARS = {"Ï": "filled", "ú": "half", "w": "whole"}
ACCIDENTAL_CHARS = {"b": -1, "#": +1, "n": 0}


def diatonic_to_midi(diatonic_index: int, alter: int = 0) -> int:
    """Convert absolute diatonic index (C0=0) and accidental alter (-1, 0, +1) to MIDI pitch."""
    octave = diatonic_index // 7
    degree = diatonic_index % 7
    # C0 is MIDI 12
    return 12 * (octave + 1) + DIATONIC_TO_SEMITONE[degree] + alter


@dataclass
class _StaffGeom:
    lines_y: list[float]  # 5 sorted y coordinates (top-left origin)
    x0: float
    x1: float

    @property
    def top_y(self) -> float:
        return self.lines_y[0]

    @property
    def bot_y(self) -> float:
        return self.lines_y[-1]

    @property
    def space(self) -> float:
        return (self.lines_y[-1] - self.lines_y[0]) / 4.0


def _cluster_y(vals: list[float], tol: float = 0.8) -> list[float]:
    if not vals:
        return []
    s = sorted(vals)
    groups: list[list[float]] = [[s[0]]]
    for v in s[1:]:
        if abs(v - groups[-1][-1]) <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def _extract_systems_on_page(page: pdfplumber.page.Page) -> list[tuple[_StaffGeom, _StaffGeom]]:
    """Detect 5-line staves and pair into (treble, bass) grand-staff systems."""
    hlines = [
        ln
        for ln in page.lines
        if abs(ln["top"] - ln["bottom"]) < 1.0 and (ln["x1"] - ln["x0"]) > 150.0
    ]
    if not hlines:
        return []

    ys = _cluster_y([float(ln["top"]) for ln in hlines], tol=0.8)
    staves: list[_StaffGeom] = []
    idx = 0
    while idx + 4 < len(ys):
        chunk = ys[idx : idx + 5]
        diffs = [chunk[k + 1] - chunk[k] for k in range(4)]
        mean_d = sum(diffs) / 4.0
        if 2.5 <= mean_d <= 8.0 and all(abs(d - mean_d) < 0.35 for d in diffs):
            matching = [
                ln for ln in hlines if min(abs(float(ln["top"]) - y) for y in chunk) < 0.9
            ]
            x0 = min(float(ln["x0"]) for ln in matching)
            x1 = max(float(ln["x1"]) for ln in matching)
            staves.append(_StaffGeom(lines_y=chunk, x0=x0, x1=x1))
            idx += 5
        else:
            idx += 1

    systems: list[tuple[_StaffGeom, _StaffGeom]] = []
    for k in range(0, len(staves) - 1, 2):
        systems.append((staves[k], staves[k + 1]))
    return systems


def _extract_printed_system_measure_numbers(
    page: pdfplumber.page.Page,
    systems: list[tuple[_StaffGeom, _StaffGeom]],
) -> dict[int, int]:
    """Read printed measure numbers positioned immediately above the left start of each system."""
    result: dict[int, int] = {}
    non_music_digits = [
        c
        for c in page.chars
        if "Doremi" not in c.get("fontname", "") and c.get("text", "").isdigit()
    ]
    for sys_idx, (treble, _bass) in enumerate(systems):
        # Measure numbers sit near x0 (within 25 pt of treble.x0) and 8..24 pt above treble.top_y.
        cands = [
            c
            for c in non_music_digits
            if abs(float(c["x0"]) - treble.x0) < 22.0
            and (treble.top_y - 26.0) <= float(c["top"]) <= (treble.top_y - 6.0)
        ]
        if cands:
            cands.sort(key=lambda c: float(c["x0"]))
            # Group contiguous digits on same baseline
            first_y = float(cands[0]["top"])
            digits = "".join(
                c["text"] for c in cands if abs(float(c["top"]) - first_y) < 3.0
            )
            if digits.isdigit():
                val = int(digits)
                if val >= 2:
                    result[sys_idx] = val
    return result


def parse_vector_score_pdf(
    pdf_path: str | Path,
    out_json_path: str | Path | None = None,
    diagnostics_dir: str | Path | None = None,
) -> tuple[list[ScoreMeasure], list[ScoreNote], dict[str, Any]]:
    """Parse a digitally typeset vector score PDF into native-coordinate measures and notes."""
    measures: list[ScoreMeasure] = []
    all_notes: list[ScoreNote] = []
    printed_anchor_checks: list[dict[str, Any]] = []
    measure_beat_checks: list[dict[str, Any]] = []

    current_measure_num = 1
    current_beats_per_bar = 4
    current_beat_unit = 4
    # Key signature accidentals by degree (0=C..6=B), detected from system 1 key signature
    key_sig_alters: dict[int, int] = {}
    font_y_offset: float | None = None

    with pdfplumber.open(str(pdf_path)) as pdf:
        global_sys_idx = 0
        for page_idx, page in enumerate(pdf.pages):
            systems = _extract_systems_on_page(page)
            if not systems:
                continue

            printed_nums = _extract_printed_system_measure_numbers(page, systems)
            music_chars = [c for c in page.chars if "Doremi" in c.get("fontname", "")]

            # Calibrate font vertical offset & key signature on first notation system if not yet set
            if font_y_offset is None:
                tr0, _bs0 = systems[0]
                first_nhs = [
                    c
                    for c in music_chars
                    if c["text"] in NOTEHEAD_CHARS
                    and (tr0.top_y - 25.0) <= float(c["top"]) <= (tr0.bot_y + 25.0)
                ]
                # Key signature flats/sharps sit between clef (x ~ tr0.x0..tr0.x0+16) and first notehead
                first_nh_x = min((float(c["x0"]) for c in first_nhs), default=tr0.x0 + 45.0)
                ks_flats = [
                    c
                    for c in music_chars
                    if c["text"] == "b"
                    and tr0.x0 + 10.0 <= float(c["x0"]) < first_nh_x - 8.0
                    and (tr0.top_y - 12.0) <= float(c["top"]) <= (tr0.bot_y + 12.0)
                ]
                ks_sharps = [
                    c
                    for c in music_chars
                    if c["text"] == "#"
                    and tr0.x0 + 10.0 <= float(c["x0"]) < first_nh_x - 8.0
                    and (tr0.top_y - 12.0) <= float(c["top"]) <= (tr0.bot_y + 12.0)
                ]
                if ks_flats:
                    # First flat in standard treble key signature is always B4 (middle line = lines_y[2])
                    ks_flats.sort(key=lambda c: float(c["x0"]))
                    b4_line_y = tr0.lines_y[2]
                    font_y_offset = b4_line_y - float(ks_flats[0]["top"])
                    flat_order_degrees = [6, 2, 5, 1, 4, 0, 3]  # B, E, A, D, G, C, F
                    for idx_f in range(min(len(ks_flats), 7)):
                        key_sig_alters[flat_order_degrees[idx_f]] = -1
                elif ks_sharps:
                    # First sharp in standard treble key signature is always F5 (top line = lines_y[0])
                    ks_sharps.sort(key=lambda c: float(c["x0"]))
                    f5_line_y = tr0.lines_y[0]
                    font_y_offset = f5_line_y - float(ks_sharps[0]["top"])
                    sharp_order_degrees = [3, 0, 4, 1, 5, 2, 6]  # F, C, G, D, A, E, B
                    for idx_s in range(min(len(ks_sharps), 7)):
                        key_sig_alters[sharp_order_degrees[idx_s]] = 1
                else:
                    font_y_offset = 1.011

            assert font_y_offset is not None

            for local_sys_idx, (treble, bass) in enumerate(systems):
                sys_top = treble.top_y
                sys_bot = bass.bot_y
                sys_height = sys_bot - sys_top
                half_space = treble.space / 2.0

                if local_sys_idx in printed_nums:
                    printed_m = printed_nums[local_sys_idx]
                    printed_anchor_checks.append(
                        {
                            "page_index": page_idx,
                            "system_index": global_sys_idx,
                            "expected_measure": current_measure_num,
                            "printed_measure": printed_m,
                            "matches": current_measure_num == printed_m,
                        }
                    )

                # Vertical grand-staff barlines spanning treble.top_y .. bass.bot_y
                vlines = [
                    ln
                    for ln in page.lines
                    if abs(float(ln["x1"]) - float(ln["x0"])) < 1.5
                    and float(ln["top"]) <= sys_top + 2.0
                    and float(ln["bottom"]) >= sys_bot - 2.0
                ]
                bar_xs = _cluster_y([float(ln["x0"]) for ln in vlines], tol=3.0)
                if not bar_xs or abs(bar_xs[0] - treble.x0) > 5.0:
                    bar_xs = [treble.x0] + bar_xs
                if abs(bar_xs[-1] - treble.x1) > 5.0:
                    bar_xs.append(treble.x1)
                bar_xs.sort()

                # Characters belonging to this system
                sys_chars = [
                    c
                    for c in music_chars
                    if (sys_top - 32.0) <= (float(c["top"]) + font_y_offset) <= (sys_bot + 32.0)
                ]

                # Check system-opening time signature before first notehead
                sys_noteheads = [c for c in sys_chars if c["text"] in NOTEHEAD_CHARS]
                first_sys_nh_x = min(
                    (float(c["x0"]) for c in sys_noteheads), default=bar_xs[0] + 45.0
                )
                opening_ts_digits = [
                    c
                    for c in sys_chars
                    if c["text"] in ("2", "3", "4", "6", "8")
                    and bar_xs[0] <= float(c["x0"]) < first_sys_nh_x - 3.0
                    and (treble.top_y - 6.0)
                    <= (float(c["top"]) + font_y_offset)
                    <= (treble.bot_y + 6.0)
                ]
                if len(opening_ts_digits) >= 2:
                    opening_ts_digits.sort(key=lambda c: float(c["top"]))
                    current_beats_per_bar = int(opening_ts_digits[0]["text"])
                    current_beat_unit = int(opening_ts_digits[1]["text"])

                # Vertical stem lines and beam shapes in this system
                stems = [
                    ln
                    for ln in page.lines
                    if abs(float(ln["x1"]) - float(ln["x0"])) < 1.2
                    and 10.0 <= (float(ln["bottom"]) - float(ln["top"])) <= (sys_height * 0.85)
                    and (sys_top - 30.0) <= float(ln["top"])
                    and float(ln["bottom"]) <= (sys_bot + 30.0)
                ]
                horiz_beams = [
                    rc
                    for rc in page.rects
                    if (float(rc["x1"]) - float(rc["x0"])) >= 6.0
                    and 1.2 <= (float(rc["bottom"]) - float(rc["top"])) <= 4.5
                    and (sys_top - 32.0) <= float(rc["top"]) <= (sys_bot + 32.0)
                ]
                tilted_beams = [
                    cv
                    for cv in page.curves
                    if len(cv.get("pts", [])) == 5
                    and cv.get("fill") is True
                    and (float(cv["x1"]) - float(cv["x0"])) >= 6.0
                    and (float(cv["bottom"]) - float(cv["top"])) <= 14.0
                    and (sys_top - 32.0) <= float(cv["top"]) <= (sys_bot + 32.0)
                ]

                sys_note_objs: list[ScoreNote] = []

                for b_idx in range(len(bar_xs) - 1):
                    mx0, mx1 = bar_xs[b_idx], bar_xs[b_idx + 1]
                    m_width = mx1 - mx0
                    m_nhs = [
                        c
                        for c in sys_noteheads
                        if (mx0 - 1.0) <= float(c["x0"]) < (mx1 - 1.0)
                    ]
                    # Filter narrow double-barline gaps or trailing courtesy meter boxes with zero notes
                    if m_width < 28.0 and not m_nhs:
                        # Courtesy time signature box at end of system updates meter for next system
                        courtesy_ts = [
                            c
                            for c in sys_chars
                            if c["text"] in ("2", "3", "4", "6", "8")
                            and mx0 <= float(c["x0"]) <= mx1
                            and (treble.top_y - 6.0)
                            <= (float(c["top"]) + font_y_offset)
                            <= (treble.bot_y + 6.0)
                        ]
                        if len(courtesy_ts) >= 2:
                            courtesy_ts.sort(key=lambda c: float(c["top"]))
                            current_beats_per_bar = int(courtesy_ts[0]["text"])
                            current_beat_unit = int(courtesy_ts[1]["text"])
                        continue
                    if not m_nhs:
                        continue

                    m_num = current_measure_num
                    current_measure_num += 1

                    m_obj = ScoreMeasure(
                        measure=m_num,
                        page_index=page_idx,
                        system_index=global_sys_idx,
                        x0_pt=round(mx0, 3),
                        y0_pt=round(sys_top - 10.0, 3),
                        x1_pt=round(mx1, 3),
                        y1_pt=round(sys_bot + 10.0, 3),
                        treble_top_pt=round(treble.top_y, 3),
                        treble_bot_pt=round(treble.bot_y, 3),
                        bass_top_pt=round(bass.top_y, 3),
                        bass_bot_pt=round(bass.bot_y, 3),
                        staff_space_pt=round(treble.space, 4),
                        beats_per_bar=current_beats_per_bar,
                        beat_unit=current_beat_unit,
                    )
                    measures.append(m_obj)

                    # Extract measure-local accidentals, dots, flags, rests, arpeggio glyphs
                    # For first measure of system, skip key-signature accidentals before first notehead - 12pt
                    first_m_nh_x = min(float(c["x0"]) for c in m_nhs)
                    acc_min_x = (
                        max(mx0, first_m_nh_x - 14.0) if b_idx == 0 else mx0 - 1.0
                    )
                    m_accs = [
                        c
                        for c in sys_chars
                        if c["text"] in ACCIDENTAL_CHARS
                        and acc_min_x <= float(c["x0"]) < mx1
                    ]
                    m_dots = [
                        c
                        for c in sys_chars
                        if c["text"] == "." and mx0 <= float(c["x0"]) < mx1 + 4.0
                    ]
                    m_flags = [
                        c
                        for c in sys_chars
                        if c["text"] == "j" and mx0 <= float(c["x0"]) < mx1 + 6.0
                    ]
                    m_arps = [
                        c
                        for c in sys_chars
                        if c["text"] == "Ð" and mx0 <= float(c["x0"]) < mx1
                    ]
                    m_rests = [
                        c
                        for c in sys_chars
                        if c["text"] == "ê" and mx0 <= float(c["x0"]) < mx1
                    ]

                    mid_gap_y = 0.5 * (treble.bot_y + bass.top_y)

                    for staff_name, staff_geom, top_diatonic in (
                        ("treble", treble, TREBLE_TOP_DIATONIC),
                        ("bass", bass, BASS_TOP_DIATONIC),
                    ):
                        if staff_name == "treble":
                            staff_nhs = [
                                c
                                for c in m_nhs
                                if (float(c["top"]) + font_y_offset) <= mid_gap_y
                            ]
                            staff_accs = [
                                c
                                for c in m_accs
                                if (float(c["top"]) + font_y_offset) <= mid_gap_y
                            ]
                            staff_rests = [
                                c
                                for c in m_rests
                                if (float(c["top"]) + font_y_offset) <= mid_gap_y
                            ]
                        else:
                            staff_nhs = [
                                c
                                for c in m_nhs
                                if (float(c["top"]) + font_y_offset) > mid_gap_y
                            ]
                            staff_accs = [
                                c
                                for c in m_accs
                                if (float(c["top"]) + font_y_offset) > mid_gap_y
                            ]
                            staff_rests = [
                                c
                                for c in m_rests
                                if (float(c["top"]) + font_y_offset) > mid_gap_y
                            ]

                        if not staff_nhs:
                            continue

                        staff_nhs.sort(key=lambda c: (float(c["x0"]), float(c["top"])))

                        # Attach each notehead to its vertical stem (if any) to separate voices & 2nd-interval chords
                        nh_records: list[dict[str, Any]] = []
                        for c in staff_nhs:
                            x0 = float(c["x0"])
                            x1 = float(c["x1"])
                            w_nh = max(x1 - x0, 5.0)
                            y_center = float(c["top"]) + font_y_offset
                            step = int(round((y_center - staff_geom.top_y) / half_space))
                            diatonic = top_diatonic - step

                            # Match vertical stem touching left or right edge of notehead
                            best_stem = None
                            best_dx = 9.0
                            for st in stems:
                                sx = float(st["x0"])
                                sy0, sy1 = float(st["top"]), float(st["bottom"])
                                if (sy0 - 3.5) <= y_center <= (sy1 + 3.5):
                                    dx = min(abs(sx - x0), abs(sx - x1))
                                    if dx < 2.2 and dx < best_dx:
                                        best_dx = dx
                                        best_stem = st

                            stem_dir = 0
                            if best_stem is not None:
                                # Up-stems attach to the right side of the primary notehead and extend upward;
                                # down-stems attach to the left side and extend downward.
                                if float(best_stem["top"]) < y_center - 7.5:
                                    stem_dir = -1
                                elif float(best_stem["bottom"]) > y_center + 7.5:
                                    stem_dir = +1
                                else:
                                    stem_dir = -1 if abs(float(best_stem["x0"]) - x1) <= abs(float(best_stem["x0"]) - x0) else +1

                            nh_records.append(
                                {
                                    "char": c,
                                    "kind": NOTEHEAD_CHARS[c["text"]],
                                    "x0": x0,
                                    "x1": x1,
                                    "w": w_nh,
                                    "y": y_center,
                                    "step": step,
                                    "diatonic": diatonic,
                                    "stem": best_stem,
                                    "stem_dir": stem_dir,
                                }
                            )

                        # Group noteheads into simultaneous chord clusters:
                        # same stem OR |dx| <= 1.55 * w_nh with compatible stem_dir (unless whole notes).
                        clusters: list[list[dict[str, Any]]] = []
                        for rec in nh_records:
                            placed = False
                            for cl in reversed(clusters):
                                same_stem = (
                                    rec["stem"] is not None
                                    and any(rec["stem"] is m["stem"] for m in cl)
                                )
                                min_dx = min(abs(rec["x0"] - m["x0"]) for m in cl)
                                compat_dir = (
                                    rec["stem_dir"] == 0
                                    or cl[0]["stem_dir"] == 0
                                    or rec["stem_dir"] == cl[0]["stem_dir"]
                                )
                                if same_stem or (min_dx <= 1.55 * rec["w"] and compat_dir):
                                    cl.append(rec)
                                    placed = True
                                    break
                            if not placed:
                                clusters.append([rec])

                        clusters.sort(key=lambda cl: min(m["x0"] for m in cl))

                        # Detect two-voice polyphony within this staff-measure:
                        # If two distinct clusters sit at nearly the same x (< 9 pt) with opposite stem_dir (-1 vs +1),
                        # or a rest sits above/below a held chord, partition into voice 1 (up-stem) & voice 2 (down-stem).
                        has_dual_voice = False
                        for i_c in range(len(clusters)):
                            for j_c in range(i_c + 1, len(clusters)):
                                xi = min(m["x0"] for m in clusters[i_c])
                                xj = min(m["x0"] for m in clusters[j_c])
                                if (
                                    abs(xi - xj) < 9.0
                                    and clusters[i_c][0]["stem_dir"] != 0
                                    and clusters[j_c][0]["stem_dir"] != 0
                                    and clusters[i_c][0]["stem_dir"] != clusters[j_c][0]["stem_dir"]
                                ):
                                    has_dual_voice = True
                                    break
                        if staff_rests and any(cl[0]["kind"] in ("half", "whole") or any(
                            abs(float(d["x0"]) - max(m["x1"] for m in cl)) < 7.0
                            and abs((float(d["top"]) + font_y_offset) - m["y"]) < 4.5
                            for m in cl for d in m_dots
                        ) for cl in clusters):
                            has_dual_voice = True

                        # Resolve accidentals in left-to-right order across the staff-measure
                        active_alters: dict[int, int] = {}
                        used_accs: set[int] = set()
                        for cl in clusters:
                            cl_x = min(m["x0"] for m in cl)
                            # Apply any accidental immediately preceding this chord (within 18 pt to the left)
                            for a_idx, acc in enumerate(staff_accs):
                                if a_idx in used_accs:
                                    continue
                                ax = float(acc["x0"])
                                ay = float(acc["top"]) + font_y_offset
                                if (cl_x - 19.0) <= ax <= (cl_x + 2.0):
                                    a_step = int(round((ay - staff_geom.top_y) / half_space))
                                    a_diat = top_diatonic - a_step
                                    active_alters[a_diat] = ACCIDENTAL_CHARS[acc["text"]]
                                    used_accs.add(a_idx)

                            for m in cl:
                                diat = m["diatonic"]
                                deg = diat % 7
                                alter = active_alters.get(diat, key_sig_alters.get(deg, 0))
                                m["midi_pitch"] = diatonic_to_midi(diat, alter)

                        # Determine duration (in quarter-note beats) for each cluster
                        def _cluster_duration_beats(cl: list[dict[str, Any]]) -> float:
                            kind = cl[0]["kind"]
                            if kind == "whole":
                                base = float(current_beats_per_bar)
                            elif kind == "half":
                                base = 2.0
                            else:
                                base = 1.0
                                st = cl[0]["stem"]
                                if st is not None:
                                    sx = float(st["x0"])
                                    sy_tip = (
                                        float(st["top"])
                                        if cl[0]["stem_dir"] == -1
                                        else float(st["bottom"])
                                    )
                                    # Count horizontal + tilted beams touching stem tip
                                    beam_hits = 0
                                    for hb in horiz_beams:
                                        if (float(hb["x0"]) - 2.0) <= sx <= (float(hb["x1"]) + 2.0):
                                            if (
                                                min(
                                                    abs(float(hb["top"]) - sy_tip),
                                                    abs(float(hb["bottom"]) - sy_tip),
                                                )
                                                < 8.5
                                            ):
                                                beam_hits += 1
                                    for tb in tilted_beams:
                                        if (float(tb["x0"]) - 2.0) <= sx <= (float(tb["x1"]) + 2.0):
                                            if (float(tb["top"]) - 6.5) <= sy_tip <= (
                                                float(tb["bottom"]) + 6.5
                                            ):
                                                # Check stem isn't just crossing near noteheads
                                                if all(
                                                    min(
                                                        abs(float(tb["top"]) - m["y"]),
                                                        abs(float(tb["bottom"]) - m["y"]),
                                                    )
                                                    > 4.5
                                                    for m in cl
                                                ):
                                                    beam_hits += 1
                                    flag_hits = sum(
                                        1
                                        for fl in m_flags
                                        if abs(float(fl["x0"]) - sx) < 4.5
                                        and abs((float(fl["top"]) + font_y_offset) - sy_tip) < 12.0
                                    )
                                    subdiv = max(beam_hits, flag_hits)
                                    if subdiv == 1:
                                        base = 0.5
                                    elif subdiv >= 2:
                                        base = 0.25

                            # Check augmentation dot immediately to the right of any notehead in cluster
                            cl_x1 = max(m["x1"] for m in cl)
                            cl_ys = [m["y"] for m in cl]
                            has_dot = any(
                                (cl_x1 - 1.5) <= float(d["x0"]) <= (cl_x1 + 8.5)
                                and min(abs((float(d["top"]) + font_y_offset) - ny) for ny in cl_ys)
                                < 4.0
                                for d in m_dots
                            )
                            return base * 1.5 if has_dot else base

                        # Assign voices and beats
                        if not has_dual_voice:
                            voice_assignment = [(1, cl) for cl in clusters]
                        else:
                            voice_assignment = [
                                (1 if cl[0]["stem_dir"] <= 0 else 2, cl) for cl in clusters
                            ]

                        # Compute beat positions per voice (scaled to current_beat_unit; 1.0 when beat_unit == 4)
                        beat_unit_scale = float(current_beat_unit) / 4.0
                        for v_num in (1, 2):
                            v_items: list[tuple[float, str, Any]] = [
                                (min(m["x0"] for m in cl), "chord", cl)
                                for vn, cl in voice_assignment
                                if vn == v_num
                            ]
                            if not v_items:
                                continue
                            if v_num == 1:
                                for rst in staff_rests:
                                    v_items.append((float(rst["x0"]), "rest_eighth", rst))
                            v_items.sort(key=lambda it: it[0])

                            beat_cursor = 1.0
                            for c_ord, (_x_pos, it_kind, payload) in enumerate(v_items):
                                if it_kind == "rest_eighth":
                                    beat_cursor += 0.5 * beat_unit_scale
                                    continue
                                cl = payload
                                dur = _cluster_duration_beats(cl) * beat_unit_scale
                                cl_x0 = min(m["x0"] for m in cl)
                                cl_y_min = min(m["y"] for m in cl)
                                cl_y_max = max(m["y"] for m in cl)
                                is_arp = any(
                                    (cl_x0 - 14.0) <= float(arp["x0"]) <= cl_x0
                                    and (cl_y_min - 12.0)
                                    <= (float(arp["top"]) + font_y_offset)
                                    <= (cl_y_max + 12.0)
                                    for arp in m_arps
                                )
                                cg_id = f"m{m_num:03d}_{staff_name[0]}_v{v_num}_c{c_ord:02d}"

                                # Sort notes inside chord from low pitch to high pitch
                                cl_sorted = sorted(cl, key=lambda m: m["midi_pitch"])
                                for n_idx, m in enumerate(cl_sorted):
                                    c_raw = m["char"]
                                    sn = ScoreNote(
                                        score_note_id=f"{cg_id}_n{n_idx:02d}",
                                        page_index=page_idx,
                                        system_index=global_sys_idx,
                                        measure=m_num,
                                        beat=round(beat_cursor, 4),
                                        duration_beats=round(dur, 4),
                                        staff=staff_name,
                                        voice=v_num,
                                        midi_pitch=m["midi_pitch"],
                                        pitch_name=midi_to_name(m["midi_pitch"]),
                                        x_pt=round(0.5 * (m["x0"] + m["x1"]), 3),
                                        y_pt=round(m["y"], 3),
                                        bbox_pt=(
                                            round(float(c_raw["x0"]), 3),
                                            round(float(c_raw["top"]), 3),
                                            round(float(c_raw["x1"]), 3),
                                            round(float(c_raw["bottom"]), 3),
                                        ),
                                        chord_group_id=cg_id,
                                        is_arpeggiated=is_arp,
                                        is_tied_continuation=False,
                                        notehead_kind=m["kind"],
                                    )
                                    sys_note_objs.append(sn)
                                beat_cursor += dur

                            if v_num == 1:
                                total_v1_beats = round(beat_cursor - 1.0, 3)
                                measure_beat_checks.append(
                                    {
                                        "measure": m_num,
                                        "staff": staff_name,
                                        "expected_beats": current_beats_per_bar,
                                        "parsed_beats": total_v1_beats,
                                        "consistent": abs(total_v1_beats - current_beats_per_bar)
                                        < 0.01,
                                    }
                                )

                # Strict within-system tie detection (excluding tilted beam polygons attached to stem tips)
                tilted_beam_ids = {id(tb) for tb in tilted_beams if any(
                    (float(tb["x0"]) - 2.0) <= float(st["x0"]) <= (float(tb["x1"]) + 2.0)
                    and (
                        abs(float(tb["top"]) - float(st["top"])) < 4.5
                        or abs(float(tb["bottom"]) - float(st["bottom"])) < 4.5
                    )
                    for st in stems
                )}
                tie_curves = [
                    cv
                    for cv in page.curves
                    if id(cv) not in tilted_beam_ids
                    and (sys_top - 18.0) <= float(cv["top"]) <= (sys_bot + 18.0)
                    and (float(cv["x1"]) - float(cv["x0"])) >= 10.0
                    and (float(cv["bottom"]) - float(cv["top"])) <= 12.0
                ]

                for staff_name in ("treble", "bass"):
                    s_notes = [n for n in sys_note_objs if n.staff == staff_name]
                    # Order unique x-positions on this staff across the whole system
                    xs_ordered = sorted({round(n.x_pt, 1) for n in s_notes})
                    for cv in tie_curves:
                        cx0, cx1 = float(cv["x0"]), float(cv["x1"])
                        cy_mid = 0.5 * (float(cv["top"]) + float(cv["bottom"]))
                        left_cands = [
                            n
                            for n in s_notes
                            if -3.0 <= (cx0 - n.x_pt) <= 10.0 and abs(cy_mid - n.y_pt) <= 7.5
                        ]
                        right_cands = [
                            n
                            for n in s_notes
                            if -3.0 <= (n.x_pt - cx1) <= 10.0 and abs(cy_mid - n.y_pt) <= 7.5
                        ]
                        for ln in left_cands:
                            for rn in right_cands:
                                if ln.midi_pitch != rn.midi_pitch or ln.voice != rn.voice or rn.x_pt <= ln.x_pt:
                                    continue
                                # Ensure no intervening different-pitch attack in the same voice between ln and rn
                                intervening = [
                                    n
                                    for n in s_notes
                                    if n.voice == ln.voice
                                    and (ln.x_pt + 3.0) < n.x_pt < (rn.x_pt - 3.0)
                                ]
                                if not intervening:
                                    rn.is_tied_continuation = True

                all_notes.extend(sys_note_objs)
                global_sys_idx += 1

    all_notes.sort(key=lambda n: (n.measure, n.beat, 0 if n.staff == "bass" else 1, n.midi_pitch))

    consistent_count = sum(1 for c in measure_beat_checks if c["consistent"])
    anchor_match_count = sum(1 for c in printed_anchor_checks if c["matches"])
    meta: dict[str, Any] = {
        "measure_count": len(measures),
        "total_notehead_count": len(all_notes),
        "attack_note_count": sum(1 for n in all_notes if not n.is_tied_continuation),
        "tied_continuation_count": sum(1 for n in all_notes if n.is_tied_continuation),
        "arpeggiated_note_count": sum(1 for n in all_notes if n.is_arpeggiated),
        "key_signature_alters": key_sig_alters,
        "calibrated_font_y_offset_pt": round(font_y_offset or 1.011, 4),
        "printed_measure_anchor_checks": len(printed_anchor_checks),
        "printed_measure_anchor_matches": anchor_match_count,
        "staff_measure_beat_checks": len(measure_beat_checks),
        "staff_measure_beat_consistent": consistent_count,
    }

    if out_json_path is not None:
        out_p = Path(out_json_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(
            json.dumps(
                {
                    "metadata": meta,
                    "measures": [m.to_dict() for m in measures],
                    "notes": [n.to_dict() for n in all_notes],
                },
                indent=2,
            )
        )

    if diagnostics_dir is not None:
        _render_score_parse_diagnostics(pdf_path, measures, all_notes, Path(diagnostics_dir))

    return measures, all_notes, meta


def _render_score_parse_diagnostics(
    pdf_path: str | Path,
    measures: list[ScoreMeasure],
    notes: list[ScoreNote],
    diag_dir: Path,
    dpi: int = 150,
) -> None:
    """Render diagnostic PNG overlays showing extracted measure boxes and decoded pitches."""
    diag_dir.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72.0
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        pages_with_music = sorted({m.page_index for m in measures})
        for p_idx in pages_with_music:
            bitmap = doc[p_idx].render(scale=scale)
            pil_img: Image.Image = bitmap.to_pil().convert("RGBA")
            overlay = Image.new("RGBA", pil_img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            for m in measures:
                if m.page_index != p_idx:
                    continue
                rect = [
                    m.x0_pt * scale,
                    m.y0_pt * scale,
                    m.x1_pt * scale,
                    m.y1_pt * scale,
                ]
                draw.rectangle(rect, outline=(30, 120, 220, 180), width=2)
                draw.text(
                    (m.x0_pt * scale + 3, m.y0_pt * scale - 14),
                    f"m.{m.measure} ({m.beats_per_bar}/{m.beat_unit})",
                    fill=(20, 80, 190, 255),
                )

            for n in notes:
                if n.page_index != p_idx:
                    continue
                cx = n.x_pt * scale
                cy = n.y_pt * scale
                color = (160, 160, 160, 220) if n.is_tied_continuation else (210, 40, 40, 230)
                draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=color)

            out_img = Image.alpha_composite(pil_img, overlay).convert("RGB")
            out_img.save(diag_dir / f"score_overlay_page_{p_idx + 1}.png")
    finally:
        doc.close()
