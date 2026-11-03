"""Local desktop protocol and transactional, versioned musician projects.

No project data is imported as code. All mutations share a project flock. Native
ownership/finalization clears long-job leases only after owned-child cleanup.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
import copy
import ctypes
import errno
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import sys
import tempfile
import time
import traceback
from typing import Any, Iterator
import uuid

SCHEMA = 1
MAX_JSON = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 512 * 1024 * 1024
MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_FRAMES = 1000
MAX_DURATION = 30.05
MAX_NOTES = 2000
OUTPUTS = {
    "video": "teaching_video.mp4", "score": "annotated_score.pdf",
    "excerpt": "annotated_excerpt.png", "notes": "predictions.csv",
}
STAGES = ["Listening to the recording", "Reading the score",
          "Finding where you played in the score", "Following your hands",
          "Locating the keyboard", "Estimating fingerings", "Preparing the video and score"]
REASONS = {
    "no_frames_in_attack_window": "No usable hand frames were available around this audio attack.",
    "chord_order_or_gate_abstention": "The visible fingertips did not give a consistent assignment for this chord.",
    "no_transcribed_onset": "The app could not match an audio note here.",
    "no_finger_within_gate": "No fingertip had enough visual support near this key.",
    "ambiguous_candidates": "The available fingertip evidence was ambiguous.",
    "ambiguous_score_alignment": "The performed score passage could not be distinguished reliably.",
    "calibration_unreliable": "The keyboard position was not reliable at this moment.",
    "no_hand_detected": "A hand could not be detected near this note.",
    "low_landmark_confidence": "The fingertip locations were not clear enough.",
    "unmatched_audio_onset": "This audio note was not matched to the score.",
}


class DesktopError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def fail(code: str, message: str) -> None:
    raise DesktopError(code, message)


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _json(path: Path) -> Any:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_JSON:
        fail("project_invalid", "A project record is missing, unsafe or too large.")
    try:
        def pairs(items):
            out = {}
            for key, value in items:
                if key in out:
                    raise ValueError("duplicate key")
                out[key] = value
            return out
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(MAX_JSON + 1)
        if len(data) > MAX_JSON:
            fail("project_invalid", "The project record is too large.")
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    except (ValueError, UnicodeError, RecursionError):
        fail("project_invalid", "A project record is damaged or unsupported.")


def _path(root: Path, relative: str) -> Path:
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in ("..", ".") for p in parts):
        fail("project_invalid", "The project contains an unsafe path.")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            fail("project_invalid", "Linked project contents are not supported.")
    return path


def _atomic(path: Path, value: Any) -> None:
    if path.is_symlink():
        fail("project_invalid", "A project record is an unsafe link.")
    data = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    if len(data) > MAX_JSON:
        fail("project_invalid", "The project record exceeds this version's limit.")
    fd, temporary = tempfile.mkstemp(prefix=".save-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _copy_file(source: Path, destination: Path, limit: int) -> None:
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as incoming:
        info = os.fstat(incoming.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            fail("project_invalid", "A project component is unsafe or exceeds its size limit.")
        with destination.open("xb") as outgoing:
            copied = 0
            while block := incoming.read(min(1024 * 1024, limit - copied + 1)):
                copied += len(block)
                if copied > limit:
                    fail("project_invalid", "A project component grew beyond its size limit.")
                outgoing.write(block)


def _exclusive_rename(source: Path, destination: Path) -> None:
    """Atomic directory publication with no overwrite, including empty directories."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        call = libc.renamex_np
        call.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = call(os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        call = libc.renameat2
        call.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = call(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    else:
        fail("unsupported", "This platform cannot safely publish the export folder.")
    if result:
        error = ctypes.get_errno()
        if error in (errno.EEXIST, errno.ENOTEMPTY):
            fail("destination_exists", "That name already exists. Choose a new name; nothing was replaced.")
        raise OSError(error, os.strerror(error))


def _name(value: str) -> str:
    value = re.sub(r"[/:\x00-\x1f]", "-", value).strip().strip(".")[:100]
    return value or "Untitled project"


def _overrides(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict) or len(value) > MAX_NOTES:
        fail("project_invalid", "The saved corrections are invalid.")
    for key, entry in value.items():
        if not isinstance(key, str) or not re.fullmatch(r"ev_[0-9]{4,8}", key):
            fail("project_invalid", "A correction has an invalid note identity.")
        if not isinstance(entry, dict) or set(entry) != {"hand", "finger"}:
            fail("project_invalid", "A saved correction is invalid.")
        if not ((entry["hand"] in ("L", "R") and entry["finger"] in ("1", "2", "3", "4", "5"))
                or entry == {"hand": "unknown", "finger": "unknown"}):
            fail("project_invalid", "Choose both a hand and a finger, or Unknown.")
    return value


def open_project(path: str | Path) -> tuple[Path, dict[str, Any]]:
    root = Path(path).expanduser().resolve(strict=True)
    if not root.is_dir() or root.suffix != ".fingeringproject":
        fail("project_invalid", "Choose a Fingering Studio project.")
    manifest = _json(_path(root, "project.json"))
    if not isinstance(manifest, dict) or type(manifest.get("schema")) is not int or manifest.get("schema") != SCHEMA or not _uuid(manifest.get("id")):
        fail("project_invalid", "This project version is damaged or unsupported.")
    if not isinstance(manifest.get("name"), str) or not 0 < len(manifest["name"]) <= 120:
        fail("project_invalid", "The project name is invalid.")
    if manifest.get("videoExtension") not in (".mov", ".mp4", ".m4v"):
        fail("project_invalid", "The project recording type is unsupported.")
    if manifest.get("status") not in ("awaiting", "working", "ready", "failed", "stopped"):
        fail("project_invalid", "The project state is unsupported.")
    if type(manifest.get("editRevision")) is not int or not 0 <= manifest["editRevision"] <= 1_000_000_000:
        fail("project_invalid", "The correction revision is invalid.")
    _overrides(manifest.get("edits"))
    if manifest.get("currentRun") is not None and not _uuid(manifest["currentRun"]):
        fail("project_invalid", "The saved result identity is invalid.")
    job = manifest.get("activeJob")
    if job is not None and (not isinstance(job, dict) or not _uuid(job.get("id"))
                             or job.get("operation") not in ("analyze", "render", "export")):
        fail("project_invalid", "The saved job identity is invalid.")
    for name in ("Inputs", "Runs"):
        if not _path(root, name).is_dir():
            fail("project_invalid", "The project is missing a required folder.")
    return root, manifest


@contextmanager
def _lock(root: Path) -> Iterator[None]:
    path = _path(root, ".lock")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            fail("project_invalid", "The project lock is unsafe.")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("busy", "Another Fingering Studio window is working on this project.")
        yield
    finally:
        os.close(fd)


def _idle(manifest: dict[str, Any]) -> None:
    if manifest["activeJob"] is not None:
        fail("recovery_needed", "An earlier job has not been finalized. Reopen it in its window, or make a recovery copy.")


def _inputs(root: Path, manifest: dict[str, Any]) -> tuple[Path, Path]:
    video = _path(root, "Inputs/video" + manifest["videoExtension"])
    score = _path(root, "Inputs/score.pdf")
    if not video.is_file() or not score.is_file() or video.stat().st_size > MAX_VIDEO_BYTES or score.stat().st_size > MAX_PDF_BYTES:
        fail("missing_inputs", "A copied input is missing. Restore the project copy or create a new project.")
    return video, score


def inspect_inputs(video_path: str | Path, score_path: str | Path) -> dict[str, Any]:
    import av
    import pdfplumber
    from .score_pdf import NOTEHEAD_CHARS, parse_vector_score_pdf
    video, score = Path(video_path).resolve(strict=True), Path(score_path).resolve(strict=True)
    if (video.suffix.lower() not in (".mov", ".mp4", ".m4v") or not video.is_file()
            or video.stat().st_size > MAX_VIDEO_BYTES):
        fail("video_limits", "Choose a MOV or MP4 recording no larger than 512 MB.")
    if score.suffix.lower() != ".pdf" or not score.is_file() or score.stat().st_size > MAX_PDF_BYTES:
        fail("score_limits", "Choose a score PDF no larger than 10 MB.")
    with av.open(str(video)) as container:
        stream = next((s for s in container.streams if s.type == "video"), None)
        if stream is None:
            fail("video_invalid", "No playable video was found.")
        width, height = stream.codec_context.width, stream.codec_context.height
        if not 0 < width <= 1920 or not 0 < height <= 1080:
            fail("video_limits", "This experimental version supports landscape video up to 1920 × 1080. Export a smaller excerpt.")
        if not any(s.type == "audio" for s in container.streams):
            fail("no_audio", "This recording has no sound. Choose a recording with piano audio.")
        first, previous, count = None, None, 0
        for frame in container.decode(stream):
            count += 1
            if count > MAX_FRAMES or not 0 < frame.width <= 1920 or not 0 < frame.height <= 1080:
                fail("video_limits", "Use an excerpt up to 30 seconds and 1,000 frames, at no more than 1080p.")
            if frame.pts is None or frame.time_base is None:
                fail("video_invalid", "This recording has missing video timestamps. Export a fresh MOV or MP4.")
            t = float(frame.pts * frame.time_base)
            if not math.isfinite(t) or (previous is not None and t <= previous):
                fail("video_invalid", "This recording has unsupported video timing.")
            first = t if first is None else first
            previous = t
            if t - first > MAX_DURATION:
                fail("video_limits", "Choose an excerpt up to 30 seconds for this experimental version.")
        if not count:
            fail("video_invalid", "This recording contains no decodable frames.")
        duration = (previous or 0) - (first or 0)
    samples, audio_frames, rate, audio_first, audio_end = 0, 0, None, None, None
    with av.open(str(video)) as container:
        audio = next(s for s in container.streams if s.type == "audio")
        for frame in container.decode(audio):
            audio_frames += 1
            if audio_frames > 10000 or not 8000 <= frame.sample_rate <= 96000 or not 1 <= len(frame.layout.channels) <= 2:
                fail("audio_limits", "Use a recording with mono or stereo audio at a standard sample rate.")
            rate = frame.sample_rate if rate is None else rate
            if frame.sample_rate != rate:
                fail("audio_limits", "The recording changes audio sample rate. Export a fresh MOV or MP4.")
            samples += frame.samples
            if samples > rate * 31:
                fail("audio_limits", "The audio track is longer than this version's 31-second limit.")
            if frame.pts is None or frame.time_base is None:
                fail("audio_limits", "The recording has missing audio timestamps.")
            t = float(frame.pts * frame.time_base)
            if not math.isfinite(t) or (audio_end is not None and abs(t - audio_end) > 0.25):
                fail("audio_limits", "The recording has discontinuous audio timing.")
            audio_first = t if audio_first is None else audio_first
            audio_end = t + frame.samples / rate
            if audio_end - audio_first > 31.05:
                fail("audio_limits", "The audio timeline exceeds this version's limit.")
    if not samples:
        fail("no_audio", "The recording's audio could not be decoded.")
    with pdfplumber.open(str(score)) as pdf:
        if not 1 <= len(pdf.pages) <= 12:
            fail("score_limits", "Choose a score of at most 12 pages.")
        recognized = 0
        for page in pdf.pages:
            if not all(_finite(v) and v > 0 for v in (page.width, page.height)) or page.width > 1000 or page.height > 1500:
                fail("score_limits", "The score page dimensions exceed this experimental version's limit.")
            objects = page.objects
            if sum(len(values) for values in objects.values()) > 30000:
                fail("score_limits", "This score is too complex for this experimental version.")
            recognized += sum("Doremi" in c.get("fontname", "") and c["text"] in NOTEHEAD_CHARS for c in page.chars)
        if not 0 < recognized <= MAX_NOTES:
            fail("unsupported_score", "This version reads a limited family of digitally typeset piano scores. Scans and many notation-software exports are not supported yet.")
    try:
        measures, notes, _ = parse_vector_score_pdf(score)
    except Exception as error:
        raise DesktopError("unsupported_score", "The score's notation could not be read reliably. Try a supported edition.") from error
    if not measures or not 0 < len(notes) <= MAX_NOTES:
        fail("unsupported_score", "The app could not identify enough supported notation in this PDF.")
    return {"videoName": video.name, "scoreName": score.name, "duration": round(duration, 3),
            "width": width, "height": height, "frames": count,
            "pages": len({m.page_index for m in measures}), "measures": len(measures),
            "warning": "Keep both hands and the bass end visible. Camera and keyboard compatibility are established during analysis."}


def create_project(video: str, score: str, destination: str, name: str) -> Path:
    inspect_inputs(video, score)
    parent = Path(destination).expanduser().resolve(strict=True)
    if not parent.is_dir():
        fail("destination_invalid", "Choose a folder for the project.")
    if shutil.disk_usage(parent).free < Path(video).stat().st_size + Path(score).stat().st_size + 512 * 1024 * 1024:
        fail("disk_space", "Free at least 512 MB plus space for the copied inputs before continuing.")
    name = _name(name)
    target = parent / (name + ".fingeringproject")
    staging = Path(tempfile.mkdtemp(prefix=".fingering-new-", dir=parent))
    try:
        (staging / "Inputs").mkdir()
        (staging / "Runs").mkdir()
        extension = Path(video).suffix.lower()
        _copy_file(Path(video), staging / "Inputs" / ("video" + extension), MAX_VIDEO_BYTES)
        _copy_file(Path(score), staging / "Inputs/score.pdf", MAX_PDF_BYTES)
        inspect_inputs(staging / "Inputs" / ("video" + extension), staging / "Inputs/score.pdf")
        manifest = {"schema": SCHEMA, "id": str(uuid.uuid4()), "name": name,
                    "created": time.time(), "videoExtension": extension,
                    "videoName": Path(video).name, "scoreName": Path(score).name,
                    "status": "awaiting", "currentRun": None, "editRevision": 0,
                    "edits": {}, "activeJob": None, "lastError": None}
        _atomic(staging / "project.json", manifest)
        _exclusive_rename(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target


def _run(root: Path, manifest: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    run_id = manifest["currentRun"]
    if not _uuid(run_id):
        fail("no_results", "This project has not completed an analysis yet.")
    directory = _path(root, "Runs/" + run_id)
    record = _json(_path(directory, "run.json"))
    if not isinstance(record, dict) or record.get("schema") != SCHEMA or record.get("status") != "complete":
        fail("project_invalid", "The saved result is incomplete or damaged.")
    _overrides(record.get("overrides"))
    digests = record.get("outputs")
    if not isinstance(digests, dict) or set(digests) != set(OUTPUTS.values()):
        fail("project_invalid", "The saved output integrity record is missing.")
    for name in OUTPUTS.values():
        path = _path(directory, name)
        if not path.is_file() or not 0 < path.stat().st_size <= 1024 * 1024 * 1024:
            fail("project_invalid", "A completed output is missing. Reanalyze in a new result version.")
        if not isinstance(digests[name], str) or _digest(path) != digests[name]:
            fail("project_invalid", "A saved output has changed or is damaged. Reanalyze to create a fresh result.")
    return directory, record


def _predictions(directory: Path) -> list[dict[str, Any]]:
    value = _json(_path(directory, "automatic_predictions.json"))
    rows = value.get("predictions") if isinstance(value, dict) else None
    if not isinstance(rows, list) or len(rows) > MAX_NOTES:
        fail("project_invalid", "The saved note list is invalid or too large.")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("event_id"), str) or not re.fullmatch(r"ev_[0-9]{4,8}", row["event_id"]) or row["event_id"] in seen:
            fail("project_invalid", "The saved note identities are invalid.")
        seen.add(row["event_id"])
        if not isinstance(row.get("pitch_name"), str) or not re.fullmatch(r"[A-G](?:b|#)?[0-8]", row["pitch_name"]):
            fail("project_invalid", "The saved pitch label is invalid.")
        if row.get("measure") is not None and (type(row["measure"]) is not int or not 1 <= row["measure"] <= 10000):
            fail("project_invalid", "The saved measure is invalid.")
        if type(row.get("midi_pitch")) is not int or not 21 <= row["midi_pitch"] <= 108:
            fail("project_invalid", "The saved pitch data is invalid.")
        for key in ("onset_sec", "offset_sec", "beat", "cost_margin", "calibration_residual_kw"):
            if row.get(key) is not None and (not _finite(row[key]) or abs(row[key]) > 10000):
                fail("project_invalid", "The saved timing or measurement data is invalid.")
        if row.get("auto_hand") not in ("L", "R", "unknown") or row.get("auto_finger") not in ("1", "2", "3", "4", "5", "unknown") or row.get("auto_confidence_tier") not in ("high", "low", "unknown"):
            fail("project_invalid", "The saved automatic fingering data is invalid.")
    return rows


def review_project(project: str | Path) -> dict[str, Any]:
    root, m = open_project(project)
    response = {"project": str(root), "name": m["name"], "status": m["status"],
                "runID": m["currentRun"], "revision": m["editRevision"],
                "busy": m["activeJob"] is not None, "dirty": False, "notes": [],
                "lastError": m.get("lastError"), "hasResults": m["currentRun"] is not None}
    if m["currentRun"] is None:
        return response
    directory, record = _run(root, m)
    rows = copy.deepcopy(_predictions(directory))
    valid = {row["event_id"] for row in rows}
    if not set(m["edits"]) <= valid:
        fail("project_invalid", "A correction refers to a missing note.")
    response["dirty"] = m["edits"] != record["overrides"]
    summary = _json(_path(directory, "sanitized_summary.json"))
    if not isinstance(summary, dict):
        fail("project_invalid", "The analysis summary is invalid.")
    response["summary"] = summary
    response["video"] = str(_path(directory, OUTPUTS["video"]))
    response["score"] = str(_path(directory, OUTPUTS["score"]))
    parsed = _json(_path(directory, "parsed_score.json"))
    positions = {}
    raw_notes = parsed.get("notes", []) if isinstance(parsed, dict) else []
    if not isinstance(raw_notes, list) or len(raw_notes) > MAX_NOTES:
        fail("project_invalid", "The score positions are invalid.")
    for note in raw_notes:
        if not isinstance(note, dict) or type(note.get("page_index")) is not int or not 0 <= note["page_index"] < 12:
            fail("project_invalid", "The score page index is invalid.")
        if not all(_finite(note.get(k)) and -50 <= note[k] <= 1550 for k in ("x_pt", "y_pt")):
            fail("project_invalid", "The score coordinates are invalid.")
        positions[note.get("score_note_id")] = note
    for row in rows:
        override = m["edits"].get(row["event_id"])
        hand, finger, tier = row["auto_hand"], row["auto_finger"], row["auto_confidence_tier"]
        if override:
            hand, finger, tier = override["hand"], override["finger"], "manual"
        reason = REASONS.get(row.get("abstain_reason"), "The estimate uses fingertip geometry around the audio attack. It is not verified finger identity.")
        note = positions.get(row.get("score_note_id"), {})
        response["notes"].append({"id": row["event_id"], "measure": row.get("measure"),
            "time": row.get("onset_sec"), "pitch": row.get("pitch_name", ""),
            "hand": hand, "finger": finger, "tier": tier,
            "autoHand": row["auto_hand"], "autoFinger": row["auto_finger"],
            "autoTier": row["auto_confidence_tier"], "reason": reason,
            "corrected": override is not None, "page": note.get("page_index"),
            "x": note.get("x_pt"), "y": note.get("y_pt")})
    return response


def set_correction(project: str, event: str, hand: str | None, finger: str | None,
                   expected_run: str, expected_revision: int) -> dict[str, Any]:
    root, _ = open_project(project)
    with _lock(root):
        _, m = open_project(root)
        _idle(m)
        if m["currentRun"] != expected_run or m["editRevision"] != expected_revision:
            fail("stale_project", "The project changed in another window. Reopen it before editing.")
        directory, _ = _run(root, m)
        if event not in {row["event_id"] for row in _predictions(directory)}:
            fail("project_invalid", "This note no longer belongs to the current result.")
        if hand is None and finger is None:
            m["edits"].pop(event, None)
        else:
            m["edits"][event] = {"hand": hand, "finger": finger}
            _overrides(m["edits"])
        m["editRevision"] += 1
        _atomic(root / "project.json", m)
    return review_project(root)


def _fence(manifest: dict[str, Any], expected_run: str | None, expected_revision: int) -> None:
    if type(expected_revision) is not int or manifest["currentRun"] != expected_run or manifest["editRevision"] != expected_revision:
        fail("stale_project", "The project changed in another window. Reopen it before continuing.")


def _validate_cache(directory: Path) -> None:
    """Bound imported caches before any legacy pipeline loader consumes them."""
    from .cli import (_load_cached_perf_notes, _load_cached_score, _load_cached_poses,
                      _load_cached_calibrations, _load_cached_alignment, CACHED_STAGE_FILES)
    def require(condition):
        if not condition:
            fail("cache_incompatible", "The saved analysis cache is invalid. Analyze again; previous results and pending edits remain available.")
    def bounded(value, depth=0):
        require(depth <= 16)
        if isinstance(value, dict):
            require(len(value) <= 10000 and all(isinstance(k, str) and len(k) <= 128 for k in value))
            for v in value.values(): bounded(v, depth + 1)
        elif isinstance(value, list):
            require(len(value) <= 10000)
            for v in value: bounded(v, depth + 1)
        elif isinstance(value, str): require(len(value) <= 4096)
        elif type(value) in (float, int): require(_finite(value) and abs(value) <= 1e12)
        else: require(value is None or type(value) is bool)
    raw = {}
    for name in (*CACHED_STAGE_FILES, "cache_manifest.json"):
        raw[name] = _json(_path(directory, name)); bounded(raw[name]); require(isinstance(raw[name], dict))
    def records(name, key, maximum):
        values = raw[name].get(key)
        require(isinstance(values, list) and len(values) <= maximum and all(isinstance(v, dict) for v in values))
    records("transcribed_notes.json", "notes", MAX_NOTES)
    records("parsed_score.json", "notes", MAX_NOTES); records("parsed_score.json", "measures", MAX_NOTES)
    records("hand_poses.json", "frames", MAX_FRAMES); records("keyboard_calibration.json", "frames", MAX_FRAMES)
    records("alignment.json", "pairs", 2 * MAX_NOTES); records("alignment.json", "measure_timings", MAX_NOTES)
    try:
        perf, _ = _load_cached_perf_notes(directory / "transcribed_notes.json")
        measures, score, _ = _load_cached_score(directory / "parsed_score.json")
        poses, _ = _load_cached_poses(directory / "hand_poses.json")
        calibrations, _ = _load_cached_calibrations(directory / "keyboard_calibration.json")
        pairs, timings, _ = _load_cached_alignment(directory / "alignment.json", perf, score)
        def number(v, low, high): return _finite(v) and low <= v <= high
        def pitch(v): return type(v) is int and 21 <= v <= 108
        require(all(pitch(n.midi_pitch) and number(n.onset_sec, -60, 60) and number(n.offset_sec, n.onset_sec, 65) for n in perf))
        require(len({n.perf_event_id for n in perf}) == len(perf) and len({n.score_note_id for n in score}) == len(score))
        require(all(pitch(n.midi_pitch) and type(n.page_index) is int and 0 <= n.page_index < 12 and number(n.x_pt, -50, 1550) and number(n.y_pt, -50, 1550) and len(n.bbox_pt) == 4 and all(number(x, -50, 1550) for x in n.bbox_pt) for n in score))
        require(all(type(m.page_index) is int and 0 <= m.page_index < 12 and all(number(getattr(m, k), -50, 1550) for k in ("x0_pt", "x1_pt", "y0_pt", "y1_pt")) for m in measures))
        require(len(poses) == len(calibrations) and len(poses) > 0)
        previous = -61.0
        for frame, calibration in zip(poses, calibrations):
            require(frame.frame_index == calibration.frame_index and 0 <= frame.frame_index < MAX_FRAMES and number(frame.pts_sec, previous, 60) and number(calibration.pts_sec, frame.pts_sec, frame.pts_sec))
            previous = frame.pts_sec
            require(0 < frame.width <= 1920 and 0 < frame.height <= 1080 and len(frame.hands) <= 2)
            for hand in frame.hands:
                require(len(hand.landmarks) <= 21 and number(hand.hand_confidence, 0, 1))
                require(all(v is None or (len(v) == 3 and number(v[0], -3840, 3840) and number(v[1], -2160, 2160) and number(v[2], 0, 1)) for v in hand.landmarks.values()))
            for matrix in (calibration.h_white, calibration.h_black):
                require(matrix is None or (len(matrix) == 3 and all(len(row) == 3 and all(number(x, -1e12, 1e12) for x in row) for row in matrix)))
            require(type(calibration.reliable) is bool and number(calibration.residual_kw, 0, 1e12))
            require(not calibration.reliable or (calibration.h_white is not None and calibration.h_black is not None))
        require(all(number(t.t_start_sec, -60, 60) and number(t.t_end_sec, t.t_start_sec, 65) and type(t.page_index) is int and 0 <= t.page_index < 12 for t in timings))
        require(all(p.alignment_status in ("matched", "unmatched_score", "unmatched_perf") and
                    (p.perf_note is not None or p.score_note is not None) and
                    (p.alignment_status != "matched" or (p.perf_note is not None and p.score_note is not None)) and
                    (p.expected_time_sec is None or number(p.expected_time_sec, -60, 65)) and
                    (p.timing_residual_sec is None or number(p.timing_residual_sec, -65, 65)) for p in pairs))
    except DesktopError: raise
    except Exception as error:
        raise DesktopError("cache_incompatible", "The saved analysis cache is invalid. Analyze again; previous results were kept.") from error


def _check_revision(root: Path, expected: dict[str, Any]) -> dict[str, Any]:
    _, now = open_project(root)
    if any(now[k] != expected[k] for k in ("currentRun", "editRevision", "edits", "activeJob")):
        fail("stale_project", "The project changed while processing; previous results were preserved.")
    return now


def process_project(project: str, job_id: str, render_only: bool, helper: Path | None,
                    expected_run: str | None, expected_revision: int, progress=lambda _stage, _label: None) -> dict[str, Any]:
    from .cli import CACHED_STAGE_FILES, run_pipeline
    root, _ = open_project(project)
    if not _uuid(job_id):
        fail("project_invalid", "The job identity is invalid.")
    with _lock(root):
        _, m = open_project(root)
        _idle(m)
        _fence(m, expected_run, expected_revision)
        video, score = _inputs(root, m)
        inspect_inputs(video, score)
        if shutil.disk_usage(root).free < 512 * 1024 * 1024:
            fail("disk_space", "Free at least 512 MB before analysis or updating the video.")
        snapshot = copy.deepcopy(m["edits"]) if render_only else {}
        previous = _run(root, m)[0] if render_only else None
        run_id = str(uuid.uuid4())
        run = _path(root, "Runs/" + run_id)
        run.mkdir(mode=0o700)
        m["activeJob"] = {"id": job_id, "operation": "render" if render_only else "analyze"}
        m["status"], m["lastError"] = "working", None
        _atomic(root / "project.json", m)
        expected = copy.deepcopy(m)
        try:
            _atomic(run / "inputs.json", {"video": str(video), "score": str(score)})
            _atomic(run / "overrides.json", {"finger_overrides": snapshot})
            if previous:
                _validate_cache(previous)
                _predictions(previous)
                for name in (*CACHED_STAGE_FILES, "cache_manifest.json", "automatic_predictions.json"):
                    source = _path(previous, name)
                    if not source.is_file():
                        fail("cache_incompatible", "The saved analysis cache is incomplete. Analyze again; old results and edits remain available.")
                    _copy_file(source, run / name, MAX_JSON)
                _validate_cache(run)
            summary = run_pipeline(run / "inputs.json", run, run / "cache", run / "overrides.json",
                                   reuse_cached=render_only, hand_pose_helper=helper, progress=progress)
            if not previous:
                shutil.copyfile(run / "predictions.json", run / "automatic_predictions.json")
            if not all((run / name).is_file() and (run / name).stat().st_size > 0 for name in OUTPUTS.values()):
                fail("analysis_failed", "The analysis did not produce all required outputs.")
            _predictions(run)
            _check_revision(root, expected)
            _atomic(run / "run.json", {"schema": SCHEMA, "status": "complete", "overrides": snapshot,
                                      "revision": expected["editRevision"], "created": time.time(),
                                      "outputs": {name: _digest(run / name) for name in OUTPUTS.values()}})
            m["currentRun"], m["edits"], m["status"] = run_id, snapshot, "ready"
            if not render_only:
                m["editRevision"] += 1
            _atomic(root / "project.json", m)
            return {"project": str(root), "summary": summary, "runID": run_id}
        except BaseException:
            # Lease intentionally remains until native ownership confirms group cleanup.
            _, latest = open_project(root)
            if latest["activeJob"] == expected["activeJob"]:
                latest["status"] = "failed"
                latest["lastError"] = "This attempt did not finish. Previous results and pending corrections were kept."
                _atomic(root / "project.json", latest)
            raise


def finalize_job(project: str, job_id: str, outcome: str) -> dict[str, Any]:
    """Called only by the native owner after it has established group cleanup."""
    root, _ = open_project(project)
    with _lock(root):
        _, m = open_project(root)
        job = m["activeJob"]
        if job is not None:
            if job["id"] != job_id:
                fail("stale_project", "A different job now owns this project.")
            m["activeJob"] = None
            m["status"] = "ready" if m["currentRun"] else ("stopped" if outcome == "cancelled" else "failed")
            if outcome == "cancelled":
                m["lastError"] = "Analysis stopped. Your project, pending edits and previous results were kept."
            _atomic(root / "project.json", m)
    return review_project(root)


def export_project(project: str, destination: str, name: str, kinds: list[str], job_id: str,
                   expected_run: str | None, expected_revision: int) -> dict[str, Any]:
    root, _ = open_project(project)
    parent = Path(destination).resolve(strict=True)
    if not parent.is_dir() or not kinds or len(set(kinds)) != len(kinds) or not set(kinds) <= set(OUTPUTS):
        fail("destination_invalid", "Choose a folder and at least one output.")
    if not _uuid(job_id):
        fail("project_invalid", "The export identity is invalid.")
    with _lock(root):
        _, m = open_project(root)
        _idle(m)
        _fence(m, expected_run, expected_revision)
        directory, run = _run(root, m)
        if m["edits"] != run["overrides"]:
            fail("render_needed", "Update the video and score to include your pending corrections before exporting.")
        target = parent / _name(name)
        if target.exists() or target.is_symlink():
            fail("destination_exists", "That name already exists. Choose a new export folder name.")
        m["activeJob"] = {"id": job_id, "operation": "export"}
        _atomic(root / "project.json", m)
        staging = Path(tempfile.mkdtemp(prefix=".fingering-export-", dir=parent))
        try:
            for kind in kinds:
                _copy_file(_path(directory, OUTPUTS[kind]), staging / OUTPUTS[kind], 1024 * 1024 * 1024)
            _exclusive_rename(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return {"exported": str(target), "files": [OUTPUTS[kind] for kind in kinds]}


def recover_project(project: str, destination: str, name: str) -> Path:
    root, _ = open_project(project)
    with _lock(root):
        _, m = open_project(root)
        video, score = _inputs(root, m)
        parent = Path(destination).resolve(strict=True)
        target = parent / (_name(name) + ".fingeringproject")
        staging = Path(tempfile.mkdtemp(prefix=".fingering-recovery-", dir=parent))
        try:
            (staging / "Inputs").mkdir()
            (staging / "Runs").mkdir()
            _copy_file(video, staging / "Inputs" / ("video" + m["videoExtension"]), MAX_VIDEO_BYTES)
            _copy_file(Path(score), staging / "Inputs/score.pdf", MAX_PDF_BYTES)
            if m["currentRun"]:
                previous, _ = _run(root, m)
                _predictions(previous)
                from .cli import CACHED_STAGE_FILES
                recovered_run = staging / "Runs" / m["currentRun"]
                recovered_run.mkdir()
                allowed = (*OUTPUTS.values(), *CACHED_STAGE_FILES, "run.json", "cache_manifest.json",
                           "automatic_predictions.json", "predictions.json", "sanitized_summary.json", "overrides.json")
                total_bytes = 0
                for component in allowed:
                    source = _path(previous, component)
                    if not source.is_file():
                        fail("project_invalid", "A saved recovery component is missing.")
                    limit = 1024 * 1024 * 1024 if component in OUTPUTS.values() else MAX_JSON
                    total_bytes += source.stat().st_size
                    if source.stat().st_size > limit or total_bytes > 2 * 1024 * 1024 * 1024:
                        fail("project_invalid", "The saved result exceeds recovery limits.")
                    _copy_file(source, recovered_run / component, limit)
            m["id"], m["name"], m["activeJob"] = str(uuid.uuid4()), _name(name), None
            m["status"] = "ready" if m["currentRun"] else "awaiting"
            m["lastError"] = "Recovery copy created. The original project was left in place."
            _atomic(staging / "project.json", m)
            _exclusive_rename(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return target


def health() -> dict[str, Any]:
    import av
    import cv2
    import torch
    from importlib.resources import files
    from . import __version__
    model = files("transkun").joinpath("pretrained/2.0.pt")
    helper = os.environ.get("PIANO_HAND_POSE_HELPER")
    if not model.is_file() or (helper is not None and not Path(helper).is_file()):
        fail("runtime_missing", "The analysis components are incomplete. Reinstall the complete app.")
    return {"ready": True, "version": __version__, "python": platform.python_version(),
            "architecture": platform.machine(), "packageOrigin": str(Path(__file__).resolve()),
            "weightsPresent": True, "helperPresent": helper is not None,
            "limits": "Apple Silicon · macOS 14+ · up to 30 seconds / 1080p / 1,000 frames · supported score editions only"}


def emit(kind: str, **values: Any) -> None:
    line = json.dumps({"protocol": 1, "type": kind, **values}, allow_nan=False)
    if len(line.encode()) > 4 * 1024 * 1024:
        fail("project_invalid", "The review response exceeds this version's limit.")
    sys.__stdout__.write(line + "\n")
    sys.__stdout__.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["health", "inspect", "create", "open", "analyze", "render", "correct", "finalize", "export", "recover"])
    for arg in ("project", "video", "score", "destination", "name", "job-id", "event", "hand", "finger", "expected-run", "outcome"):
        parser.add_argument("--" + arg)
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--kinds", nargs='+')
    args = parser.parse_args(argv)
    try:
        # Imported model/package diagnostics must not corrupt the stdout protocol.
        with redirect_stdout(sys.stderr):
            op = args.operation
            if op == "health":
                result = health()
            elif op == "inspect":
                result = inspect_inputs(args.video, args.score)
            elif op == "create":
                result = review_project(create_project(args.video, args.score, args.destination, args.name))
            elif op == "open":
                result = review_project(args.project)
            elif op in ("analyze", "render"):
                helper = os.environ.get("PIANO_HAND_POSE_HELPER")
                result = process_project(args.project, args.job_id, op == "render", Path(helper) if helper else None,
                                         None if args.expected_run == "none" else args.expected_run, args.expected_revision,
                                         lambda stage, label: emit("progress", stage=stage, label=label))
            elif op == "correct":
                result = set_correction(args.project, args.event, args.hand, args.finger, args.expected_run, args.expected_revision)
            elif op == "finalize":
                result = finalize_job(args.project, args.job_id, args.outcome)
            elif op == "export":
                result = export_project(args.project, args.destination, args.name, args.kinds, args.job_id,
                                        None if args.expected_run == "none" else args.expected_run, args.expected_revision)
            else:
                result = review_project(recover_project(args.project, args.destination, args.name))
        emit("result", data=result)
        return 0
    except DesktopError as error:
        emit("error", code=error.code, message=error.message)
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        message = str(error).lower()
        if any(t in message for t in ("reference", "red felt", "black keys", "octave anchor", "keyboard calibration")):
            emit("error", code="keyboard_not_found", message="The keyboard could not be located reliably. Include a hand-free moment showing the bass end, filmed from behind the music desk.")
        elif "cached stages" in message:
            emit("error", code="cache_incompatible", message="This analysis cache is incompatible with the app. Analyze again; previous results and pending edits remain available.")
        else:
            emit("error", code="operation_failed", message="This operation could not finish. Your originals and previous result were preserved. Details are in the private job log.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
