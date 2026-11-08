"""Audio playback of PDF pages.

``Reader`` is the document-level controller the GUI talks to: it tracks the
current page, skips pages without text and moves to the next page when one
finishes. ``SegmentPlayer`` plays one page's sentence segments through
``QAudioSink`` while a background thread synthesizes the next segment, so
there is no gap and the UI never blocks on the TTS model.
"""

from __future__ import annotations

import enum
import logging

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QThread, Signal, Slot
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices, QtAudio

from readaloud.pdf_extract import Page
from readaloud.tts import SAMPLE_RATE, KokoroEngine, TtsError, clamp_speed, split_into_segments, to_pcm16

log = logging.getLogger(__name__)


class PlayerState(enum.Enum):
    """Playback state shown to the user."""

    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class _SynthWorker(QObject):
    """Runs TTS in a background thread. Requests from stale generations are skipped."""

    ready = Signal()
    synthesized = Signal(int, int, bytes)  # generation, segment index, PCM16 audio
    failed = Signal(str)

    def __init__(self, engine: KokoroEngine) -> None:
        super().__init__()
        self._engine = engine
        self.current_generation = 0  # written from the GUI thread, read here

    @Slot()
    def warm_up(self) -> None:
        """Load the model and run one tiny synthesis so the first Play is quick."""
        try:
            self._engine.load()
            self._engine.synthesize("Ready.")
        except TtsError as exc:
            self.failed.emit(str(exc))
            return
        log.info("Voice model ready")
        self.ready.emit()

    @Slot(int, int, str, float)
    def synthesize(self, generation: int, index: int, text: str, speed: float) -> None:
        """Synthesize one segment and emit its PCM audio."""
        if generation != self.current_generation:
            return
        try:
            audio = self._engine.synthesize(text, speed)
        except TtsError as exc:
            self.failed.emit(str(exc))
            return
        self.synthesized.emit(generation, index, to_pcm16(audio))


class SegmentPlayer(QObject):
    """Plays a list of text segments in order, synthesizing one segment ahead."""

    segment_started = Signal(int)
    finished = Signal()
    state_changed = Signal(PlayerState)
    engine_ready = Signal()
    error = Signal(str)

    _request = Signal(int, int, str, float)

    def __init__(self, engine: KokoroEngine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._segments: list[str] = []
        self._index = 0
        self._speed = 1.0
        self._state = PlayerState.STOPPED
        self._generation = 0
        self._cache: dict[int, bytes] = {}
        self._requested: set[int] = set()
        self._waiting = False
        self._buffer: QBuffer | None = None

        fmt = QAudioFormat()
        fmt.setSampleRate(SAMPLE_RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self._sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt, self)
        self._sink.stateChanged.connect(self._on_sink_state)

        self._thread = QThread(self)
        self._worker = _SynthWorker(engine)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.warm_up)
        self._request.connect(self._worker.synthesize)
        self._worker.synthesized.connect(self._on_synthesized)
        self._worker.ready.connect(self.engine_ready)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    @property
    def state(self) -> PlayerState:
        """Current playback state."""
        return self._state

    @property
    def speed(self) -> float:
        """Current speaking speed multiplier."""
        return self._speed

    def shutdown(self) -> None:
        """Stop playback and the worker thread. Call before the app exits."""
        self.stop()
        self._thread.quit()
        self._thread.wait()

    def play(self, segments: list[str], start_index: int = 0) -> None:
        """Start playing ``segments`` from ``start_index``."""
        self._reset()
        self._segments = list(segments)
        self._set_state(PlayerState.PLAYING)
        self._play_index(start_index)

    def pause(self) -> None:
        """Pause playback; resume() continues from the same spot."""
        if self._state is not PlayerState.PLAYING:
            return
        if self._sink.state() == QtAudio.State.ActiveState:
            self._sink.suspend()
        self._set_state(PlayerState.PAUSED)

    def resume(self) -> None:
        """Resume after pause()."""
        if self._state is not PlayerState.PAUSED:
            return
        self._set_state(PlayerState.PLAYING)
        sink_state = self._sink.state()
        if sink_state == QtAudio.State.SuspendedState:
            self._sink.resume()
        elif sink_state == QtAudio.State.IdleState:  # paused right as a segment ended
            self._advance()
        else:
            self._play_index(self._index)

    def stop(self) -> None:
        """Stop playback and drop any synthesized audio."""
        self._reset()
        self._set_state(PlayerState.STOPPED)

    def set_speed(self, speed: float) -> None:
        """Change speed. The current sentence finishes; the next one uses the new speed."""
        self._speed = clamp_speed(speed)
        self._new_generation()
        current = self._cache.get(self._index)
        self._cache = {self._index: current} if current is not None else {}
        self._requested = set(self._cache)
        if self._state is not PlayerState.STOPPED:
            self._ensure_requested(self._index)
            self._ensure_requested(self._index + 1)

    def _reset(self) -> None:
        self._new_generation()
        self._sink.stop()
        self._buffer = None
        self._cache.clear()
        self._requested.clear()
        self._waiting = False
        self._segments = []
        self._index = 0

    def _new_generation(self) -> None:
        self._generation += 1
        self._worker.current_generation = self._generation

    def _set_state(self, state: PlayerState) -> None:
        if state is not self._state:
            self._state = state
            self.state_changed.emit(state)

    def _ensure_requested(self, index: int) -> None:
        if 0 <= index < len(self._segments) and index not in self._cache and index not in self._requested:
            self._requested.add(index)
            self._request.emit(self._generation, index, self._segments[index], self._speed)

    def _play_index(self, index: int) -> None:
        self._index = index
        if index >= len(self._segments):
            self._reset()
            self.finished.emit()  # a listener may start the next page right away
            if not self._segments:
                self._set_state(PlayerState.STOPPED)
            return
        if index in self._cache:
            self._start_audio(self._cache[index])
        else:
            self._waiting = True
            self._ensure_requested(index)
        self._ensure_requested(index + 1)

    def _start_audio(self, pcm: bytes) -> None:
        self._waiting = False
        self._buffer = QBuffer(self)
        self._buffer.setData(QByteArray(pcm))
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._sink.start(self._buffer)
        self.segment_started.emit(self._index)

    @Slot(int, int, bytes)
    def _on_synthesized(self, generation: int, index: int, pcm: bytes) -> None:
        if generation != self._generation:
            return
        self._requested.discard(index)
        self._cache[index] = pcm
        if self._waiting and index == self._index and self._state is PlayerState.PLAYING:
            self._start_audio(pcm)

    @Slot(QtAudio.State)
    def _on_sink_state(self, state: QtAudio.State) -> None:
        if state != QtAudio.State.IdleState or self._state is not PlayerState.PLAYING:
            return
        if self._sink.error() not in (QtAudio.Error.NoError, QtAudio.Error.UnderrunError):
            self._on_failed(f"Audio output error: {self._sink.error().name}")
            return
        self._advance()

    def _advance(self) -> None:
        self._sink.stop()
        self._cache.pop(self._index, None)
        self._play_index(self._index + 1)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.stop()
        self.error.emit(message)


