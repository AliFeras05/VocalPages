"""Export PDF pages to a single MP3 or WAV file.

Audio is streamed into a WAV file segment by segment, so memory use stays flat
while synthesizing. For MP3 output that WAV is a temporary file that pydub
(via ffmpeg) converts at the end.
"""

from __future__ import annotations

import shutil
import tempfile
import warnings
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence

import numpy as np

from readaloud.pdf_extract import Page
from readaloud.tts import SAMPLE_RATE, split_into_segments, to_pcm16

SUPPORTED_FORMATS = ("mp3", "wav")
MP3_BITRATE = "96k"
PAGE_GAP_SECONDS = 0.8
# Apps launched from the macOS Finder don't inherit the shell PATH, so also
# look where Homebrew and common installers put ffmpeg.
FFMPEG_FALLBACK_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")

ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


class ExportError(Exception):
    """Raised when an export cannot be started or fails."""


class ExportCancelled(Exception):
    """Raised when the user cancels an export. No output file is left behind."""


class Synthesizer(Protocol):
    """Anything that turns text into mono float32 audio at ``SAMPLE_RATE``."""

    def synthesize(self, text: str, speed: float = 1.0) -> np.ndarray: ...


@dataclass
class ExportResult:
    """Summary of a finished export."""

    path: Path
    duration_seconds: float
    exported_pages: list[int] = field(default_factory=list)
    skipped_pages: list[int] = field(default_factory=list)


def find_ffmpeg() -> str | None:
    """Return the path of an ffmpeg executable, or None if none is installed."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for directory in FFMPEG_FALLBACK_DIRS:
        found = shutil.which("ffmpeg", path=directory)
        if found:
            return found
    return None


def resolve_page_range(start: int | None, end: int | None, page_count: int) -> list[int]:
    """Return the 1-based page numbers from ``start`` to ``end`` inclusive.

    ``None`` means the first or last page. Raises ``ValueError`` for an empty
    document or a range outside ``1..page_count`` or with ``start > end``.
    """
    if page_count < 1:
        raise ValueError("The document has no pages.")
    first = 1 if start is None else start
    last = page_count if end is None else end
    if not (1 <= first <= page_count and 1 <= last <= page_count):
        raise ValueError(f"Pages must be between 1 and {page_count}.")
    if first > last:
        raise ValueError("The first page must not be after the last page.")
    return list(range(first, last + 1))


def output_format(path: str | Path) -> str:
    """Return ``"mp3"`` or ``"wav"`` from the file extension, or raise ``ValueError``."""
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix not in SUPPORTED_FORMATS:
        raise ValueError("Choose a file name ending in .mp3 or .wav.")
    return suffix


def export_pages(
    pages: Sequence[Page],
    page_numbers: Sequence[int],
    out_path: str | Path,
    engine: Synthesizer,
    speed: float = 1.0,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCheck | None = None,
) -> ExportResult:
    """Synthesize the given pages into one audio file at ``out_path``.

    Pages without text are skipped and reported in the result. ``progress`` is
    called with (segments done, total segments). If ``is_cancelled`` returns
    True the export stops, partial output is removed and ``ExportCancelled``
    is raised.
    """
    out_path = Path(out_path)
    fmt = output_format(out_path)
    ffmpeg = find_ffmpeg() if fmt == "mp3" else None
    if fmt == "mp3" and ffmpeg is None:
        raise ExportError("MP3 export needs ffmpeg. Install it, or export to WAV instead.")

    selected = [pages[n - 1] for n in page_numbers]
    readable = [p for p in selected if p.has_text]
    if not readable:
        raise ExportError("None of the selected pages contain extractable text.")
    plan = [(page, split_into_segments(page.text)) for page in readable]
    total = sum(len(segments) for _, segments in plan)

    with tempfile.TemporaryDirectory(prefix="readaloud-") as tmp:
        wav_path = out_path if fmt == "wav" else Path(tmp) / "export.wav"
        try:
            frames = _write_wav(plan, wav_path, engine, speed, total, progress, is_cancelled)
            if ffmpeg is not None:
                _convert_to_mp3(wav_path, out_path, ffmpeg)
        except BaseException:
            out_path.unlink(missing_ok=True)
            raise

    return ExportResult(
        path=out_path,
        duration_seconds=frames / SAMPLE_RATE,
        exported_pages=[p.number for p in readable],
        skipped_pages=[p.number for p in selected if not p.has_text],
    )


def _write_wav(
    plan: list[tuple[Page, list[str]]],
    wav_path: Path,
    engine: Synthesizer,
    speed: float,
    total: int,
    progress: ProgressCallback | None,
    is_cancelled: CancelCheck | None,
) -> int:
    """Stream synthesized audio into a 16-bit mono WAV file; return the frame count."""
    gap = b"\x00\x00" * int(PAGE_GAP_SECONDS * SAMPLE_RATE)
    done = 0
    frames = 0
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        for page_index, (_page, segments) in enumerate(plan):
            if page_index:
                wav.writeframes(gap)
                frames += len(gap) // 2
            for segment in segments:
                if is_cancelled and is_cancelled():
                    raise ExportCancelled()
                pcm = to_pcm16(engine.synthesize(segment, speed))
                wav.writeframes(pcm)
                frames += len(pcm) // 2
                done += 1
                if progress:
                    progress(done, total)
    return frames


def _convert_to_mp3(wav_path: Path, mp3_path: Path, ffmpeg: str) -> None:
    with warnings.catch_warnings():
        # pydub 0.25 emits Syntax/Deprecation warnings (with install paths) on import.
        warnings.simplefilter("ignore")
        from pydub import AudioSegment

    AudioSegment.converter = ffmpeg

    try:
        AudioSegment.from_wav(wav_path).export(mp3_path, format="mp3", bitrate=MP3_BITRATE)
    except Exception as exc:
        raise ExportError(f"MP3 encoding failed: {exc}") from exc
