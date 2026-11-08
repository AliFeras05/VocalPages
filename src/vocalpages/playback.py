"""Audio playback of PDF pages.

``Reader`` is the document-level controller the GUI talks to: it tracks the
current section (PDF page or EPUB chapter), skips sections without text and
moves to the next one when a section finishes. ``SegmentPlayer`` plays one page's sentence segments through
``QAudioSink`` while a background thread synthesizes the next segment, so
there is no gap and the UI never blocks on the TTS model.
"""

from __future__ import annotations

import enum
import logging

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QThread, Signal, Slot
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices, QtAudio

from vocalpages.document import Document, Section
from vocalpages.tts import SAMPLE_RATE, KokoroEngine, TtsError, clamp_speed, to_pcm16

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
    """Document-level playback: current section, skipping empty sections and auto-advance.

    Works on any ``Document``; a section is a PDF page or an EPUB chapter.
    """

    section_changed = Signal(int)  # 1-based section number
    segment_started = Signal(int, int)  # section number, sentence index (audio started)
    position_changed = Signal(int, int)  # section number, sentence index (reading position)
    section_skipped = Signal(int)  # section number with no readable text
    state_changed = Signal(PlayerState)
    finished = Signal()
    engine_ready = Signal()
    error = Signal(str)

    def __init__(self, engine: KokoroEngine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._document: Document | None = None
        self._current = 1
        self._sentence = 0
        self._player = SegmentPlayer(engine, self)
        self._player.segment_started.connect(self._on_segment_started)
        self._player.finished.connect(self._on_section_finished)
        self._player.state_changed.connect(self.state_changed)
        self._player.engine_ready.connect(self.engine_ready)
        self._player.error.connect(self.error)

    @property
    def document(self) -> Document | None:
        """The open document, or None."""
        return self._document

    @property
    def section_count(self) -> int:
        """Number of sections in the open document (0 if none)."""
        return self._document.section_count if self._document else 0

    @property
    def current_section(self) -> int:
        """1-based number of the current section."""
        return self._current

    @property
    def current_sentence(self) -> int:
        """0-based index of the sentence playback starts from (or is reading now)."""
        return self._sentence

    @property
    def state(self) -> PlayerState:
        """Current playback state."""
        return self._player.state

    def section(self, number: int) -> Section:
        """Return the section with the given 1-based number."""
        if self._document is None:
            raise IndexError("No document is open")
        return self._document.section(number)

    def set_document(self, document: Document, start_section: int = 1, start_sentence: int = 0) -> None:
        """Load a new document and show ``start_section`` without playing.

        ``start_sentence`` is where the next Play begins (for resuming).
        """
        self._player.stop()
        self._document = document
        self._current = 1
        self.go_to_section(start_section)
        sentences = len(self.section(self._current).sentences)
        if 0 < start_sentence < sentences:
            self._set_position(self._current, start_sentence)

    def play_from(self, sentence: int) -> None:
        """Stop whatever is playing and start reading the current section at ``sentence``."""
        if not self.section_count:
            return
        sentences = self.section(self._current).sentences
        if not 0 <= sentence < len(sentences):
            return
        self._player.stop()
        self._set_position(self._current, sentence)
        self._player.play(list(sentences), start_index=sentence)

    def go_to_section(self, number: int) -> None:
        """Make ``number`` the current section. Keeps playing if playback was active."""
        if not self.section_count:
            return
        number = max(1, min(number, self.section_count))
        direction = 1 if number >= self._current else -1
        was_active = self._player.state is not PlayerState.STOPPED
        self._player.stop()
        self._current = number
        self._sentence = 0
        self.section_changed.emit(number)
        self.position_changed.emit(number, 0)
        if was_active:
            self._play_current(direction)

    def play(self) -> None:
        """Play from the current sentence, or resume if paused."""
        if self._player.state is PlayerState.PAUSED:
            self._player.resume()
        elif self._player.state is PlayerState.STOPPED and self.section_count:
            self._play_current(direction=1)

    def pause(self) -> None:
        """Pause playback."""
        self._player.pause()

    def stop(self) -> None:
        """Stop playback; the current section and sentence stay selected."""
        self._player.stop()

    def set_speed(self, speed: float) -> None:
        """Set the speaking speed multiplier (0.5 to 2.0)."""
        self._player.set_speed(speed)

    def shutdown(self) -> None:
        """Release audio and worker resources."""
        self._player.shutdown()

    def _play_current(self, direction: int) -> None:
        """Play the current section, skipping sections without text in ``direction``."""
        while not self.section(self._current).has_text:
            self.section_skipped.emit(self._current)
            nxt = self._current + direction
            if not 1 <= nxt <= self.section_count:
                self._player.stop()
                self.finished.emit()
                return
            self._current = nxt
            self._sentence = 0
            self.section_changed.emit(nxt)
        sentences = self.section(self._current).sentences
        start = self._sentence if self._sentence < len(sentences) else 0
        self._player.play(list(sentences), start_index=start)

    @Slot()
    def _on_section_finished(self) -> None:
        if self._current >= self.section_count:
            self.finished.emit()
            return
        self._current += 1
        self._sentence = 0
        self.section_changed.emit(self._current)
        self.position_changed.emit(self._current, 0)
        self._play_current(direction=1)

    def _set_position(self, section: int, sentence: int) -> None:
        self._sentence = sentence
        self.position_changed.emit(section, sentence)

    @Slot(int)
    def _on_segment_started(self, index: int) -> None:
        self._set_position(self._current, index)
        self.segment_started.emit(self._current, index)
