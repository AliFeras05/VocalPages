"""Offline text-to-speech with Kokoro.

The engine is loaded lazily because importing Kokoro (and PyTorch) and loading
the model takes several seconds. All synthesis goes through a lock so the
playback and export threads can share a single model instance.
"""

from __future__ import annotations

import logging
import re
import threading
import warnings
from contextlib import contextmanager
from typing import Iterator

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 24_000
DEFAULT_VOICE = "af_heart"
DEFAULT_LANG_CODE = "a"  # American English
KOKORO_REPO_ID = "hexgrad/Kokoro-82M"
MIN_SPEED = 0.5
MAX_SPEED = 2.0
MAX_SEGMENT_CHARS = 400

_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "st", "vs", "etc", "e.g", "i.e", "fig", "no"}
_SENTENCE_END_RE = re.compile(r"(?:(?<=[.!?…])|(?<=[.!?…][\"'”’)\]]))\s+")


class TtsError(Exception):
    """Raised when the TTS engine cannot be loaded or fails to synthesize."""


def _ends_with_abbreviation(sentence: str) -> bool:
    words = sentence.rstrip().split()
    return bool(words) and words[-1].rstrip(".").lower() in _ABBREVIATIONS


def _split_long(sentence: str, max_chars: int) -> list[str]:
    """Split an over-long sentence at word boundaries, preferring commas and semicolons."""
    parts: list[str] = []
    rest = sentence
    while len(rest) > max_chars:
        window = rest[:max_chars]
        cut = max(window.rfind(", "), window.rfind("; "))
        cut = cut + 1 if cut > max_chars // 3 else window.rfind(" ")
        if cut <= 0:
            cut = max_chars
        parts.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        parts.append(rest)
    return parts


def split_into_segments(text: str, max_chars: int = MAX_SEGMENT_CHARS) -> list[str]:
    """Split page text into sentence-sized segments for synthesis and highlighting.

    Paragraph breaks always end a segment. Common abbreviations such as "Dr." do
    not, and sentences longer than ``max_chars`` are broken at word boundaries.
    """
    segments: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        pending = ""
        for piece in _SENTENCE_END_RE.split(paragraph):
            pending = f"{pending} {piece}".strip() if pending else piece.strip()
            if pending and not _ends_with_abbreviation(pending):
                segments.extend(_split_long(pending, max_chars))
                pending = ""
        if pending:
            segments.extend(_split_long(pending, max_chars))
    return segments


def normalize_page_text(text: str) -> str:
    """Collapse whitespace inside paragraphs, keeping blank lines between them.

    This is the text shown to the user; every segment from
    ``split_into_segments`` appears in it verbatim, in order.
    """
    paragraphs = (" ".join(p.split()) for p in re.split(r"\n\s*\n", text))
    return "\n\n".join(p for p in paragraphs if p)


def locate_segments(display_text: str, segments: list[str]) -> list[tuple[int, int]]:
    """Return the (start, end) character span of each segment within ``display_text``.

    Segments are searched in order; a segment that cannot be found gets an
    empty span at the current position.
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    for segment in segments:
        start = display_text.find(segment, pos)
        if start < 0:
            spans.append((pos, pos))
            continue
        end = start + len(segment)
        spans.append((start, end))
        pos = end
    return spans


def clamp_speed(speed: float) -> float:
    """Clamp a speaking speed to the range Kokoro handles well."""
    return max(MIN_SPEED, min(MAX_SPEED, speed))


def to_pcm16(audio: np.ndarray) -> bytes:
    """Convert float audio in [-1, 1] to little-endian 16-bit PCM bytes."""
    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767).astype("<i2").tobytes()


@contextmanager
def _quiet_third_party() -> Iterator[None]:
    """Silence PyTorch/Kokoro warning chatter, which also prints install paths."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        warnings.filterwarnings("ignore", category=FutureWarning)
        yield


class KokoroEngine:
    """Thin, thread-safe wrapper around a Kokoro ``KPipeline``."""

    def __init__(self, voice: str = DEFAULT_VOICE, lang_code: str = DEFAULT_LANG_CODE) -> None:
        self.voice = voice
        self.lang_code = lang_code
        self._pipeline = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        """True once the model has been loaded."""
        return self._pipeline is not None

    def load(self) -> None:
        """Load the Kokoro model (downloads it on first use). Safe to call repeatedly."""
        with self._lock:
            if self._pipeline is not None:
                return
            try:
                with _quiet_third_party():
                    from kokoro import KPipeline

                    self._pipeline = KPipeline(lang_code=self.lang_code, repo_id=KOKORO_REPO_ID)
            except ImportError as exc:
                raise TtsError("Kokoro is not installed. Run: pip install kokoro") from exc
            except Exception as exc:
                raise TtsError(f"Could not load the Kokoro model: {exc}") from exc
            log.info("Kokoro model loaded")

    def synthesize(self, text: str, speed: float = 1.0) -> np.ndarray:
        """Return mono float32 audio at ``SAMPLE_RATE`` for ``text``.

        Empty text returns an empty array.
        """
        if not text.strip():
            return np.zeros(0, dtype=np.float32)
        self.load()
        with self._lock, _quiet_third_party():
            try:
                chunks = [
                    np.asarray(audio, dtype=np.float32)
                    for _graphemes, _phonemes, audio in self._pipeline(
                        text, voice=self.voice, speed=clamp_speed(speed)
                    )
                    if audio is not None
                ]
            except Exception as exc:
                raise TtsError(f"Speech synthesis failed: {exc}") from exc
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)
