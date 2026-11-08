"""Tests for the resume-position store."""

from __future__ import annotations

from pathlib import Path

from readaloud.state import ResumeStore, fingerprint


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state" / "resume.json"
    ResumeStore(path).set("abc", 7)
    assert ResumeStore(path).get("abc") == 7
    assert ResumeStore(path).get("missing") is None


def test_corrupt_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "resume.json"
    path.write_text("{not json")
    store = ResumeStore(path)
    assert store.get("abc") is None
    store.set("abc", 2)
    assert ResumeStore(path).get("abc") == 2


def test_saved_file_contains_no_paths(tmp_path: Path, sample_pdf: Path) -> None:
    path = tmp_path / "resume.json"
    ResumeStore(path).set(fingerprint(sample_pdf), 3)
    content = path.read_text()
    assert str(tmp_path) not in content
    assert "sample" not in content


def test_fingerprint_depends_on_content_not_name(tmp_path: Path) -> None:
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    assert fingerprint(a) == fingerprint(b)
    b.write_bytes(b"different")
    assert fingerprint(a) != fingerprint(b)
