"""Tests for export page-range logic and the export pipeline (with a fake TTS engine)."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from vocalpages.export import (
    SECTION_GAP_SECONDS,
    ExportCancelled,
    ExportError,
    export_sections,
    find_ffmpeg,
    output_format,
    resolve_section_range,
)
from vocalpages.document import Section
from vocalpages.tts import SAMPLE_RATE


class FakeEngine:
    """Returns 0.1 s of quiet tone per segment, so tests need no TTS model."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str, speed: float = 1.0) -> np.ndarray:
        self.calls.append(text)
        t = np.arange(int(0.1 * SAMPLE_RATE)) / SAMPLE_RATE
        return (0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


PAGES = [
    Section.from_text(1, "Page 1", "Page one. Has two sentences."),
    Section.from_text(2, "Page 2", "Page two."),
    Section.from_text(3, "Page 3", ""),  # scanned / no text
    Section.from_text(4, "Page 4", "Page four."),
]


# ----- resolve_section_range ---------------------------------------------------


def test_whole_document_by_default() -> None:
    assert resolve_section_range(None, None, 4) == [1, 2, 3, 4]


def test_explicit_range_is_inclusive() -> None:
    assert resolve_section_range(1, 3, 10) == [1, 2, 3]


def test_single_page_range() -> None:
    assert resolve_section_range(5, 5, 10) == [5]


def test_open_ended_ranges() -> None:
    assert resolve_section_range(8, None, 10) == [8, 9, 10]
    assert resolve_section_range(None, 2, 10) == [1, 2]


@pytest.mark.parametrize("start,end", [(0, 3), (1, 11), (4, 2), (-1, 2), (11, None)])
def test_invalid_ranges_raise(start: int | None, end: int | None) -> None:
    with pytest.raises(ValueError):
        resolve_section_range(start, end, 10)


def test_empty_document_raises() -> None:
    with pytest.raises(ValueError):
        resolve_section_range(None, None, 0)


# ----- output_format --------------------------------------------------------


@pytest.mark.parametrize("name,fmt", [("a.mp3", "mp3"), ("b.WAV", "wav"), ("dir.x/c.Mp3", "mp3")])
def test_output_format(name: str, fmt: str) -> None:
    assert output_format(name) == fmt


@pytest.mark.parametrize("name", ["a.ogg", "noext", "a.mp3.txt"])
def test_output_format_rejects_unknown(name: str) -> None:
    with pytest.raises(ValueError):
        output_format(name)


# ----- export_pages ---------------------------------------------------------


def test_export_wav_range_skips_empty_pages(tmp_path: Path) -> None:
    engine = FakeEngine()
    progress: list[tuple[int, int]] = []
    out = tmp_path / "out.wav"

    result = export_sections(
        PAGES, [2, 3, 4], out, engine, progress=lambda d, t: progress.append((d, t))
    )

    assert engine.calls == ["Page two.", "Page four."]
    assert result.exported_sections == [2, 4]
    assert result.skipped_sections == [3]
    assert progress == [(1, 2), (2, 2)]
    with wave.open(str(out)) as wav:
        assert wav.getframerate() == SAMPLE_RATE
        assert wav.getnchannels() == 1
        expected = 2 * int(0.1 * SAMPLE_RATE) + int(SECTION_GAP_SECONDS * SAMPLE_RATE)
        assert wav.getnframes() == expected
    assert result.duration_seconds == pytest.approx(expected / SAMPLE_RATE)


def test_export_cancel_removes_partial_file(tmp_path: Path) -> None:
    out = tmp_path / "out.wav"
    engine = FakeEngine()
    with pytest.raises(ExportCancelled):
        export_sections(PAGES, [1, 2], out, engine, is_cancelled=lambda: len(engine.calls) >= 1)
    assert not out.exists()


def test_export_only_empty_pages_raises(tmp_path: Path) -> None:
    with pytest.raises(ExportError):
        export_sections(PAGES, [3], tmp_path / "out.wav", FakeEngine())


def test_find_ffmpeg_without_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    found = find_ffmpeg()
    assert found is None or Path(found).name == "ffmpeg"


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_export_mp3(tmp_path: Path) -> None:
    out = tmp_path / "out.mp3"
    result = export_sections(PAGES, [1, 2], out, FakeEngine())
    assert out.stat().st_size > 0
    assert result.duration_seconds > 0
