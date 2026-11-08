"""Offline text-to-speech with Kokoro.

The engine is loaded lazily because importing Kokoro (and PyTorch) and loading
the model takes several seconds. All synthesis goes through a lock so the
playback and export threads can share a single model instance.
"""

from __future__ import annotations

import logging
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


class TtsError(Exception):
    """Raised when the TTS engine cannot be loaded or fails to synthesize."""


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


class FairLock:
    """A first-come, first-served lock.

    ``threading.Lock`` lets a thread that releases and immediately re-acquires
    win again, so a long export would starve live playback. Tickets make
    waiters take turns.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._next_ticket = 0
        self._serving = 0

    def __enter__(self) -> "FairLock":
        with self._cond:
            ticket = self._next_ticket
            self._next_ticket += 1
            self._cond.wait_for(lambda: self._serving == ticket)
        return self

    def __exit__(self, *exc_info: object) -> None:
        with self._cond:
            self._serving += 1
            self._cond.notify_all()


class KokoroEngine:
    """Thin, thread-safe wrapper around a Kokoro ``KPipeline``."""

    def __init__(self, voice: str = DEFAULT_VOICE, lang_code: str = DEFAULT_LANG_CODE) -> None:
        self.voice = voice
        self.lang_code = lang_code
        self._pipeline = None
        self._lock = FairLock()

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
