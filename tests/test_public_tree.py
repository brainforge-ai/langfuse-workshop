"""The public repo must not carry presenter-only material, in files or in history."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_PATHS = ("presenter/", "docs/plans/", "requirements.md")
# Assembled from pieces so this file does not match its own scan.
MARKERS = tuple(
    "".join(parts)
    for parts in (
        ("ans", "wer key"),
        ("ans", "wer-key"),
        ("plan", "ted"),
        ("bug ", "catalog"),
        ("spoi", "ler"),
        ("root ", "cause:"),
        ("reserve ", "bug"),
    )
)
# Pull requests from attendees may mention what they found; the scan guards main only.
ON_PULL_REQUEST = pytest.mark.skipif(
    bool(os.environ.get("GITHUB_BASE_REF")), reason="pull request checks guard main only"
)
CATALOG_ID = re.compile(r"\b(" + "B" + r"[1-4]|" + "H" + r"[1-3]|" + "E" + r"E)\b")


def _git(*args):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        pytest.skip("not a git checkout with commits")
    return result.stdout


def test_no_private_path_is_tracked():
    tracked = _git("ls-files").splitlines()
    leaked = [p for p in tracked if p.startswith(PRIVATE_PATHS) or p == ".env"]
    assert leaked == []


@ON_PULL_REQUEST
def test_no_tracked_text_file_carries_a_marker():
    this_file = Path(__file__).resolve().relative_to(ROOT).as_posix()
    hits = []
    for name in _git("ls-files").splitlines():
        if name == this_file:
            continue
        try:
            text = (ROOT / name).read_text(encoding="utf-8").lower()
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        hits += [f"{name}: {m}" for m in MARKERS if m in text]
    assert hits == []


@ON_PULL_REQUEST
def test_no_commit_message_carries_a_marker_or_catalog_id():
    log = _git("log", "--format=%H%n%B%n----")
    hits = []
    for entry in log.split("----"):
        lines = entry.strip().splitlines()
        if not lines:
            continue
        sha, message = lines[0], "\n".join(lines[1:])
        lower = message.lower()
        hits += [f"{sha[:8]}: {m}" for m in MARKERS if m in lower]
        hits += [f"{sha[:8]}: {m}" for m in CATALOG_ID.findall(message)]
    assert hits == []
