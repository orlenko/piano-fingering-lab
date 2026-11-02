"""Shared data models and pitch utilities across pipeline stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

NOTE_NAMES_SHARP = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
NOTE_NAMES_FLAT = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")

# Standard 88-key piano layout: MIDI 21 (A0) .. 108 (C8), 52 white keys (u in [0, 52]).
BLACK_PC = frozenset({1, 3, 6, 8, 10})
WHITE_PC_TO_INDEX = {0: 0, 2: 1, 4: 2, 5: 3, 7: 4, 9: 5, 11: 6}


def is_black_key(midi_pitch: int) -> bool:
    """Return True if midi_pitch corresponds to a black key."""
    return (midi_pitch % 12) in BLACK_PC


def midi_to_name(midi_pitch: int, prefer_flats: bool = True) -> str:
    """Convert MIDI pitch integer to scientific pitch notation (e.g., 60 -> C4, 70 -> Bb4)."""
    octave = (midi_pitch // 12) - 1
    names = NOTE_NAMES_FLAT if prefer_flats else NOTE_NAMES_SHARP
    return f"{names[midi_pitch % 12]}{octave}"


def midi_to_canonical_u_center(midi_pitch: int) -> float:
    """Return canonical lateral center u in [0, 52] white-key units (A0=[0,1], C8=[51,52]).

    White keys occupy unit intervals [k, k+1] with center k + 0.5.
    Black keys sit centered near the seam between adjacent white keys with slight
    physical asymmetry matching standard piano keybed geometry.
    """
    if midi_pitch < 21 or midi_pitch > 108:
        raise ValueError(f"MIDI pitch out of 88-key range [21, 108]: {midi_pitch}")

    # Count white keys strictly below midi_pitch starting at A0 (21).
    pc = midi_pitch % 12
    octave_from_c0 = (midi_pitch // 12) - 1  # A0 is octave 0 -> 21//12 - 1 = 0
    # C1 (24) starts white key index 2 (after A0=0, B0=1).
    if midi_pitch == 21:
        return 0.5  # A0
    if midi_pitch == 22:
        return 1.05  # A#0
    if midi_pitch == 23:
        return 1.5  # B0

    c_oct_idx = octave_from_c0 - 1  # C1 -> 0
    base_u = 2.0 + 7.0 * c_oct_idx
    if pc in WHITE_PC_TO_INDEX:
        return base_u + WHITE_PC_TO_INDEX[pc] + 0.5

    # Black key physical centers relative to C's left edge in white-key widths:
    # C# sits slightly left of C|D seam (1.0), D# slightly right of D|E seam (2.0),
    # F# slightly left of F|G seam (4.0), G# centered on G|A seam (5.0), A# slightly right of A|B seam (6.0).
    black_offsets = {
        1: 0.93,   # C#
        3: 2.07,   # D#
        6: 3.92,   # F#
        8: 5.00,   # G#
        10: 6.08,  # A#
    }
    return base_u + black_offsets[pc]


@dataclass
class PerfNote:
    """Unquantized transcribed performance note attack."""

    perf_event_id: str
    onset_sec: float
    offset_sec: float
    midi_pitch: int
    velocity: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreMeasure:
    """Extracted vector PDF measure geometry and meter."""

    measure: int
    page_index: int
    system_index: int
    x0_pt: float
    y0_pt: float
    x1_pt: float
    y1_pt: float
    treble_top_pt: float
    treble_bot_pt: float
    bass_top_pt: float
    bass_bot_pt: float
    staff_space_pt: float
    beats_per_bar: int
    beat_unit: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreNote:
    """Extracted vector PDF score note with native page coordinates."""

    score_note_id: str
    page_index: int
    system_index: int
    measure: int
    beat: float
    duration_beats: float
    staff: str  # "treble" | "bass"
    voice: int
    midi_pitch: int
    pitch_name: str
    x_pt: float
    y_pt: float
    bbox_pt: tuple[float, float, float, float]
    chord_group_id: str
    is_arpeggiated: bool = False
    is_tied_continuation: bool = False
    notehead_kind: str = "filled"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MeasureTiming:
    """Synchronized measure interval on the video presentation clock."""

    measure: int
    page_index: int
    system_index: int
    t_start_sec: float
    t_end_sec: float
    matched_note_count: int
    provenance: str = "auto"
    auto_t_start_sec: float | None = None
    auto_t_end_sec: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HandObservation:
    """Single detected hand in top-left pixel coordinates."""

    det_index: int
    detector_chirality: str  # "L" | "R" | "unknown"
    resolved_hand: str  # "L" | "R" | "ambiguous"
    palm_cross: float
    hand_confidence: float
    landmarks: dict[str, tuple[float, float, float] | None]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FramePose:
    """Full-frame two-hand pose detection result."""

    frame_index: int
    pts_sec: float
    width: int
    height: int
    hands: list[HandObservation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FrameCalibration:
    """Per-frame planar keyboard homographies (white plane Z=0 and black top plane Z=h_black)."""

    frame_index: int
    pts_sec: float
    h_white: list[list[float]] | None
    h_black: list[list[float]] | None
    residual_kw: float
    inlier_count: int
    reliable: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateFinger:
    """Visually supported candidate finger for a note attack."""

    hand: str  # "L" | "R"
    finger: int  # 1..5
    cost: float
    delta_u_kw: float
    v_norm: float
    slip_kw_per_s: float
    mean_tip_conf: float
    supporting_frames: int

    @property
    def label(self) -> str:
        return f"{self.hand}{self.finger}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["label"] = self.label
        return d


@dataclass
class PredictionRecord:
    """Reviewable per-event fingering prediction and provenance record."""

    event_id: str
    alignment_status: str  # "matched" | "unmatched_score" | "unmatched_perf"
    perf_event_id: str | None
    score_note_id: str | None
    onset_sec: float | None
    offset_sec: float | None
    midi_pitch: int
    pitch_name: str
    page_index: int | None
    measure: int | None
    beat: float | None
    staff: str | None
    chord_group_id: str | None
    auto_hand: str  # "L" | "R" | "unknown"
    auto_finger: str  # "1".."5" | "unknown"
    auto_confidence_tier: str  # "high" | "low" | "unknown"
    cost_margin: float | None
    abstain_reason: str | None
    candidate_fingers: list[CandidateFinger] = field(default_factory=list)
    supporting_frame_pts: list[float] = field(default_factory=list)
    calibration_residual_kw: float | None = None
    final_hand: str = "unknown"
    final_finger: str = "unknown"
    final_confidence_tier: str = "unknown"
    provenance: str = "auto"  # "auto" | "manual_override"
    musician_verdict: str = ""
    musician_corrected_finger: str = ""
    musician_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
