"""Stage 4: Backward dual-plane keyboard calibration, octave anchoring, and camera tracking."""

from __future__ import annotations

import json
import math
from pathlib import Path
import time
from typing import Any

import av
import cv2
import numpy as np

from .hand_pose import FINGERTIP_JOINTS
from .models import (
    FrameCalibration,
    FramePose,
    is_black_key,
    midi_to_canonical_u_center,
    midi_to_name,
)

ALL_BLACK_MIDIS = [p for p in range(21, 109) if is_black_key(p)]  # 36 black keys: 22 (A#0) .. 106 (A#7)
ALL_BLACK_US = np.array([midi_to_canonical_u_center(p) for p in ALL_BLACK_MIDIS], dtype=np.float64)


def _fit_line_ransac(
    xs: np.ndarray,
    ys: np.ndarray,
    tol: float = 3.5,
    iters: int = 250,
) -> tuple[float, float, np.ndarray]:
    """Fit y = m * x + b via deterministic RANSAC + least-squares refinement."""
    if len(xs) < 2:
        return 0.0, 0.0, np.zeros(len(xs), dtype=bool)
    rng = np.random.default_rng(42)
    best_inliers = np.zeros(len(xs), dtype=bool)
    n = len(xs)
    for _ in range(iters):
        i1, i2 = rng.choice(n, size=2, replace=False)
        if abs(xs[i2] - xs[i1]) < 40.0:
            continue
        m = (ys[i2] - ys[i1]) / (xs[i2] - xs[i1])
        if abs(m) > 0.9:
            continue
        b = ys[i1] - m * xs[i1]
        inl = np.abs(ys - (m * xs + b)) <= tol
        if int(np.sum(inl)) > int(np.sum(best_inliers)):
            best_inliers = inl

    if int(np.sum(best_inliers)) >= 2:
        m_ref, b_ref = np.polyfit(xs[best_inliers], ys[best_inliers], 1)
        best_inliers = np.abs(ys - (m_ref * xs + b_ref)) <= tol
        if int(np.sum(best_inliers)) >= 2:
            m_ref, b_ref = np.polyfit(xs[best_inliers], ys[best_inliers], 1)
        return float(m_ref), float(b_ref), best_inliers
    m_fb, b_fb = np.polyfit(xs, ys, 1)
    return float(m_fb), float(b_fb), np.ones(len(xs), dtype=bool)


def _detect_red_felt_and_white_front_lines(
    bgr: np.ndarray,
    exclude_mask: np.ndarray | None = None,
) -> tuple[tuple[float, float], tuple[float, float], int] | None:
    """Detect (m_back, b_back) red-felt line (v=0) and (m_front, b_front) white-key front line (v=1)."""
    h, w = bgr.shape[:2]
    b_ch = bgr[:, :, 0].astype(np.float32)
    g_ch = bgr[:, :, 1].astype(np.float32)
    r_ch = bgr[:, :, 2].astype(np.float32)

    red_excess = r_ch - np.maximum(g_ch, b_ch)
    bright = (r_ch + g_ch + b_ch) / 3.0

    # Sample columns every 8 px
    xs_red: list[float] = []
    ys_red: list[float] = []
    for x in range(40, w - 40, 8):
        if exclude_mask is not None and np.mean(exclude_mask[:, x] > 0) > 0.65:
            continue
        col_b = bright[:, x]
        col_r = red_excess[:, x]
        # Locate neutral bright white-key band first (bright > 130, low red_excess < 30)
        neutral_white = np.where((col_b > 130.0) & (col_r < 32.0))[0]
        if len(neutral_white) < 30:
            continue
        wy_top = int(neutral_white[0])
        search_lo = max(wy_top + 100, 260)
        search_hi = min(wy_top + 520, h - 20)
        if search_hi <= search_lo + 10:
            continue
        seg = col_r[search_lo:search_hi]
        pk = int(np.argmax(seg))
        if seg[pk] >= 22.0:
            ry = search_lo + pk
            if exclude_mask is not None and exclude_mask[ry, x] > 0:
                continue
            xs_red.append(float(x))
            ys_red.append(float(ry))

    if len(xs_red) < 20:
        return None

    m_back, b_back, inl_back = _fit_line_ransac(
        np.array(xs_red, dtype=np.float64),
        np.array(ys_red, dtype=np.float64),
        tol=4.0,
    )
    red_inlier_cnt = int(np.sum(inl_back))
    if red_inlier_cnt < 16:
        return None

    # Now detect white-key front edge (v=1) above red felt line:
    # transition from dark upper rail (bright < 80) to neutral bright white key (bright > 135, red_excess < 32)
    xs_front: list[float] = []
    ys_front: list[float] = []
    for x in range(40, w - 40, 8):
        y_bk = int(round(m_back * x + b_back))
        y_lo = max(15, y_bk - 480)
        y_hi = min(h - 10, y_bk - 150)
        if y_hi <= y_lo + 30:
            continue
        col_b = bright[y_lo:y_hi, x]
        col_r = red_excess[y_lo:y_hi, x]
        # Smooth 1D brightness slightly
        for k in range(6, len(col_b) - 12):
            if (
                np.mean(col_b[k - 6 : k - 1]) < 82.0
                and np.mean(col_b[k + 2 : k + 12]) > 138.0
                and np.mean(col_r[k + 2 : k + 12]) < 32.0
            ):
                fy = y_lo + k
                if exclude_mask is None or exclude_mask[fy, x] == 0:
                    xs_front.append(float(x))
                    ys_front.append(float(fy))
                break

    if len(xs_front) < 16:
        return None

    m_front, b_front, inl_front = _fit_line_ransac(
        np.array(xs_front, dtype=np.float64),
        np.array(ys_front, dtype=np.float64),
        tol=4.0,
    )
    if int(np.sum(inl_front)) < 12:
        return None

    return (m_back, b_back), (m_front, b_front), red_inlier_cnt


def _fit_1d_projective(s_obs: np.ndarray, u_true: np.ndarray) -> np.ndarray:
    """Fit 1D projective homography u = (p0 * s + p1) / (p2 * s + 1) via linear least squares + Gauss-Newton."""
    # Linear initialization: p0*s + p1 - p2*s*u = u
    a_mat = np.column_stack([s_obs, np.ones_like(s_obs), -s_obs * u_true])
    params, *_ = np.linalg.lstsq(a_mat, u_true, rcond=None)
    p = params.astype(np.float64)
    for _ in range(8):
        denom = p[2] * s_obs + 1.0
        u_pred = (p[0] * s_obs + p[1]) / denom
        res = u_true - u_pred
        j0 = s_obs / denom
        j1 = 1.0 / denom
        j2 = -(p[0] * s_obs + p[1]) * s_obs / (denom * denom)
        jac = np.column_stack([j0, j1, j2])
        dp, *_ = np.linalg.lstsq(jac, res, rcond=None)
        p += dp
        if float(np.linalg.norm(dp)) < 1e-8:
            break
    return p


