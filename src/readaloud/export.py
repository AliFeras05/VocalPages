"""Export document sections (PDF pages or EPUB chapters) to a single MP3 or WAV file.

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

from readaloud.document import Section
from readaloud.tts import SAMPLE_RATE, to_pcm16

SUPPORTED_FORMATS = ("mp3", "wav")
MP3_BITRATE = "96k"
SECTION_GAP_SECONDS = 0.8
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
    exported_sections: list[int] = field(default_factory=list)
    skipped_sections: list[int] = field(default_factory=list)


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


def resolve_section_range(start: int | None, end: int | None, count: int) -> list[int]:
    """Return the 1-based section numbers from ``start`` to ``end`` inclusive.

    ``None`` means the first or last section. Raises ``ValueError`` for an empty
    document or a range outside ``1..count`` or with ``start > end``.
    """
    if count < 1:
        raise ValueError("The document has nothing to export.")
    first = 1 if start is None else start
    last = count if end is None else end
    if not (1 <= first <= count and 1 <= last <= count):
        raise ValueError(f"The range must be between 1 and {count}.")
    if first > last:
        raise ValueError("The start of the range must not be after its end.")
    return list(range(first, last + 1))


def output_format(path: str | Path) -> str:
    """Return ``"mp3"`` or ``"wav"`` from the file extension, or raise ``ValueError``."""
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix not in SUPPORTED_FORMATS:
        raise ValueError("Choose a file name ending in .mp3 or .wav.")
    return suffix


def export_sections(
    sections: Sequence[Section],
    numbers: Sequence[int],
    out_path: str | Path,
    engine: Synthesizer,
    speed: float = 1.0,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCheck | None = None,
) -> ExportResult:
    """Synthesize the sections with the given 1-based ``numbers`` into one audio file.

    Sections without text are skipped and reported in the result. ``progress`` is
    called with (segments done, total segments). If ``is_cancelled`` returns
    True the export stops, partial output is removed and ``ExportCancelled``
    is raised.
    """
    out_path = Path(out_path)
    fmt = output_format(out_path)
    ffmpeg = find_ffmpeg() if fmt == "mp3" else None
    if fmt == "mp3" and ffmpeg is None:
        raise ExportError("MP3 export needs ffmpeg. Install it, or export to WAV instead.")

    selected = [sections[n - 1] for n in numbers]
    readable = [s for s in selected if s.has_text]
    if not readable:
        raise ExportError("None of the selected sections contain readable text.")
    plan = [list(section.sentences) for section in readable]
    total = sum(len(segments) for segments in plan)

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
        exported_sections=[s.number for s in readable],
        skipped_sections=[s.number for s in selected if not s.has_text],
    )


def _write_wav(
    plan: list[list[str]],
    wav_path: Path,
    engine: Synthesizer,
    speed: float,
    total: int,
    progress: ProgressCallback | None,
    is_cancelled: CancelCheck | None,
) -> int:
    """Stream synthesized audio into a 16-bit mono WAV file; return the frame count."""
    gap = b"\x00\x00" * int(SECTION_GAP_SECONDS * SAMPLE_RATE)
    done = 0
    frames = 0
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        for section_index, segments in enumerate(plan):
            if section_index:
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