class Reader(QObject):
    """Document-level playback: current page, page skipping and auto-advance."""

    page_changed = Signal(int)  # 1-based page number
    segment_started = Signal(int, int)  # page number, segment index
    page_skipped = Signal(int)  # page number with no extractable text
    state_changed = Signal(PlayerState)
    finished = Signal()
    engine_ready = Signal()
    error = Signal(str)

    def __init__(self, engine: KokoroEngine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pages: list[Page] = []
        self._segments: dict[int, list[str]] = {}
        self._current = 1
        self._player = SegmentPlayer(engine, self)
        self._player.segment_started.connect(lambda i: self.segment_started.emit(self._current, i))
        self._player.finished.connect(self._on_page_finished)
        self._player.state_changed.connect(self.state_changed)
        self._player.engine_ready.connect(self.engine_ready)
        self._player.error.connect(self.error)

    @property
    def pages(self) -> list[Page]:
        """All pages of the open document."""
        return list(self._pages)

    @property
    def page_count(self) -> int:
        """Number of pages in the open document (0 if none)."""
        return len(self._pages)

    @property
    def current_page(self) -> int:
        """1-based number of the current page."""
        return self._current

    @property
    def state(self) -> PlayerState:
        """Current playback state."""
        return self._player.state

    def page(self, number: int) -> Page:
        """Return the page with the given 1-based number."""
        return self._pages[number - 1]

    def segments(self, number: int) -> list[str]:
        """Sentence segments of a page, computed once and cached."""
        if number not in self._segments:
            self._segments[number] = split_into_segments(self.page(number).text)
        return self._segments[number]

    def set_pages(self, pages: list[Page], start_page: int = 1) -> None:
        """Load a new document and show ``start_page`` without playing."""
        self._player.stop()
        self._pages = list(pages)
        self._segments.clear()
        self.go_to_page(start_page)

    def go_to_page(self, number: int) -> None:
        """Make ``number`` the current page. Keeps playing if playback was active."""
        if not self._pages:
            return
        number = max(1, min(number, self.page_count))
        direction = 1 if number >= self._current else -1
        was_active = self._player.state is not PlayerState.STOPPED
        self._player.stop()
        self._current = number
        self.page_changed.emit(number)
        if was_active:
            self._play_current(direction)

    def play(self) -> None:
        """Play from the start of the current page, or resume if paused."""
        if self._player.state is PlayerState.PAUSED:
            self._player.resume()
        elif self._player.state is PlayerState.STOPPED and self._pages:
            self._play_current(direction=1)

    def pause(self) -> None:
        """Pause playback."""
        self._player.pause()

    def stop(self) -> None:
        """Stop playback; the current page stays selected."""
        self._player.stop()

    def set_speed(self, speed: float) -> None:
        """Set the speaking speed multiplier (0.5 to 2.0)."""
        self._player.set_speed(speed)

    def shutdown(self) -> None:
        """Release audio and worker resources."""
        self._player.shutdown()

    def _play_current(self, direction: int) -> None:
        """Play the current page, skipping pages without text in ``direction``."""
        while not self.page(self._current).has_text:
            self.page_skipped.emit(self._current)
            nxt = self._current + direction
            if not 1 <= nxt <= self.page_count:
                self._player.stop()
                self.finished.emit()
                return
            self._current = nxt
            self.page_changed.emit(nxt)
        self._player.play(self.segments(self._current))

    @Slot()
    def _on_page_finished(self) -> None:
        if self._current >= self.page_count:
            self.finished.emit()
            return
        self._current += 1
        self.page_changed.emit(self._current)
        self._play_current(direction=1)