def _eval_1d_projective(p: np.ndarray, s: np.ndarray | float) -> np.ndarray | float:
    return (p[0] * s + p[1]) / (p[2] * s + 1.0)


def _build_hand_arm_mask(
    shape_hw: tuple[int, int],
    fp: FramePose,
    dilate_px: int = 48,
) -> np.ndarray:
    """Create binary uint8 exclusion mask (255 = masked hand/arm) from detected pose landmarks."""
    h, w = shape_hw
    mask = np.zeros((h, w), dtype=np.uint8)
    for h_obs in fp.hands:
        pts = [
            (int(round(val[0])), int(round(val[1])))
            for val in h_obs.landmarks.values()
            if val is not None
        ]
        if len(pts) >= 3:
            arr = np.array(pts, dtype=np.int32)
            # Also extend wrist upward toward top of frame (pianist's forearm in behind-music-desk view)
            wrist = h_obs.landmarks.get("wrist")
            if wrist is not None:
                wx, wy = int(round(wrist[0])), int(round(wrist[1]))
                arm_pts = np.array(
                    [[wx - 65, max(0, wy - 220)], [wx + 65, max(0, wy - 220)], [wx + 55, wy], [wx - 55, wy]],
                    dtype=np.int32,
                )
                arr = np.vstack([arr, arm_pts])
            hull = cv2.convexHull(arr)
            cv2.fillConvexPoly(mask, hull, 255)
        elif pts:
            for px, py in pts:
                cv2.circle(mask, (px, py), 45, 255, -1)

    if dilate_px > 0 and np.any(mask):
        kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilate_px + 1, 2 * dilate_px + 1))
        mask = cv2.dilate(mask, kern)
    return mask


