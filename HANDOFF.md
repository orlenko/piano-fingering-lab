# Build the first piano fingering teaching video

> Desktop update (2026-11-03): the native internal alpha and reviewed architecture are documented in `docs/desktop.md` and `docs/desktop-plan.md`. Original private proof-of-concept deliverables remain unchanged in `.local/out/`. The alpha has local workflow tests; it is not a notarized, second-Mac-qualified public release.

> Implementation update (2026-11-02): the local proof of concept now exists. See `README.md` for execution, `docs/experiment-log.md` for measured aggregates and limitations, and `docs/review.md` for the independent review. The bootstrap state below is historical context. Private deliverables remain in `.local/out/`.

## Immediate instruction

Produce a proof of concept from the video and PDF already supplied by the operator. It should identify the pianist's actual fingers, highlight the current measure in the score, and render a video with hands on the left and score on the right. Also produce a separately annotated score or excerpt. The operator will show the outputs to the musician who played; she will judge whether the fingerings are right.

Do the best-effort processing first. Do not require the non-musician operator to transcribe or label 20–40 note attacks before starting. That was an earlier research proposal and has been superseded by the operator's instruction. Confidence, unknowns, and a reviewable event list should make the initial output useful even when imperfect.

Start with local models/tools. If local results are inadequate, identify the particular missing capability and the hosted API/model access needed. Do not silently upload the private media or incur paid inference. No hosted credentials have been provided.

## Local handoff state

Read `.local/inputs.json` for absolute input paths and inspection locations. That manifest is intentionally not tracked. The source files remain unchanged at their original locations. Existing diagnostic output is copied into `.local/inspection/`.

The input video is approximately 22.24 seconds, 1920 × 1080, nominally 30 fps, with audio. The camera moves, the keyboard is diagonal, and the late part leaves the keyboard. The supplied PDF has a cover plus three digitally typeset notation pages. No separate performance MIDI or MusicXML was supplied. The exact performed score range is not yet established.

A local Apple Vision hand-pose probe ran on 43 half-second samples. It returned two hands on 35 of 36 samples in the first 18 seconds. This tested landmark localization only: no finger-to-note assignment or score synchronization has been performed. The private JSON preserves actual frame timestamps and landmark confidences. Detection-order colors in overlays are not stable hand identities.

No prototype pipeline, fingered PDF, synchronized MP4, model environment, or downloaded checkpoint exists yet. This repository is a clean bootstrap and this handoff, not an implementation.

## Suggested implementation path

1. Inspect the actual clip and PDF, and write a small executable design. Have a separate agent challenge it. Follow the operator's output-first evaluation order.
2. Establish a local Python 3.11 environment and select a piano transcription model. [Transkun](https://github.com/Yujia-Yan/Transkun) has pretrained audio-to-MIDI inference and a CPU CLI path. Evaluate actual runtime and note-event output on the supplied clip. [Aria-AMT](https://github.com/EleutherAI/aria-amt) and [Basic Pitch](https://github.com/spotify/basic-pitch) are alternatives.
3. Recover score semantics and page positions. This is a vector/font-based PDF: [PDFtoMusic Pro](https://www.myriad-online.com/en/products/pdftomusicpro.htm) is a possible vector-conversion route; [Audiveris](https://github.com/Audiveris/audiveris) is a local OMR/correction option. Do not assume ordinary PDF text extraction produces musical note semantics.
4. Align the performed excerpt to the score. [Partitura](https://github.com/CPJKU/partitura) and [Parangonar](https://github.com/sildater/parangonar) support symbolic representation and note matching. Do not stretch a short excerpt across the complete piece or assume it starts at measure one.
5. Track fingers locally using [MediaPipe Hand Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker) with two hands or the available native Apple Vision baseline. Calibrate keys to absolute pitches, including an octave anchor. Account for camera movement; leave unknowns when contact or calibration is ambiguous. Inspect temporal windows around note attacks and handle chord notes jointly.
6. Render the original score beside the video, with measure highlights and finger labels. Retain actual media timestamps, source-note identities where established, and explicit provenance for manual timing or edits. A separate reviewable event table should allow the musician to correct predictions. Export the best usable excerpt if the entire recording cannot be analyzed reliably, and disclose its coverage.

The implementation agent can choose a smaller local route if it produces the requested artifacts faster and preserves honesty about what was automated. Avoid a new web platform, training system, or live follower before producing the first media output.

## Useful existing work and caveats

- [PianoVAM ASDF](https://github.com/yonghyunk1m/PianoVAM-Code) is the closest existing observed-fingering workflow: performance video plus MIDI, keyboard calibration, hand landmarks, candidate fingers, and human correction. Its repository license was not established during research; use it as a methodological reference until code reuse is cleared. Do not mistake a dataset license for the code's license.
- [At Your Fingertips](https://arxiv.org/html/2303.03745v1) demonstrates observed fingering extraction using video and corresponding MIDI. Its published performance is not a promise for this input.
- [Matchmaker Demo](https://github.com/pymatchmaker/matchmaker-demo) has recorded-file simulation, Audiveris PDF processing, and measure highlighting. It is a prototype with experimental PDF support. Its mapping uses Audiveris `BINARY.png` pages; validate registration before applying those coordinates to another rendering of the PDF. It does not provide a complete hands-video compositor or MP4 exporter.
- [V2N](https://github.com/yonghyunk1m/V2N) has released video-to-MIDI weights, but predicts note events rather than finger identities and expects a normalized keyboard crop. Treat it as an alternative if the audio/geometry route fails.
- A suggested ergonomic fingering is not an observation of the pianist's choice. Sequence priors may rank visually supported candidates; keep unsupported cases uncertain.
- MIDI, if later available, reduces transcription uncertainty but still needs synchronization. Multi-camera capture is a future advantage; do not wait for another recording to try the supplied files.
- Keep purchased notation, personal media, detailed inferred labels, and diagnostic imagery private. Only code, methods, and sanitized aggregate results belong in this public repo.

## Completion report

Give the operator clickable paths to the resulting video, annotated score, and reviewable prediction table. State the analyzed time/score range, automatic stages, manual interventions, uncertain coverage, and any actual need for hosted models. Do not claim musician-verified correctness before she evaluates it.
