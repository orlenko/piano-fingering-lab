# Sanitized Experiment Log — Proof-of-Concept Run

This log records architectural decisions, bugs caught during stage testing and visual diagnostics, and sanitized aggregate metrics from the offline proof-of-concept pipeline ([src/piano_fingering/](../src/piano_fingering/)). No local paths, filenames, musical titles, watermarks, or copyrighted pitch sequences are stored here.

## 1. Key Engineering Decisions & Discoveries

1. **Audio-to-Video Container Clock Alignment (`transcribe.py`)**:
   - Decoding the input MP4 container via `PyAV` revealed a `+0.158896 s` initial timestamp offset between the audio stream (`audio_first_pts_sec`) and video stream (`video_first_pts_sec`).
   - Adding `(audio_first_pts_sec - video_first_pts_sec)` to all `Transkun 2.0` note onsets/offsets aligned audio attacks directly to the video presentation timestamp (`PTS`) clock (`5.5 ms` median in-sample alignment fit residual, not independently measured attack accuracy).
   - Programmatic invocation of `Transkun 2.0` via `importlib.resources` and `PyAV` float32 stereo resampling bypassed broken upstream CLI dependencies (`pkg_resources` removal in `setuptools>=82` and external `pydub`/`ffmpeg` assumptions). Negative pedal CC events (`-64`, `-67`) emitted by `Transkun` were separated from piano pitches (`21..108`).

2. **Permissive Native Vector PDF Extraction (`score_pdf.py`, `render.py`)**:
   - Replaced AGPL-licensed PDF libraries with permissive dependencies (`pdfplumber`, `pypdfium2`, `pypdf`, `reportlab`).
   - Direct extraction of staff lines, barlines, stems, beams, accidentals, ties, wavy arpeggio glyphs, and music-font noteheads auto-calibrated the music font's baseline offset (`+1.0083 pt`), matched `11/11` printed system measure-number anchors, and achieved exact beat-duration consistency on `77/80` single-staff measures (the remaining `3/80` being multi-voice measures handled via vertical voice splitting).

3. **Exact-Pitch Subsequence Excerpt Alignment (`align.py`)**:
   - Rather than assuming performance from Measure 1 to the end of the score or folding pitches into octave-invariant chroma, subsequence search scored exact MIDI pitch sets and inter-onset intervals across all candidate measure ranges.
   - Identified the performed excerpt (`mm. 1–16` on Page 2, `t = 2.6501..19.4647 s`, stopping on the downbeat of `m. 16`) with a `1.429x` top-1-to-top-2 non-overlapping score margin (`136/140` transcribed notes matched = `97.1%` automatic performance-to-score agreement; `136/152` excerpt score attacks matched = `89.5%` automatic score-attack match coverage).

4. **Behind-Music-Desk Camera Geometry & Rotation-Invariant Chirality (`hand_pose.py`, `render.py`)**:
   - The source camera sits behind the music stand looking toward the pianist (`1920x1080` VFR, `667` frames): raw left = treble / pianist's right hand, raw right = bass / pianist's left hand.
   - Full-rate two-hand pose extraction via compiled Swift `AVAssetReader` + `VNDetectHumanHandPoseRequest` converted normalized bottom-left Vision coordinates to top-left pixel coordinates (`y_px = (1 - y_vn) * H`) and filtered `confidence == 0` fallback joints.
   - Dorsal metacarpal cross-product chirality (`(middle_mcp - wrist) x (little_mcp - index_mcp) > 0 => R` in top-left image coordinates) agreed with `VNChirality` on `99.73%` (`1093/1096`) of confident hand detections across camera tilts and thumb-under crossings.
   - Rotating the left video pane `180°` inside a full-width `960x540` letterbox (`960x1080` half-canvas) restored natural Pianist POV (bass left, treble right) without cropping fingertips at either edge of the keyboard, with upright badges drawn post-rotation.

5. **Dual-Plane 88-Key Calibration & Early-Pan Octave-Alias Fix (`keyboard.py`)**:
   - Calibrated separate planar homographies `H_white` (`Z = 0` white-key surface) and `H_black` (`Z = h_black` elevated black-key top plane) from an unoccluded post-performance frame (`frame 596`, `t = 19.81 s`), approximating elevated-key geometry on angled attacks. Propagation uses a fixed reference correction and does not eliminate translation-dependent parallax.
   - **Bug caught via visual diagnostics**: Initial unseeded direct optical flow (`ref -> cur`) aliased onto the periodic octave lattice (`-14.0` white-key-widths = `-2` octaves) during an `~800 px` camera pan from high treble (`C8` cheek block visible at `t < 3.4 s`) to bass (`A0` cheek block visible at `t > 4.3 s`).
   - **Fix**: Expanding the canonical key grid to the full 88-key range `u in [0, 52]`, seeding reference optical flow from `inv(H_prev) @ H_ref` (`OPTFLOW_USE_INITIAL_FLOW`), enforcing inter-frame physical continuity (`|du| <= 1.35` key-widths/frame), and verifying white-key apron brightness against dark cheek-block wood eliminated all octave jumps (`0` reliable jumps `> 1.2` key-widths across all `667` frames; `0.045` key-width median residual, `0.120` key-width p95 residual).