def _calibrate_unoccluded_reference(
    ref_bgr: np.ndarray,
    octave_hint_u_from_hands: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Estimate white and elevated black-key reference mappings on a clean frame."""
    h, w = ref_bgr.shape[:2]
    lines = _detect_red_felt_and_white_front_lines(ref_bgr)
    if lines is None:
        raise RuntimeError("Failed to detect red felt / white-key front lines on reference frame.")
    (m_back, b_back), (m_front, b_front), _ = lines

    gray = cv2.cvtColor(ref_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # Find horizontal keyboard extent [x_min_kb, x_max_kb] where white keys exist (right cheek block near x ~ 1840)
    valid_kb_xs: list[int] = []
    for x in range(10, w - 10):
        yb = m_back * x + b_back
        yf = m_front * x + b_front
        ymid = int(round(0.22 * yb + 0.78 * yf))  # white-key apron band (tau = 0.78)
        if 0 <= ymid < h and gray[ymid, x] > 115.0:
            valid_kb_xs.append(x)
    if not valid_kb_xs:
        raise RuntimeError("No visible white-key apron in reference frame.")
    x_kb_left = float(max(0, min(valid_kb_xs) - 4))
    x_kb_right = float(min(w - 1, max(valid_kb_xs) + 4))

    # Rectify the keyboard trapezoid into a W_rect x H_rect strip:
    # s in [0, W_rect] runs RIGHT-TO-LEFT (from bass cheek block x_kb_right toward treble x_kb_left!)
    # tau in [0, H_rect] runs BACK-TO-FRONT (row 0 = red felt v=0, row H_rect = white-key front v=1)
    w_rect = 2000
    h_rect = 400
    src_quad = np.array(
        [
            [x_kb_right, m_back * x_kb_right + b_back],
            [x_kb_left, m_back * x_kb_left + b_back],
            [x_kb_left, m_front * x_kb_left + b_front],
            [x_kb_right, m_front * x_kb_right + b_front],
        ],
        dtype=np.float32,
    )
    dst_quad = np.array(
        [
            [0.0, 0.0],
            [float(w_rect), 0.0],
            [float(w_rect), float(h_rect)],
            [0.0, float(h_rect)],
        ],
        dtype=np.float32,
    )
    h_img_to_rect = cv2.getPerspectiveTransform(src_quad, dst_quad)
    h_rect_to_img = np.linalg.inv(h_img_to_rect)
    rect_gray = cv2.warpPerspective(gray, h_img_to_rect, (w_rect, h_rect))

    # Segment black keys in rectified band tau in [0.10, 0.42] (rows 40..168)
    bk_profile = np.mean(rect_gray[44:164, :], axis=0)
    apron_profile = np.mean(rect_gray[280:360, :], axis=0)
    # Smooth slightly and normalize against local brightness
    bk_smooth = cv2.GaussianBlur(bk_profile.reshape(1, -1), (9, 1), 1.8).ravel()
    is_dark = bk_smooth < 82.0

    # Extract connected dark runs = individual black keys!
    runs: list[tuple[int, int, float]] = []
    in_run = False
    r0 = 0
    for s_i, val in enumerate(is_dark):
        if val and not in_run:
            in_run = True
            r0 = s_i
        elif not val and in_run:
            in_run = False
            width_s = s_i - r0
            # Filter thin white-key seams (< 11 rect px) vs genuine black keys (14..65 rect px)
            # Also require white key apron to be bright nearby so cheek-block black wood at s~0 is excluded!
            s_mid = 0.5 * (r0 + s_i - 1)
            apron_window = apron_profile[max(0, int(s_mid) - 25) : min(w_rect, int(s_mid) + 25)]
            if 13 <= width_s <= 68 and len(apron_window) > 0 and float(np.max(apron_window)) > 130.0:
                runs.append((r0, s_i - 1, s_mid))
    if in_run:
        width_s = w_rect - r0
        s_mid = 0.5 * (r0 + w_rect - 1)
        if 13 <= width_s <= 68:
            runs.append((r0, w_rect - 1, s_mid))

    if len(runs) < 12:
        raise RuntimeError(f"Too few black keys segmented on reference frame: {len(runs)}")

    s_centers = np.array([r[2] for r in runs], dtype=np.float64)
    n_det = len(s_centers)

    # Measure each black key's visible tip tau_tip in [0, 1] inside rectified image
    tau_tips: list[float] = []
    for r0, r1, s_mid in runs:
        c_lo = max(0, int(round(s_mid)) - 3)
        c_hi = min(w_rect, int(round(s_mid)) + 4)
        col_strip = np.mean(rect_gray[:, c_lo:c_hi], axis=1)
        # Find row in [140..330] where dark black key transitions to bright white apron (> 118)
        tip_row = int(round(0.60 * h_rect))
        for r_y in range(130, 340):
            if np.mean(col_strip[r_y - 8 : r_y]) < 85.0 and np.mean(col_strip[r_y + 2 : r_y + 12]) > 120.0:
                tip_row = r_y
                break
        tau_tips.append(tip_row / float(h_rect))

    # Match s_centers against ALL_BLACK_US via 1D projective fit across all valid starting offsets.
    # Notice: pattern [A#0] - [C#1, D#1] - [F#1, G#1, A#1] is 12-semitone periodic EXCEPT at offset=0 (A#0)!
    # Check whether right cheek block is visible at s=0 (x_kb_right < w - 25):
    right_cheek_block_visible = x_kb_right < (w - 25)
    if not right_cheek_block_visible:
        raise RuntimeError("Absolute octave anchor unavailable: bass cheek block is outside the frame.")

    best_offset = 0
    best_p1d = None
    best_score = 1e9

    candidate_offsets = range(0, len(ALL_BLACK_US) - n_det + 1)
    for off in candidate_offsets:
        u_slice = ALL_BLACK_US[off : off + n_det]
        p1d = _fit_1d_projective(s_centers, u_slice)
        u_pred = _eval_1d_projective(p1d, s_centers)
        rmse = float(np.sqrt(np.mean((u_pred - u_slice) ** 2)))
        if not np.all(np.isfinite(p1d)) or not np.isfinite(rmse) or rmse > 0.16:
            continue

        # Check left/right boundary consistency:
        # At s = 0 (rightmost white-key boundary!), what is u(0)?
        u_at_right_edge = float(_eval_1d_projective(p1d, 0.0))
        if not np.isfinite(u_at_right_edge) or abs(u_at_right_edge) > 0.8 or off != 0:
            continue
        score = rmse
        if right_cheek_block_visible:
            # Physical right cheek block of an 88-key piano is A0's left edge -> u = 0.0!
            score += 0.25 * abs(u_at_right_edge - 0.0)
        if octave_hint_u_from_hands is not None:
            # Cross-verify against expected played-register u range
            u_mid_frame = float(_eval_1d_projective(p1d, 0.5 * w_rect))
            hint_lo, hint_hi = octave_hint_u_from_hands
            if not (hint_lo <= u_mid_frame <= hint_hi):
                score += 0.5 * min(abs(u_mid_frame - hint_lo), abs(u_mid_frame - hint_hi))

        if score < best_score:
            best_score = score
            best_offset = off
            best_p1d = p1d

    if best_p1d is None:
        raise RuntimeError("No accepted reference key-pattern fit with an absolute octave anchor.")
    matched_midis = ALL_BLACK_MIDIS[best_offset : best_offset + n_det]
    matched_us = ALL_BLACK_US[best_offset : best_offset + n_det]
    u_fit_res = float(np.median(np.abs(_eval_1d_projective(best_p1d, s_centers) - matched_us)))

    # Detect key slant angle in rectified apron: white-key dark seams at tau ~ 0.85 vs black-key centers at tau ~ 0.25!
    # In rectified space, check seam offset ds between tau=0.25 and tau=0.88 for C#|D|D# and F#|G|G#|A|A# seams:
    apron_band = np.mean(rect_gray[295:375, :], axis=0)
    apron_grad = cv2.GaussianBlur(apron_band.reshape(1, -1), (5, 1), 1.0).ravel()
    # Estimate global horizontal shear ds_apron (rectified pixels shift from tau=0 to tau=1)
    # For every integer white-key seam u_seam in [ceil(min_u)..floor(max_u)], invert best_p1d(s) = u_seam:
    # u = (p0*s + p1)/(p2*s + 1) => s * (p0 - p2*u) = u - p1 => s = (u - p1) / (p0 - p2*u)
    def u_to_s(u_val: float) -> float:
        return float((u_val - best_p1d[1]) / (best_p1d[0] - best_p1d[2] * u_val))

    best_shear_s = 0.0
    best_seam_darkness = 1e9
    u_seams = [float(k) for k in range(max(1, int(math.ceil(matched_us[0]))), int(math.floor(matched_us[-1])) + 1)]
    for shear_s in np.linspace(-55.0, 55.0, 221):
        vals = []
        for usm in u_seams:
            s_at_apron = int(round(u_to_s(usm) + 0.84 * shear_s))
            if 4 <= s_at_apron < w_rect - 4:
                # Local minimum within +-2 px around predicted seam
                vals.append(float(np.min(apron_grad[s_at_apron - 2 : s_at_apron + 3])))
        if len(vals) >= 10:
            mean_v = float(np.mean(vals))
            if mean_v < best_seam_darkness:
                best_seam_darkness = mean_v
                best_shear_s = float(shear_s)

    # Construct 2D point correspondences in ORIGINAL IMAGE PIXELS for:
    # 1) H_white: Image(x, y) -> (u, v) on Z=0 white-key plane (v=0 at red felt, v=1 at white-key front)
    # 2) H_black: Image(x, y) -> (u, v_black) on Z=h_black top plane (v_black=0 at red felt base, v_black=0.62 at visible black-key tip!)
    white_img_pts: list[list[float]] = []
    white_uv_pts: list[list[float]] = []
    black_img_pts: list[list[float]] = []
    black_uv_pts: list[list[float]] = []

    def rect_to_img_pt(s_val: float, tau_val: float) -> tuple[float, float]:
        pt = np.array([s_val, tau_val * h_rect, 1.0], dtype=np.float64)
        q = h_rect_to_img @ pt
        return (float(q[0] / q[2]), float(q[1] / q[2]))

    for idx_k, (s_c, u_c, tau_tip) in enumerate(zip(s_centers, matched_us, tau_tips)):
        # Base at red felt (tau = 0.0)
        xb, yb = rect_to_img_pt(float(s_c), 0.0)
        white_img_pts.append([xb, yb])
        white_uv_pts.append([float(u_c), 0.0])

        # Front of white-key plane (tau = 1.0, shifted by apron seam shear!)
        xf, yf = rect_to_img_pt(float(s_c) + best_shear_s, 1.0)
        white_img_pts.append([xf, yf])
        white_uv_pts.append([float(u_c), 1.0])

        # Elevated black-key top face: base at tau = 0.02 -> v_black = 0.0, visible tip at tau_tip -> v_black = 0.62
        xb_top, yb_top = rect_to_img_pt(float(s_c), 0.02)
        xt_top, yt_top = rect_to_img_pt(float(s_c) + tau_tip * best_shear_s * 0.45, float(tau_tip))
        black_img_pts.append([xb_top, yb_top])
        black_uv_pts.append([float(u_c), 0.0])
        black_img_pts.append([xt_top, yt_top])
        black_uv_pts.append([float(u_c), 0.62])

    h_white_ref, _ = cv2.findHomography(
        np.array(white_img_pts, dtype=np.float64),
        np.array(white_uv_pts, dtype=np.float64),
        method=0,
    )
    h_black_ref, _ = cv2.findHomography(
        np.array(black_img_pts, dtype=np.float64),
        np.array(black_uv_pts, dtype=np.float64),
        method=0,
    )
    for mapping in (h_white_ref, h_black_ref):
        if mapping is None or not np.all(np.isfinite(mapping)) or np.linalg.matrix_rank(mapping) < 3:
            raise RuntimeError("Invalid reference keyboard homography.")

    black_key_img_centers = [
        rect_to_img_pt(float(s_c) + 0.25 * best_shear_s, 0.25) for s_c in s_centers
    ]

    return {
        "h_white": h_white_ref.astype(np.float64),
        "h_black": h_black_ref.astype(np.float64),
        "matched_black_midis": matched_midis,
        "matched_black_us": matched_us.tolist(),
        "black_key_img_centers": black_key_img_centers,
        "u_fit_median_residual_kw": round(u_fit_res, 4),
        "right_cheek_block_visible": right_cheek_block_visible,
        "shear_rect_px": round(best_shear_s, 2),
        "m_back": m_back,
        "b_back": b_back,
        "m_front": m_front,
        "b_front": b_front,
    }


def _evaluate_homography_black_key_residual(
    gray: np.ndarray,
    exclude_mask: np.ndarray,
    h_white: np.ndarray,
) -> tuple[float, int]:
    """Measure median lateral black-key center residual (in white-key widths) on unmasked keys."""
    h_img, w_img = gray.shape[:2]
    try:
        h_inv = np.linalg.inv(h_white)
    except np.linalg.LinAlgError:
        return 9.99, 0

    # Sample horizontal profile along v = 0.24 across full 88-key range u in [0.3, 51.7] at step du = 0.05 kw
    us_grid = np.arange(0.3, 51.75, 0.05)
    pts_uv = np.column_stack([us_grid, np.full_like(us_grid, 0.24), np.ones_like(us_grid)])
    pts_img = (h_inv @ pts_uv.T).T
    denom = np.where(np.abs(pts_img[:, 2]) > 1e-9, pts_img[:, 2], 1e-9)
    xs = pts_img[:, 0] / denom
    ys = pts_img[:, 1] / denom

    in_bounds = (xs >= 8) & (xs < w_img - 8) & (ys >= 8) & (ys < h_img - 8)
    residuals: list[float] = []

    for u_bk in ALL_BLACK_US:
        # Look within [u_bk - 0.48, u_bk + 0.48] across all 36 black keys (A#0..A#7)
        win_mask = in_bounds & (np.abs(us_grid - u_bk) <= 0.48)
        idxs = np.where(win_mask)[0]
        if len(idxs) < 12:
            continue
        xi = np.round(xs[idxs]).astype(np.int32)
        yi = np.round(ys[idxs]).astype(np.int32)
        if np.any(exclude_mask[yi, xi] > 0):
            continue
        vals = gray[yi, xi]
        # Valid unmasked black key should have clear dark valley (< 85) flanked by bright white stem (> 115)
        if float(np.min(vals)) < 85.0 and float(np.max(vals)) > 115.0:
            dark_mask = vals < (0.5 * (float(np.min(vals)) + float(np.max(vals))))
            if np.any(dark_mask):
                u_centroid = float(np.mean(us_grid[idxs][dark_mask]))
                residuals.append(abs(u_centroid - float(u_bk)))

    if not residuals:
        return 9.99, 0
    return float(np.median(residuals)), len(residuals)


def _refine_lateral_u_shift(
    gray: np.ndarray,
    exclude_mask: np.ndarray,
    h_white: np.ndarray,
) -> np.ndarray:
    """Fine 1D sub-key lateral alignment polish against all unmasked black keys across [0, 52]."""
    h_img, w_img = gray.shape[:2]
    try:
        h_inv = np.linalg.inv(h_white)
    except np.linalg.LinAlgError:
        return h_white
    us_grid = np.arange(0.3, 51.75, 0.04)
    pts_uv = np.column_stack([us_grid, np.full_like(us_grid, 0.24), np.ones_like(us_grid)])
    pts_img = (h_inv @ pts_uv.T).T
    denom = np.where(np.abs(pts_img[:, 2]) > 1e-9, pts_img[:, 2], 1e-9)
    xs = pts_img[:, 0] / denom
    ys = pts_img[:, 1] / denom
    in_bounds = (xs >= 8) & (xs < w_img - 8) & (ys >= 8) & (ys < h_img - 8)

    u_obs_list: list[float] = []
    u_true_list: list[float] = []
    for u_bk in ALL_BLACK_US:
        idxs = np.where(in_bounds & (np.abs(us_grid - u_bk) <= 0.45))[0]
        if len(idxs) < 12:
            continue
        xi = np.round(xs[idxs]).astype(np.int32)
        yi = np.round(ys[idxs]).astype(np.int32)
        if np.any(exclude_mask[yi, xi] > 0):
            continue
        vals = gray[yi, xi]
        if float(np.min(vals)) < 85.0 and float(np.max(vals)) > 115.0:
            dark_mask = vals < (0.5 * (float(np.min(vals)) + float(np.max(vals))))
            if np.any(dark_mask):
                u_cent = float(np.mean(us_grid[idxs][dark_mask]))
                if abs(u_cent - float(u_bk)) <= 0.42:
                    u_obs_list.append(u_cent)
                    u_true_list.append(float(u_bk))

    if len(u_obs_list) >= 5:
        # Affine 1D correction u_corr = a * u_obs + b (RANSAC median-robust)
        u_o = np.array(u_obs_list, dtype=np.float64)
        u_t = np.array(u_true_list, dtype=np.float64)
        diffs = u_t - u_o
        med_d = float(np.median(diffs))
        inl = np.abs(diffs - med_d) <= 0.16
        if int(np.sum(inl)) >= 5 and (np.max(u_o[inl]) - np.min(u_o[inl])) >= 6.0:
            a_u, b_u = np.polyfit(u_o[inl], u_t[inl], 1)
            if 0.94 <= a_u <= 1.06 and abs(b_u) <= 1.2:
                corr = np.array([[a_u, 0.0, b_u], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
                return corr @ h_white
        elif int(np.sum(inl)) >= 4 and abs(med_d) <= 0.55:
            corr = np.array([[1.0, 0.0, med_d], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
            return corr @ h_white
    return h_white


def _is_homography_step_consistent(
    h_try: np.ndarray,
    h_prev: np.ndarray,
    w_img: int,
    h_img: int,
    max_du: float = 1.35,
    max_dv: float = 0.25,
) -> bool:
    """Enforce inter-frame physical continuity (blocks +-7 kw octave jumps and projective blow-ups)."""
    try:
        h_prev_inv = np.linalg.inv(h_prev)
    except np.linalg.LinAlgError:
        return False

    us_probe = np.linspace(1.0, 51.0, 26)
    probe_uv = np.column_stack([us_probe, np.full_like(us_probe, 0.50), np.ones_like(us_probe)])
    probe_px = (h_prev_inv @ probe_uv.T).T
    d_p = np.where(np.abs(probe_px[:, 2]) > 1e-9, probe_px[:, 2], 1e-9)
    px_x = probe_px[:, 0] / d_p
    px_y = probe_px[:, 1] / d_p
    vis = (px_x >= 35) & (px_x < w_img - 35) & (px_y >= 25) & (px_y < h_img - 25)
    vis_us = us_probe[vis]
    if len(vis_us) < 4 or (vis_us[-1] - vis_us[0]) < 6.0:
        return False

    u_lo, u_mid, u_hi = float(vis_us[0]), float(vis_us[len(vis_us) // 2]), float(vis_us[-1])
    test_uv = np.array(
        [
            [u_lo, 0.15, 1.0],
            [u_mid, 0.15, 1.0],
            [u_hi, 0.15, 1.0],
            [u_lo, 0.85, 1.0],
            [u_mid, 0.85, 1.0],
            [u_hi, 0.85, 1.0],
        ],
        dtype=np.float64,
    )
    test_px = (h_prev_inv @ test_uv.T).T
    test_px = test_px / np.where(np.abs(test_px[:, 2:3]) > 1e-9, test_px[:, 2:3], 1e-9)

    try_uv = (h_try @ test_px.T).T
    if np.any(np.abs(try_uv[:, 2]) < 1e-7):
        return False
    u_try = try_uv[:, 0] / try_uv[:, 2]
    v_try = try_uv[:, 1] / try_uv[:, 2]

    if float(np.max(np.abs(u_try - test_uv[:, 0]))) > max_du:
        return False
    if float(np.max(np.abs(v_try - test_uv[:, 1]))) > max_dv:
        return False

    span_true = u_hi - u_lo
    span_back = (u_try[2] - u_try[0]) / span_true
    span_front = (u_try[5] - u_try[3]) / span_true
    if not (0.86 <= span_back <= 1.16 and 0.86 <= span_front <= 1.16):
        return False
    return True


def _verify_white_apron_brightness(
    gray: np.ndarray,
    exclude_mask: np.ndarray,
    h_white: np.ndarray,
) -> tuple[bool, str | None]:
    """Verify unmasked white-key apron [0.5, 51.5] lies on bright keys and not dark cheek blocks."""
    h_img, w_img = gray.shape[:2]
    try:
        h_inv = np.linalg.inv(h_white)
    except np.linalg.LinAlgError:
        return False, "singular_homography"

    us_apron = np.arange(0.5, 51.6, 0.5)
    pts_uv = np.column_stack([us_apron, np.full_like(us_apron, 0.80), np.ones_like(us_apron)])
    pts_px = (h_inv @ pts_uv.T).T
    d = np.where(np.abs(pts_px[:, 2]) > 1e-9, pts_px[:, 2], 1e-9)
    xs = pts_px[:, 0] / d
    ys = pts_px[:, 1] / d

    in_b = (xs >= 10) & (xs < w_img - 10) & (ys >= 10) & (ys < h_img - 10)
    idxs = np.where(in_b)[0]
    if len(idxs) < 10:
        return False, "off_keyboard_view"

    xi = np.round(xs[idxs]).astype(np.int32)
    yi = np.round(ys[idxs]).astype(np.int32)
    unmasked = exclude_mask[yi, xi] == 0
    vals = gray[yi[unmasked], xi[unmasked]]
    if len(vals) < 8:
        return False, "heavily_occluded_apron"
    if float(np.median(vals)) < 112.0:
        return False, "apron_too_dark"

    # Check consecutive unmasked 6-sample (~3-white-key) windows: none should sit on dark cheek-block wood
    if len(vals) >= 8:
        for k in range(0, len(vals) - 5):
            if float(np.percentile(vals[k : k + 6], 75)) < 85.0:
                return False, "cheek_block_boundary_mismatch"
    return True, None


def calibrate_and_track_keyboard(
    video_path: str | Path,
    frame_poses: list[FramePose],
    out_json_path: str | Path | None = None,
    diagnostics_dir: str | Path | None = None,
) -> tuple[list[FrameCalibration], dict[str, Any]]:
    """Run Stage 4 reference dual-plane keyboard calibration and backward/forward camera tracking."""
    t0 = time.perf_counter()

    # Decode all video frames once or in two light passes:
    # First pass: locate sharpest hand-free reference frame (handCount == 0) with maximum red-felt inliers.
    candidate_ref_indices = [fp.frame_index for fp in frame_poses if len(fp.hands) == 0]
    ref_stride = max(1, len(candidate_ref_indices) // 24)
    grays: list[np.ndarray] = []
    ref_candidates_bgr: dict[int, np.ndarray] = {}
    cand_set = set(candidate_ref_indices[::ref_stride])

    container = av.open(str(video_path))
    try:
        v_stream = next(s for s in container.streams if s.type == "video")
        for idx, frame in enumerate(container.decode(v_stream)):
            bgr = frame.to_ndarray(format="bgr24")
            grays.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
            if idx in cand_set:
                ref_candidates_bgr[idx] = bgr
    finally:
        container.close()

    if len(grays) != len(frame_poses):
        raise ValueError(
            f"PyAV decoded {len(grays)} frames vs hand_poses {len(frame_poses)} frames."
        )

    best_ref_idx = -1
    best_ref_inliers = -1
    for r_idx, bgr in ref_candidates_bgr.items():
        det = _detect_red_felt_and_white_front_lines(bgr)
        if det is not None and det[2] > best_ref_inliers:
            best_ref_inliers = det[2]
            best_ref_idx = r_idx

    if best_ref_idx < 0:
        raise RuntimeError("Could not find a valid unoccluded keyboard reference frame.")

    ref_bgr = ref_candidates_bgr[best_ref_idx]
    ref_cal = _calibrate_unoccluded_reference(ref_bgr)
    h_white_ref: np.ndarray = ref_cal["h_white"]
    h_black_ref: np.ndarray = ref_cal["h_black"]
    # Approximate transfer: the fixed reference-plane correction is not exact under camera translation.
    h_black_from_white = h_black_ref @ np.linalg.inv(h_white_ref)

    n_frames = len(grays)
    h_img, w_img = grays[0].shape[:2]
    h_whites: list[np.ndarray | None] = [None] * n_frames
    residuals: list[float] = [9.99] * n_frames
    inlier_counts: list[int] = [0] * n_frames
    reliables: list[bool] = [False] * n_frames
    reasons: list[str | None] = [None] * n_frames

    # Restrict feature tracking strictly to the full 88-key polygon [0, 52] x [-0.08, 1.06]
    us_edge = np.linspace(0.0, 52.0, 27)
    kb_poly_uv = np.vstack(
        [
            np.column_stack([us_edge, np.full_like(us_edge, -0.08), np.ones_like(us_edge)]),
            np.column_stack([us_edge[::-1], np.full_like(us_edge, 1.06), np.ones_like(us_edge)]),
        ]
    )

    def _project_kb_mask(h_w: np.ndarray) -> np.ndarray:
        mask_out = np.zeros((h_img, w_img), dtype=np.uint8)
        try:
            hw_inv = np.linalg.inv(h_w)
        except np.linalg.LinAlgError:
            return mask_out
        pts_h = (hw_inv @ kb_poly_uv.T).T
        valid_z = pts_h[:, 2] > 0.05
        if int(np.sum(valid_z)) < 4:
            return mask_out
        pts_2d = pts_h[valid_z, :2] / pts_h[valid_z, 2:3]
        pts_2d = np.clip(pts_2d, -4000.0, 6000.0)
        cv2.fillPoly(mask_out, [np.round(pts_2d).astype(np.int32)], 255)
        return mask_out

    ref_kb_mask = _project_kb_mask(h_white_ref)

    ref_gray = grays[best_ref_idx]
    ref_pts = cv2.goodFeaturesToTrack(
        ref_gray,
        maxCorners=800,
        qualityLevel=0.01,
        minDistance=8,
        mask=ref_kb_mask,
    )

    # Evaluate reference frame itself
    empty_mask = np.zeros((h_img, w_img), dtype=np.uint8)
    ref_res, ref_inl = _evaluate_homography_black_key_residual(ref_gray, empty_mask, h_white_ref)
    h_whites[best_ref_idx] = h_white_ref
    residuals[best_ref_idx] = ref_res
    inlier_counts[best_ref_idx] = ref_inl
    apron_ok, _ = _verify_white_apron_brightness(ref_gray, empty_mask, h_white_ref)
    if not apron_ok or ref_inl < 5 or not np.isfinite(ref_res) or ref_res > 0.32:
        raise RuntimeError("Reference keyboard calibration failed the reliability gate.")
    reliables[best_ref_idx] = True

    lk_params = dict(
        winSize=(25, 25),
        maxLevel=4,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )

    def _track_step(cur_idx: int, prev_idx: int) -> None:
        h_prev = h_whites[prev_idx]
        if h_prev is None:
            reasons[cur_idx] = "homography_tracking_lost"
            reliables[cur_idx] = False
            return

        cur_gray = grays[cur_idx]
        hand_mask = _build_hand_arm_mask((h_img, w_img), frame_poses[cur_idx], dilate_px=46)

        cand_h: np.ndarray | None = None

        # Strategy 1: Seeded direct LK optical flow from clean reference frame (zero cumulative drift,
        # initialized via prev_idx homography so periodic piano octaves cannot alias!)
        if ref_pts is not None:
            try:
                t_ref_to_prev = np.linalg.inv(h_prev) @ h_white_ref
                ref_flat = ref_pts.reshape(-1, 2)
                ref_hom = np.column_stack([ref_flat, np.ones(len(ref_flat), dtype=np.float64)])
                init_hom = (t_ref_to_prev @ ref_hom.T).T
                valid_z = init_hom[:, 2] > 0.05
                init_xy = np.zeros_like(ref_flat, dtype=np.float32)
                init_xy[valid_z] = (init_hom[valid_z, :2] / init_hom[valid_z, 2:3]).astype(np.float32)
            except np.linalg.LinAlgError:
                valid_z = np.zeros(len(ref_pts), dtype=bool)
                init_xy = np.zeros((len(ref_pts), 2), dtype=np.float32)

            vis_idxs: list[int] = []
            for k_r, (ix_f, iy_f) in enumerate(init_xy):
                if not valid_z[k_r]:
                    continue
                ix, iy = int(round(float(ix_f))), int(round(float(iy_f)))
                if 20 <= ix < w_img - 20 and 20 <= iy < h_img - 20 and hand_mask[iy, ix] == 0:
                    vis_idxs.append(k_r)

            if len(vis_idxs) >= 32:
                ref_sub = ref_pts[vis_idxs].astype(np.float32)
                p1_init = init_xy[vis_idxs].reshape(-1, 1, 2).copy()
                p1, st, _err = cv2.calcOpticalFlowPyrLK(
                    ref_gray,
                    cur_gray,
                    ref_sub,
                    p1_init,
                    flags=cv2.OPTFLOW_USE_INITIAL_FLOW,
                    **lk_params,
                )
                p0_back_init = ref_sub.copy()
                p0_back, st_back, _ = cv2.calcOpticalFlowPyrLK(
                    cur_gray,
                    ref_gray,
                    p1,
                    p0_back_init,
                    flags=cv2.OPTFLOW_USE_INITIAL_FLOW,
                    **lk_params,
                )
                fb_err = np.linalg.norm(ref_sub.reshape(-1, 2) - p0_back.reshape(-1, 2), axis=1)
                step_disp = np.linalg.norm(p1.reshape(-1, 2) - init_xy[vis_idxs], axis=1)
                good = (
                    (st.ravel() == 1)
                    & (st_back.ravel() == 1)
                    & (fb_err < 1.8)
                    & (step_disp < 48.0)
                )
                pts_ref_g = ref_sub.reshape(-1, 2)[good]
                pts_cur_g = p1.reshape(-1, 2)[good]
                keep = [
                    k_pt
                    for k_pt, (cx, cy) in enumerate(pts_cur_g)
                    if 0 <= int(round(cx)) < w_img
                    and 0 <= int(round(cy)) < h_img
                    and hand_mask[int(round(cy)), int(round(cx))] == 0
                ]
                if len(keep) >= 24:
                    t_cur_to_ref, inl = cv2.findHomography(
                        pts_cur_g[keep], pts_ref_g[keep], cv2.RANSAC, 2.5
                    )
                    if t_cur_to_ref is not None and inl is not None and int(np.sum(inl)) >= 18:
                        h_try = h_white_ref @ t_cur_to_ref
                        h_try = _refine_lateral_u_shift(cur_gray, hand_mask, h_try)
                        if _is_homography_step_consistent(h_try, h_prev, w_img, h_img):
                            res_try, inl_try = _evaluate_homography_black_key_residual(
                                cur_gray, hand_mask, h_try
                            )
                            apron_ok, _ = _verify_white_apron_brightness(cur_gray, hand_mask, h_try)
                            if apron_ok and inl_try >= 6 and res_try <= 0.26:
                                cand_h = h_try
                                residuals[cur_idx] = res_try
                                inlier_counts[cur_idx] = inl_try

        # Strategy 2: Frame-to-frame propagation across large camera pan (e.g. treble pan u > 38)
        if cand_h is None:
            prev_gray = grays[prev_idx]
            prev_hand_mask = _build_hand_arm_mask((h_img, w_img), frame_poses[prev_idx], dilate_px=46)
            prev_valid_mask = _project_kb_mask(h_prev)
            prev_valid_mask[prev_hand_mask > 0] = 0

            pts_prev = cv2.goodFeaturesToTrack(
                prev_gray,
                maxCorners=700,
                qualityLevel=0.01,
                minDistance=8,
                mask=prev_valid_mask,
            )
            if pts_prev is not None and len(pts_prev) >= 16:
                p1, st, _ = cv2.calcOpticalFlowPyrLK(prev_gray, cur_gray, pts_prev, None, **lk_params)
                p0_b, st_b, _ = cv2.calcOpticalFlowPyrLK(cur_gray, prev_gray, p1, None, **lk_params)
                fb = np.linalg.norm(pts_prev.reshape(-1, 2) - p0_b.reshape(-1, 2), axis=1)
                step_d = np.linalg.norm(p1.reshape(-1, 2) - pts_prev.reshape(-1, 2), axis=1)
                good = (st.ravel() == 1) & (st_b.ravel() == 1) & (fb < 2.0) & (step_d < 70.0)
                g_prev = pts_prev.reshape(-1, 2)[good]
                g_cur = p1.reshape(-1, 2)[good]
                keep = [
                    k_pt
                    for k_pt, (cx, cy) in enumerate(g_cur)
                    if 0 <= int(round(cx)) < w_img
                    and 0 <= int(round(cy)) < h_img
                    and hand_mask[int(round(cy)), int(round(cx))] == 0
                ]
                if len(keep) >= 12:
                    src_pts = g_cur[keep]
                    dst_pts = g_prev[keep]
                    candidates_s2: list[tuple[float, int, np.ndarray]] = []

                    # 6-DOF affine warp preserves projective foreshortening without collinear-strip blow-up
                    aff_2x3, inl_a = cv2.estimateAffine2D(
                        src_pts, dst_pts, method=cv2.RANSAC, ransacReprojThreshold=2.5
                    )
                    if aff_2x3 is not None and inl_a is not None and int(np.sum(inl_a)) >= 10:
                        t_aff = np.vstack([aff_2x3, [0.0, 0.0, 1.0]])
                        h_a = _refine_lateral_u_shift(cur_gray, hand_mask, h_prev @ t_aff)
                        if _is_homography_step_consistent(h_a, h_prev, w_img, h_img):
                            r_a, i_a = _evaluate_homography_black_key_residual(cur_gray, hand_mask, h_a)
                            candidates_s2.append((r_a, i_a, h_a))

                    # 8-DOF homography for out-of-plane camera tilt during wide pan
                    t_hom, inl_h = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 2.5)
                    if t_hom is not None and inl_h is not None and int(np.sum(inl_h)) >= 12:
                        h_h = _refine_lateral_u_shift(cur_gray, hand_mask, h_prev @ t_hom)
                        if _is_homography_step_consistent(h_h, h_prev, w_img, h_img):
                            r_h, i_h = _evaluate_homography_black_key_residual(cur_gray, hand_mask, h_h)
                            # Require clear improvement over 6-DOF affine before accepting extra 2 projective DOFs
                            candidates_s2.append((r_h + 0.012, i_h, h_h))

                    if candidates_s2:
                        candidates_s2.sort(key=lambda item: item[0])
                        _, best_i2, best_h2 = candidates_s2[0]
                        true_r2, true_i2 = _evaluate_homography_black_key_residual(
                            cur_gray, hand_mask, best_h2
                        )
                        cand_h = best_h2
                        residuals[cur_idx] = true_r2
                        inlier_counts[cur_idx] = max(best_i2, true_i2)

        if cand_h is None:
            reasons[cur_idx] = "homography_tracking_lost"
            reliables[cur_idx] = False
            return

        h_whites[cur_idx] = cand_h
        apron_ok, apron_reason = _verify_white_apron_brightness(cur_gray, hand_mask, cand_h)
        if not apron_ok:
            reliables[cur_idx] = False
            reasons[cur_idx] = apron_reason
        elif inlier_counts[cur_idx] < 5:
            reliables[cur_idx] = False
            reasons[cur_idx] = "insufficient_keyboard_inliers"
        elif not np.isfinite(residuals[cur_idx]) or residuals[cur_idx] > 0.32:
            reliables[cur_idx] = False
            reasons[cur_idx] = "high_calibration_residual"
        else:
            reliables[cur_idx] = True
            reasons[cur_idx] = None

    # Track backward from best_ref_idx -> 0
    for idx in range(best_ref_idx - 1, -1, -1):
        _track_step(idx, idx + 1)

    # Track forward from best_ref_idx -> n_frames - 1
    for idx in range(best_ref_idx + 1, n_frames):
        _track_step(idx, idx - 1)

    # Cross-check octave anchor against detected L/R fingertip register distributions
    r_us: list[float] = []
    l_us: list[float] = []
    for idx, fp in enumerate(frame_poses):
        hw = h_whites[idx]
        if not reliables[idx] or hw is None:
            continue
        for h_obs in fp.hands:
            for jn in FINGERTIP_JOINTS.values():
                lm = h_obs.landmarks.get(jn)
                if lm is not None and lm[2] >= 0.6:
                    d = hw[2, 0] * lm[0] + hw[2, 1] * lm[1] + hw[2, 2]
                    if abs(d) > 1e-9:
                        u_v = (hw[0, 0] * lm[0] + hw[0, 1] * lm[1] + hw[0, 2]) / d
                        if h_obs.resolved_hand == "R":
                            r_us.append(float(u_v))
                        elif h_obs.resolved_hand == "L":
                            l_us.append(float(u_v))

    calibrations: list[FrameCalibration] = []
    for idx, fp in enumerate(frame_poses):
        hw = h_whites[idx]
        if hw is not None:
            # Normalize matrix so hw[2, 2] == 1.0
            hw_n = hw / (hw[2, 2] if abs(hw[2, 2]) > 1e-12 else 1.0)
            hb = h_black_from_white @ hw_n
            hb_n = hb / (hb[2, 2] if abs(hb[2, 2]) > 1e-12 else 1.0)
            hw_list: list[list[float]] | None = np.round(hw_n, 8).tolist()
            hb_list: list[list[float]] | None = np.round(hb_n, 8).tolist()
        else:
            hw_list = None
            hb_list = None

        calibrations.append(
            FrameCalibration(
                frame_index=idx,
                pts_sec=fp.pts_sec,
                h_white=hw_list,
                h_black=hb_list,
                residual_kw=round(residuals[idx], 4),
                inlier_count=inlier_counts[idx],
                reliable=reliables[idx],
                reason=reasons[idx],
            )
        )

    reliable_res = [c.residual_kw for c in calibrations if c.reliable]
    elapsed = time.perf_counter() - t0
    meta: dict[str, Any] = {
        "reference_frame_index": best_ref_idx,
        "reference_frame_pts_sec": frame_poses[best_ref_idx].pts_sec,
        "reference_visible_black_key_range": [
            midi_to_name(ref_cal["matched_black_midis"][0]),
            midi_to_name(ref_cal["matched_black_midis"][-1]),
        ],
        "reference_right_cheek_block_visible": ref_cal["right_cheek_block_visible"],
        "reference_1d_projective_residual_kw": ref_cal["u_fit_median_residual_kw"],
        "total_frames": n_frames,
        "reliable_calibrated_frames": len(reliable_res),
        "unreliable_frames": n_frames - len(reliable_res),
        "reliable_frame_ratio": round(len(reliable_res) / max(n_frames, 1), 4),
        "median_residual_kw": (
            round(float(np.median(reliable_res)), 4) if reliable_res else None
        ),
        "p95_residual_kw": (
            round(float(np.percentile(reliable_res, 95)), 4) if reliable_res else None
        ),
        "median_right_hand_u_kw": round(float(np.median(r_us)), 2) if r_us else None,
        "median_left_hand_u_kw": round(float(np.median(l_us)), 2) if l_us else None,
        "runtime_sec": round(elapsed, 3),
    }

    if diagnostics_dir is not None:
        _render_keyboard_diagnostics(
            video_path,
            calibrations,
            best_ref_idx,
            Path(diagnostics_dir),
        )

    if out_json_path is not None:
        out_p = Path(out_json_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(
            json.dumps(
                {
                    "metadata": meta,
                    "frames": [c.to_dict() for c in calibrations],
                },
                indent=2,
            )
        )

    return calibrations, meta


def _render_keyboard_diagnostics(
    video_path: str | Path,
    calibrations: list[FrameCalibration],
    ref_idx: int,
    diag_dir: Path,
) -> None:
    """Save visual calibration check images at early pan, mid-piece, and unoccluded reference."""
    diag_dir.mkdir(parents=True, exist_ok=True)
    sample_idxs = sorted({30, 90, 150, 300, 450, ref_idx})
    sample_set = {i for i in sample_idxs if 0 <= i < len(calibrations)}

    container = av.open(str(video_path))
    try:
        v_stream = next(s for s in container.streams if s.type == "video")
        for idx, frame in enumerate(container.decode(v_stream)):
            if idx not in sample_set:
                continue
            bgr = frame.to_ndarray(format="bgr24")
            cal = calibrations[idx]
            if cal.h_white is not None and cal.h_black is not None:
                hw_inv = np.linalg.inv(np.asarray(cal.h_white, dtype=np.float64))
                hb_inv = np.linalg.inv(np.asarray(cal.h_black, dtype=np.float64))

                # Draw all 88 keys (A0..C8): white-key seams on H_white and black-key tips on H_black
                for midi_p in range(21, 109):
                    u_c = midi_to_canonical_u_center(midi_p)
                    if not is_black_key(midi_p):
                        # Draw white-key seam u_left = u_c - 0.5 (plus outer C8 seam u = 52.0)
                        seams_to_draw = [u_c - 0.5] + ([52.0] if midi_p == 108 else [])
                        for u_s in seams_to_draw:
                            pts = (hw_inv @ np.array([[u_s, 0.0, 1.0], [u_s, 1.0, 1.0]]).T).T
                            p0 = tuple(np.round(pts[0, :2] / pts[0, 2]).astype(int))
                            p1 = tuple(np.round(pts[1, :2] / pts[1, 2]).astype(int))
                            is_c = ((midi_p % 12) == 0 and u_s < 51.9) or u_s > 51.9
                            col = (0, 230, 0) if is_c else (180, 180, 40)
                            cv2.line(bgr, p0, p1, col, 2 if is_c else 1)
                        if (midi_p % 12) == 0 or midi_p == 21:
                            pm = (hw_inv @ np.array([u_c, 0.85, 1.0])).ravel()
                            px, py = int(round(pm[0] / pm[2])), int(round(pm[1] / pm[2]))
                            if 0 <= px < bgr.shape[1] and 0 <= py < bgr.shape[0]:
                                cv2.putText(
                                    bgr,
                                    midi_to_name(midi_p),
                                    (px - 14, py),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.55,
                                    (0, 255, 80),
                                    2,
                                )
                    else:
                        # Mark black-key tip on elevated H_black plane in magenta!
                        pt_b = (hb_inv @ np.array([u_c, 0.58, 1.0])).ravel()
                        bx, by = int(round(pt_b[0] / pt_b[2])), int(round(pt_b[1] / pt_b[2]))
                        if 0 <= bx < bgr.shape[1] and 0 <= by < bgr.shape[0]:
                            cv2.circle(bgr, (bx, by), 4, (255, 50, 255), -1)

            status_txt = (
                f"frame={idx} t={cal.pts_sec:.2f}s reliable={cal.reliable} "
                f"res={cal.residual_kw:.3f}kw inliers={cal.inlier_count} reason={cal.reason}"
            )
            cv2.rectangle(bgr, (15, 15), (1080, 62), (0, 0, 0), -1)
            cv2.putText(
                bgr,
                status_txt,
                (25, 48),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (80, 255, 80) if cal.reliable else (60, 120, 255),
                2,
            )
            cv2.imwrite(str(diag_dir / f"keyboard_cal_f{idx:04d}.jpg"), bgr)
    finally:
        container.close()
