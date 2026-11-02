"""Stage 1: Local piano audio note-attack transcription via PyAV + Transkun 2.0."""

from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path
import time
from typing import Any

import av
import moduleconf
import numpy as np
import torch

from .models import PerfNote


def extract_av_clock_and_audio(
    video_path: str | Path,
    target_fs: int = 44100,
) -> tuple[np.ndarray, dict[str, float]]:
    """Decode stereo float32 audio resampled to target_fs and measure A/V initial PTS offset.

    Returns:
        audio_stereo: float32 ndarray of shape (N, 2) in [-1.0, 1.0].
        clock_info: dict with video_first_pts_sec, audio_first_pts_sec, audio_minus_video_offset_sec,
                    video_duration_sec, audio_duration_sec, frame_count.
    """
    container = av.open(str(video_path))
    try:
        v_stream = next((s for s in container.streams if s.type == "video"), None)
        a_stream = next((s for s in container.streams if s.type == "audio"), None)
        if v_stream is None or a_stream is None:
            raise ValueError("Input media must contain both a video stream and an audio stream.")

        v_first_pts: float | None = None
        v_last_pts: float = 0.0
        v_count = 0
        for packet in container.demux(v_stream):
            for frame in packet.decode():
                if frame.pts is not None and frame.time_base is not None:
                    t = float(frame.pts * frame.time_base)
                    if v_first_pts is None:
                        v_first_pts = t
                    v_last_pts = max(v_last_pts, t)
                    v_count += 1

    finally:
        container.close()

    if v_first_pts is None:
        v_first_pts = 0.0

    container = av.open(str(video_path))
    try:
        a_stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(format="flt", layout="stereo", rate=target_fs)
        chunks: list[np.ndarray] = []
        a_first_pts: float | None = None

        for frame in container.decode(a_stream):
            if a_first_pts is None and frame.pts is not None and frame.time_base is not None:
                a_first_pts = float(frame.pts * frame.time_base)
            for rframe in resampler.resample(frame):
                arr = rframe.to_ndarray()
                # Interleaved 'flt' stereo from PyAV has shape (1, 2*samples) or (samples, 2) depending on version.
                if arr.ndim == 2 and arr.shape[0] == 1:
                    arr = arr.reshape(-1, 2)
                elif arr.ndim == 2 and arr.shape[0] == 2 and arr.shape[1] != 2:
                    arr = arr.T
                chunks.append(np.asarray(arr, dtype=np.float32))

        for rframe in resampler.resample(None):
            arr = rframe.to_ndarray()
            if arr.ndim == 2 and arr.shape[0] == 1:
                arr = arr.reshape(-1, 2)
            elif arr.ndim == 2 and arr.shape[0] == 2 and arr.shape[1] != 2:
                arr = arr.T
            chunks.append(np.asarray(arr, dtype=np.float32))
    finally:
        container.close()

    if a_first_pts is None:
        a_first_pts = 0.0

    audio = np.concatenate(chunks, axis=0) if chunks else np.zeros((0, 2), dtype=np.float32)
    audio_dur = float(audio.shape[0]) / float(target_fs)
    clock_info = {
        "video_first_pts_sec": v_first_pts,
        "audio_first_pts_sec": a_first_pts,
        "audio_minus_video_offset_sec": a_first_pts - v_first_pts,
        "video_span_sec": v_last_pts - v_first_pts,
        "audio_duration_sec": audio_dur,
        "video_frame_count": float(v_count),
    }
    return audio, clock_info


def transcribe_video_audio(
    video_path: str | Path,
    out_json_path: str | Path | None = None,
    device: str = "cpu",
) -> tuple[list[PerfNote], dict[str, Any]]:
    """Run local Transkun 2.0 piano transcription on the video's audio track.

    All emitted onset_sec and offset_sec timestamps are aligned to the video presentation
    clock relative to video_first_pts_sec (so t=0 matches the first video frame's PTS).
    """
    t0 = time.perf_counter()
    weight_path = str(files("transkun").joinpath("pretrained/2.0.pt"))
    conf_path = str(files("transkun").joinpath("pretrained/2.0.conf"))

    conf_mgr = moduleconf.parseFromFile(conf_path)
    transkun_cls = conf_mgr["Model"].module.TransKun
    conf = conf_mgr["Model"].config

    checkpoint = torch.load(weight_path, map_location=device, weights_only=False)
    model = transkun_cls(conf=conf).to(device)
    state_dict = checkpoint.get("best_state_dict", checkpoint.get("state_dict"))
    model.load_state_dict(state_dict, strict=False)
    model.eval()

    audio, clock_info = extract_av_clock_and_audio(video_path, target_fs=int(model.fs))
    offset_sec = clock_info["audio_minus_video_offset_sec"]

    with torch.no_grad():
        x = torch.from_numpy(audio).to(device)
        notes_est = model.transcribe(x, discardSecondHalf=False)

    # Sort deterministically by (onset, pitch); separate negative pedal CC events (-64, -67).
    raw_items = []
    pedal_count = 0
    for n in notes_est:
        onset = float(n.start) + offset_sec
        offset = float(n.end) + offset_sec
        pitch = int(n.pitch)
        vel = int(getattr(n, "velocity", 80))
        if pitch < 21 or pitch > 108:
            pedal_count += 1
            continue
        raw_items.append((onset, pitch, offset, vel))
    raw_items.sort(key=lambda item: (item[0], item[1]))

    perf_notes = [
        PerfNote(
            perf_event_id=f"perf_{idx:04d}",
            onset_sec=round(onset, 6),
            offset_sec=round(max(offset, onset + 0.01), 6),
            midi_pitch=pitch,
            velocity=vel,
        )
        for idx, (onset, pitch, offset, vel) in enumerate(raw_items)
    ]

    elapsed = time.perf_counter() - t0
    meta: dict[str, Any] = {
        "model": "transkun-2.0-pretrained",
        "device": device,
        "sample_rate_hz": int(model.fs),
        "runtime_sec": round(elapsed, 3),
        "note_count": len(perf_notes),
        "pedal_cc_event_count": pedal_count,
        "onset_range_sec": (
            [perf_notes[0].onset_sec, perf_notes[-1].onset_sec] if perf_notes else None
        ),
        "midi_pitch_range": (
            [min(n.midi_pitch for n in perf_notes), max(n.midi_pitch for n in perf_notes)]
            if perf_notes
            else None
        ),
        "clock": clock_info,
    }

    if out_json_path is not None:
        out_p = Path(out_json_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(
            json.dumps(
                {"metadata": meta, "notes": [n.to_dict() for n in perf_notes]},
                indent=2,
            )
        )

    return perf_notes, meta