6. **Order-Constrained Chord/Roll DP & Honest Abstention (`assign.py`)**:
   - Simultaneous attacks (`|dt| <= 45 ms`) and rolled chords sharing a score `chord_group_id` (`|dt| <= 250 ms`) were solved jointly via an exact dynamic program over `(last_L, last_R, pitch_L, pitch_R)` states enforcing strict intra-hand anatomical pitch monotonicity (`L5 < L4 < L3 < L2 < L1` and `R1 < R2 < R3 < R4 < R5`), mutual finger exclusion (including tied-pitch duplicate-note guards), and per-note partial-chord abstention (`unknown`).
   - Notably, in Measure 1 (`t = 2.65..3.05 s`), while the camera was still framed on the treble register before panning left, the pianist's left-hand bass dyad was physically outside the camera frame; the solver honestly abstained (`?`, `no_finger_within_gate`) on the off-camera bass notes while labeling the visible right-hand chord and melody notes.

7. **Closed-Loop VFR & Audio Sync Verification (`render.py`)**:
   - Preserved exact source `AVFrame.pts` ticks and `time_base` into `libx264` (`max_vfr_pts_error_ms = 0.1556 ms` across `667/667` muxed frames) and added closed-loop `PyAV` measurement of `(audio_first_pts - video_first_pts)` on the muxed `.mp4` with automatic `-itsoffset` compensation (`av_offset_error_ms = 0.0 ms`).

## 2. Sanitized Aggregate Metrics (Proof-of-Concept Run)

| Stage / Metric | Value |
| :--- | :--- |
| Video frames / VFR fidelity (`max_vfr_pts_error_ms`) | `667` frames / `0.1556 ms` |
| Muxed A/V clock offset error (`av_offset_error_ms`) | `0.0 ms` (source offset `+158.9 ms` preserved) |
| Transcribed piano note attacks (`Transkun 2.0`, local CPU) | `140` (`t = 2.56..19.06 s`; `15` pedal CC events filtered) |
| Parsed vector PDF measures / noteheads | `40` measures / `516` noteheads (`513` attacks, `3` ties, `116` arpeggiated) |
| Printed measure-number anchors / single-voice beat checks | `11/11` (`100%`) / `77/80` (`96.25%`) |
| Aligned performed excerpt | Measures `1–16` (Page 2), `t = 2.65..19.46 s` (`1.429x` top-1/top-2 ratio) |
| Automatic score match coverage / performance agreement / median in-sample fit residual | `136/152` (`89.47%`) / `136/140` (`97.14%`) / `5.5 ms` |
| Two-hand pose frames / dorsal-palm chirality agreement | `584/667` frames / `99.73%` |
| Reliable keyboard-calibrated frames / median (`p95`) residual | `599/667` (`89.81%`, `100%` of playing span) / `0.045 kw` (`0.120 kw`) |
| Emitted fingerings over matched attacks (`136`) | `130/136` (`95.59%`): `122` high-confidence, `8` low-confidence `(n?)` |
| Emitted fingerings over all excerpt score attacks (`152`) | `130/152` (`85.53%`) |
| Abstained (`unknown` / `?`) score attacks (`22` total) | `16` `no_transcribed_onset`, `3` `no_finger_within_gate`, `3` `ambiguous_candidates` |
| Manual overrides applied (`finger` / `measure_timing`) | `0` / `0` (`100%` automatic output) |

## 3. Evaluation Status & Inference Provenance

- **Measurement limits**: Counts compare automatic stages against one another, not against independent reference labels. The 5.5 ms residual is computed after fitting the same matched onsets. High/low fingering tiers, calibration residuals, and alignment score ratios are heuristic diagnostics rather than accuracy measurements. The excerpt finder is a greedy elastic candidate search, not a globally optimal subsequence dynamic program. Tests exercise selected synthetic geometry, alignment, overrides and failure paths; full accidental/chord/tie parsing and finger identity accuracy are not independently validated.
- **Musician evaluation pending**: No operator-fabricated ground-truth finger labels were created. Accuracy of the `130` emitted fingerings (`122` high-confidence, `8` low-confidence) must be judged directly by the pianist who recorded the video using `.local/out/teaching_video.mp4`, `.local/out/annotated_score.pdf`, and `.local/out/predictions.csv`.
- **Local vs. hosted compute**: `100%` of pipeline execution runs offline on local hardware with zero network calls. During development, rendered diagnostic PNG/JPEG frames in `.local/out/diagnostics/` were visually inspected by the coding assistant in the local IDE session to catch and verify fixes for the early-pan octave alias and bottom-system score cropping.


## 4. Takeover review and fresh execution (2026-11-02)

The abrupt prior handoff was reconciled against the working tree and existing local artifacts. Independent review and re-review are recorded in [review.md](review.md). A fresh seven-stage local run reproduced the aggregate coverage and calibration values above, including 130 emitted fingerings, 22 unknown score attacks and zero manual edits. The recomputed non-overlapping alignment ratio is 1.429 (the earlier cached run recorded 1.552); the selected excerpt and matched-note counts are unchanged, and the current heuristic ambiguity flag is false. This is an internal score margin, not a correctness probability.

All 667 output frames were preserved; measured maximum relative PTS error was 0.1556 ms and A/V initial-offset error was 0.0 ms. These describe container timing only. No additional hosted model access was needed.

The final fresh run completed in 75.6 seconds. Eight composite frames spanning the early pan, steady playing, final attack and post-performance departure were inspected, along with the final annotated excerpt. Labels were legible and no obvious symbol-obscuring collisions were seen in that excerpt. A full decode comparison confirmed identical audio sample bytes and relative audio-frame timestamps before and after muxing. The current cache manifest also passed validation against input bytes, source code, dependency manifests, device and generated stage outputs. The staged-tree privacy and synthetic suite passed all 21 tests. These checks do not replace the musician's pending fingering assessment.
