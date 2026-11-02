"""Two-tier zero-secret privacy guard test scanning tracked and staged files."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

import pdfplumber
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".pdf",
    ".wav",
    ".mp3",
    ".m4a",
    ".mid",
    ".midi",
    ".mxl",
    ".musicxml",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".csv",
    ".tsv",
    ".jsonl",
    ".pt",
    ".pth",
    ".safetensors",
    ".task",
}

STATIC_FORBIDDEN_REGEXES = [
    re.compile(r"/Users/[A-Za-z0-9._-]+"),
    re.compile(r"/home/[A-Za-z0-9._-]+"),
    re.compile(r"Authorized for use by", re.IGNORECASE),
    re.compile(r"Musicnotes", re.IGNORECASE),
    re.compile(r"\bVID_20\d{6}"),
    re.compile(r"\bMN0\d{5,}\b"),
]

GENERIC_SCORE_PHRASES = {
    "for piano",
    "all rights reserved",
    "published under license from",
    "with pedal",
}


def _repository_blobs(repo_root: Path = REPO_ROOT) -> list[tuple[str, Path, bytes]]:
    """Read both index blobs (what will be committed) and unignored working files."""
    out = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repo_root,
    )
    blobs = []
    for name in set(out.decode().split("\0")) - {""}:
        p = repo_root / name
        if p.is_file():
            blobs.append((f"working:{name}", p, p.read_bytes()))
    index = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=repo_root)
    for entry in index.decode().split("\0"):
        if not entry:
            continue
        header, name = entry.split("\t", 1)
        mode, oid, stage = header.split()
        if mode == "160000":
            continue
        content = subprocess.check_output(["git", "cat-file", "blob", oid], cwd=repo_root)
        blobs.append((f"index:{stage}:{name}", repo_root / name, content))
    return blobs


def _extract_dynamic_private_phrases(inputs_file: Path) -> list[str]:
    """Extract forbidden phrases dynamically in memory from untracked .local/inputs.json & PDF.

    When inputs_file exists, all referenced inputs must be readable (never silently skipped).
    """
    data = json.loads(inputs_file.read_text(encoding="utf-8"))
    phrases: set[str] = set()
    for key in (
        "video",
        "video_path",
        "score",
        "score_path",
        "private_research_proposal",
        "private_research_ledger",
    ):
        val = data.get(key)
        if isinstance(val, str) and val:
            phrases.add(val)
            stem = Path(val).stem
            if len(stem) >= 6:
                phrases.add(stem)

    score_raw = data.get("score") or data.get("score_path") or data.get("score_pdf_path")
    assert isinstance(score_raw, str) and score_raw, (
        "Present .local/inputs.json must define a valid 'score' path for dynamic privacy scanning."
    )
    score_path = Path(score_raw).expanduser()
    assert score_path.is_file(), f"Configured score PDF in .local/inputs.json is unreadable: {score_path.name}"

    with pdfplumber.open(str(score_path)) as pdf:
        assert len(pdf.pages) > 0, "Configured score PDF has zero pages."
        for page_idx, page in enumerate(pdf.pages):
            # Filter out legacy music-font notehead/symbol glyphs before text extraction
            non_music_page = page.filter(
                lambda obj: obj.get("object_type") != "char"
                or "Doremi" not in obj.get("fontname", "")
            )
            page_txt = non_music_page.extract_text() or ""
            min_len = 8 if page_idx == 0 else 10
            for raw_line in page_txt.splitlines():
                line = raw_line.strip().strip("“”\"'")
                if len(line) < min_len or line.lower() in GENERIC_SCORE_PHRASES:
                    continue
                phrases.add(line)
                for prefix in ("from:", "arranged by:", "authorized for use by"):
                    if line.lower().startswith(prefix):
                        tail = line[len(prefix) :].strip(" :“”\"'")
                        if len(tail) >= 6:
                            phrases.add(tail)

    return sorted(p for p in phrases if len(p) >= 6)


def test_no_private_files_or_static_leaks_in_git_tree() -> None:
    files = _repository_blobs()
    assert files, "Expected non-empty git file list"
    self_path = Path(__file__).resolve()

    violations: list[str] = []
    for label, path, raw_content in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith(".local/"):
            violations.append(f"Tracked/unignored file under .local/: {rel}")
            continue
        if path.suffix.lower() in FORBIDDEN_EXTENSIONS:
            violations.append(f"Forbidden media/data extension in git tree: {rel}")
            continue

        try:
            content = raw_content.decode("utf-8")
        except UnicodeDecodeError:
            continue

        if path.resolve() != self_path:
            for rx in STATIC_FORBIDDEN_REGEXES:
                if rx.search(content):
                    violations.append(f"Static privacy violation in {label}: matched {rx.pattern!r}")

    assert not violations, "Static privacy check failed:\n" + "\n".join(violations)


def test_no_dynamic_local_input_phrases_in_git_tree() -> None:
    inputs_file = REPO_ROOT / ".local" / "inputs.json"
    if not inputs_file.exists():
        pytest.skip(
            "Optional .local/inputs.json not present (clean-clone mode); dynamic phrase scan skipped."
        )

    files = _repository_blobs()
    dynamic_phrases = _extract_dynamic_private_phrases(inputs_file)
    assert dynamic_phrases, "Expected non-empty dynamic phrase set from .local/inputs.json"

    violations: list[str] = []
    for label, path, raw_content in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            content = raw_content.decode("utf-8")
        except UnicodeDecodeError:
            continue

        if rel == "LICENSE":
            # Only exempt the repository author's standard MIT copyright line, scanning the rest of LICENSE
            content = "\n".join(
                ln for ln in content.splitlines() if not ln.strip().lower().startswith("copyright (c)")
            )

        content_lower = content.lower()
        for phrase in dynamic_phrases:
            if phrase.lower() in content_lower:
                violations.append(
                    f"Dynamic local-input metadata leaked in {label} (len={len(phrase)})"
                )

    assert not violations, "Dynamic privacy check failed:\n" + "\n".join(violations)


def test_index_blob_scanned_even_when_working_file_cleaned_or_deleted(tmp_path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    secret = b"synthetic-private-phrase"
    staged = tmp_path / "note.txt"
    staged.write_bytes(secret)
    subprocess.run(["git", "add", "note.txt"], cwd=tmp_path, check=True)
    staged.write_text("sanitized")
    blobs = _repository_blobs(tmp_path)
    assert any(label.startswith("index:") and raw == secret for label, _, raw in blobs)
    assert any(label.startswith("working:") and raw == b"sanitized" for label, _, raw in blobs)
    staged.unlink()
    assert any(raw == secret for _, _, raw in _repository_blobs(tmp_path))
