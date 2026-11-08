"""Qt main window. Only widgets and wiring live here; the work happens in
``document`` (and its loaders), ``playback`` and ``export``."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QObject, Qt, QThread, Slot
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QMouseEvent,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QSplitter,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from readaloud import APP_NAME
from readaloud.document import Document, DocumentError
from readaloud.export import ExportResult, output_format, resolve_section_range
from readaloud.export_dialog import ExportWorker, RangeDialog
from readaloud.playback import PlayerState, Reader
from readaloud.library import BookRecord, Library
from readaloud.sidebar import LibrarySidebar
from readaloud.sentences import locate_sentences, sentence_at
from readaloud.tts import KokoroEngine

HIGHLIGHT_COLOR = QColor(255, 230, 140)
HIGHLIGHT_TEXT_COLOR = QColor(20, 20, 20)  # readable on the highlight in light and dark themes
SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)


def pdf_from_mime(mime: QMimeData) -> Path | None:
    """Return the first local ``.pdf`` file in dragged data, or None."""
    for url in mime.urls():
        if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf"):
            return Path(url.toLocalFile())
    return None


class StartScreen(QFrame):
    """Shown before a PDF is open: invites the user to drop or choose a file."""

    def __init__(self, open_action: QAction, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("startScreen")
        self.setStyleSheet(
            "#startScreen { border: 2px dashed palette(mid); border-radius: 16px; }"
        )
        title = QLabel("Drop a PDF here", self)
        font = title.font()
        font.setPointSize(font.pointSize() + 10)
        font.setBold(True)
        title.setFont(font)
        hint = QLabel("or", self)
        button = QPushButton("Choose a PDF…", self)
        button.setMinimumHeight(36)
        button.clicked.connect(open_action.trigger)

        layout = QVBoxLayout(self)
        layout.addStretch()
        for widget in (title, hint, button):
            layout.addWidget(widget, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(
        self, engine: KokoroEngine | None = None, library: Library | None = None
    ) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 720)
        self.setAcceptDrops(True)

        self._engine = engine or KokoroEngine()
        self._reader = Reader(self._engine, self)
        self._library = library or Library()
        self._book: BookRecord | None = None
        self._export_thread: QThread | None = None
        self._export_worker: ExportWorker | None = None
        self._export_progress: QProgressDialog | None = None
        self._spans: list[tuple[int, int]] = []

        self._build_actions()
        self._build_layout()
        self._connect_reader()
        self._refresh_sidebar()
        self.show_home()
        self.statusBar().showMessage("Loading voice model…")

    # ----- construction -------------------------------------------------

    def _build_actions(self) -> None:
        toolbar = QToolBar("Playback", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.toolbar = toolbar

        self.open_action = QAction("Open PDF…", self, shortcut=QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.choose_file)
        self.play_action = QAction("Play", self, shortcut=Qt.Key.Key_Space)
        self.play_action.triggered.connect(self._toggle_play)
        self.stop_action = QAction("Stop", self)
        self.stop_action.triggered.connect(self._reader.stop)
        self.prev_action = QAction("◀ Previous", self, shortcut=Qt.Key.Key_PageUp)
        self.prev_action.triggered.connect(lambda: self._reader.go_to_section(self._reader.current_section - 1))
        self.next_action = QAction("Next ▶", self, shortcut=Qt.Key.Key_PageDown)
        self.next_action.triggered.connect(lambda: self._reader.go_to_section(self._reader.current_section + 1))

        for action in (self.open_action, self.play_action, self.stop_action, self.prev_action, self.next_action):
            toolbar.addAction(action)

        toolbar.addSeparator()
        self.goto_label = QLabel(" Go to page ", self)
        toolbar.addWidget(self.goto_label)
        self.section_spin = QSpinBox(self)
        self.section_spin.setMinimum(1)
        self.section_spin.setKeyboardTracking(False)
        self.section_spin.editingFinished.connect(self._jump_to_spin_section)
        toolbar.addWidget(self.section_spin)
        self.go_action = QAction("Go", self)
        self.go_action.triggered.connect(self._jump_to_spin_section)
        toolbar.addAction(self.go_action)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" Speed ", self))
        self.speed_combo = QComboBox(self)
        for speed in SPEEDS:
            self.speed_combo.addItem(f"{speed:g}×", speed)
        self.speed_combo.setCurrentIndex(SPEEDS.index(1.0))
        self.speed_combo.currentIndexChanged.connect(
            lambda _i: self._reader.set_speed(self.speed_combo.currentData())
        )
        toolbar.addWidget(self.speed_combo)

        toolbar.addSeparator()
        self.export_action = QAction("Export audio…", self, shortcut=QKeySequence("Ctrl+E"))
        self.export_action.triggered.connect(self.start_export)
        toolbar.addAction(self.export_action)

    def _build_layout(self) -> None:
        self.page_label = QLabel("No document open", self)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.text_view = QPlainTextEdit(self)
        self.text_view.setReadOnly(True)
        font = self.text_view.font()
        font.setPointSize(font.pointSize() + 3)
        self.text_view.setFont(font)
        self.text_view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.text_view.viewport().installEventFilter(self)
        self.text_view.setToolTip("Click a sentence to start reading from it")

        reading_view = QWidget(self)
        layout = QVBoxLayout(reading_view)
        layout.addWidget(self.page_label)
        layout.addWidget(self.text_view)

        start_container = QWidget(self)
        start_layout = QVBoxLayout(start_container)
        start_layout.setContentsMargins(40, 40, 40, 40)
        start_layout.addWidget(StartScreen(self.open_action, start_container))

        self.stack = QStackedWidget(self)
        self.stack.addWidget(start_container)
        self.stack.addWidget(reading_view)

        self.sidebar = LibrarySidebar(self)
        self.sidebar.home_requested.connect(self.show_home)
        self.sidebar.book_selected.connect(self.open_book)
        self.sidebar.remove_requested.connect(self._confirm_remove)

        splitter = QSplitter(self)
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([260, 840])
        self.setCentralWidget(splitter)

    def _connect_reader(self) -> None:
        self._reader.section_changed.connect(self._show_section)
        self._reader.position_changed.connect(self._highlight_segment)
        self._reader.position_changed.connect(self._save_position)
        self._reader.section_skipped.connect(self._on_section_skipped)
        self._reader.state_changed.connect(lambda _state: self._update_controls())
        self._reader.finished.connect(lambda: self.statusBar().showMessage("Finished reading.", 5000))
        self._reader.engine_ready.connect(lambda: self.statusBar().showMessage("Voice model ready.", 3000))
        self._reader.error.connect(self._show_error)

    # ----- actions ------------------------------------------------------

    @Slot()
    def choose_file(self) -> None:
        """Ask the user for a document and open it."""
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", str(Path.home()), "PDF files (*.pdf)")
        if path:
            self.open_file(Path(path))

    def open_file(self, path: Path) -> None:
        """Add the file at ``path`` to the library (or find it there) and open it."""
        try:
            record, document, _is_new = self._library.add(path)
        except DocumentError as exc:
            self._show_error(str(exc))
            return
        except OSError:
            self._show_error(f"Could not read {path.name}.")
            return
        self._show_document(record, document)

    @Slot(str)
    def open_book(self, book_id: str) -> None:
        """Open a library book exactly where it was left off."""
        if self._book is not None and self._book.id == book_id and self.stack.currentIndex() == 1:
            return
        record = self._library.get(book_id)
        if record is None:
            return
        try:
            document = self._library.load(book_id)
        except (DocumentError, OSError) as exc:
            self._show_error(f"Could not open “{record.title}”: {exc}")
            return
        self._show_document(record, document)

    @Slot()
    def show_home(self) -> None:
        """Stop reading and show the home page."""
        self._reader.stop()
        self.stack.setCurrentIndex(0)
        self.toolbar.setVisible(False)
        self.sidebar.select(None)
        self.setWindowTitle(APP_NAME)
        self.statusBar().clearMessage()

    def _show_document(self, record: BookRecord, document: Document) -> None:
        if not document.section_count:
            self._show_error("This document has nothing to read.")
            return
        self._book = None  # don't save positions while the new book loads
        self.stack.setCurrentIndex(1)
        self.toolbar.setVisible(True)
        self.setWindowTitle(f"{document.title} — {APP_NAME}")
        self.goto_label.setText(f" Go to {document.unit.lower()} ")
        self._reader.set_document(document, start_section=record.section, start_sentence=record.sentence)
        self._book = record
        self._refresh_sidebar()
        empty = sum(1 for section in document.sections if not section.has_text)
        if empty:
            self.statusBar().showMessage(
                f"{empty} {document.unit.lower()}(s) have no readable text (scanned?) and will be skipped.",
                8000,
            )
        self._update_controls()

    @Slot(str)
    def _confirm_remove(self, book_id: str) -> None:
        record = self._library.get(book_id)
        if record is None:
            return
        answer = QMessageBox.question(
            self,
            APP_NAME,
            f"Remove “{record.title}” from the library?\n\n"
            "Your original file is not deleted; only Readaloud's copy and reading position are.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self._book is not None and self._book.id == book_id:
            self._book = None
            self.show_home()
        self._library.remove(book_id)
        self._refresh_sidebar()

    @Slot(int, int)
    def _save_position(self, section: int, sentence: int) -> None:
        if self._book is None:
            return
        self._library.save_position(self._book.id, section, sentence)
        if section != self._book.section:
            self._book = replace(self._book, section=section, sentence=sentence)
            self.sidebar.update_progress(self._book.id, self._book.progress_text)

    def _refresh_sidebar(self) -> None:
        self.sidebar.set_books(self._library.books(), self._book.id if self._book else None)

    @Slot()
    def _jump_to_spin_section(self) -> None:
        if self.section_spin.value() != self._reader.current_section:
            self._reader.go_to_section(self.section_spin.value())

    @Slot()
    def start_export(self) -> None:
        """Ask for a section range and output file, then export on a worker thread."""
        document = self._reader.document
        if self._export_thread is not None or document is None:
            return
        dialog = RangeDialog(document.unit, document.section_count, self._reader.current_section, self)
        if dialog.exec() != RangeDialog.DialogCode.Accepted:
            return
        try:
            numbers = resolve_section_range(*dialog.selected_range(), document.section_count)
        except ValueError as exc:
            self._show_error(str(exc))
            return

        stem = Path(self._book.original_name).stem if self._book else document.title
        suggested = str(Path.home() / f"{stem}.mp3")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export audio", suggested, "MP3 audio (*.mp3);;WAV audio (*.wav)"
        )
        if not path:
            return
        out_path = Path(path)
        try:
            output_format(out_path)
        except ValueError as exc:
            self._show_error(str(exc))
            return

        worker = ExportWorker(
            document.sections, numbers, out_path, self._engine, self.speed_combo.currentData()
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_export_progress)
        worker.finished.connect(self._on_export_finished)
        worker.failed.connect(self._on_export_failed)
        worker.cancelled.connect(self._on_export_cancelled)

        progress = QProgressDialog("Preparing export…", "Cancel", 0, 0, self)
        progress.setWindowTitle("Exporting audio")
        progress.setModal(False)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(worker.cancel)
        progress.show()

        self._export_thread, self._export_worker, self._export_progress = thread, worker, progress
        self._update_controls()
        thread.start()

    @Slot(int, int)
    def _on_export_progress(self, done: int, total: int) -> None:
        if self._export_progress is not None:
            self._export_progress.setMaximum(total)
            self._export_progress.setValue(done)
            self._export_progress.setLabelText(f"Synthesizing sentence {done} of {total}…")

    @Slot(object)
    def _on_export_finished(self, result: ExportResult) -> None:
        self._end_export()
        document = self._reader.document
        minutes, seconds = divmod(round(result.duration_seconds), 60)
        message = f"Exported {result.path.name} ({minutes}:{seconds:02d})."
        if result.skipped_sections and document is not None:
            skipped = ", ".join(map(str, result.skipped_sections))
            message += f"\nSkipped {document.unit.lower()}(s) with no readable text: {skipped}."
        QMessageBox.information(self, APP_NAME, message)

    @Slot(str)
    def _on_export_failed(self, message: str) -> None:
        self._end_export()
        self._show_error(f"Export failed: {message}")

    @Slot()
    def _on_export_cancelled(self) -> None:
        self._end_export()
        self.statusBar().showMessage("Export cancelled.", 5000)

    def _end_export(self) -> None:
        if self._export_progress is not None:
            self._export_progress.close()
            self._export_progress.deleteLater()
        if self._export_thread is not None:
            self._export_thread.quit()
            self._export_thread.wait()
            self._export_thread.deleteLater()
        if self._export_worker is not None:
            self._export_worker.deleteLater()
        self._export_thread = self._export_worker = self._export_progress = None
        self._update_controls()

    @Slot()
    def _toggle_play(self) -> None:
        if self._reader.state is PlayerState.PLAYING:
            self._reader.pause()
        else:
            self._reader.play()

    # ----- reader signal handlers --------------------------------------

    @Slot(int)
    def _show_section(self, number: int) -> None:
        section = self._reader.section(number)
        unit = self._reader.document.unit if self._reader.document else "Page"
        self.page_label.setText(f"{unit} {number} of {self._reader.section_count}")
        self.section_spin.blockSignals(True)
        self.section_spin.setMaximum(self._reader.section_count)
        self.section_spin.setValue(number)
        self.section_spin.blockSignals(False)
        if section.has_text:
            self._spans = locate_sentences(section.text, list(section.sentences))
            self.text_view.setPlainText(section.text)
        else:
            self._spans = []
            self.text_view.setPlainText(
                f"This {unit.lower()} has no readable text. It may be a scanned image; it will be skipped."
            )
        self._update_controls()

    @Slot(int, int)
    def _highlight_segment(self, section_number: int, index: int) -> None:
        if section_number != self._reader.current_section or not 0 <= index < len(self._spans):
            return
        start, end = self._spans[index]
        cursor = QTextCursor(self.text_view.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format = QTextCharFormat()
        selection.format.setBackground(HIGHLIGHT_COLOR)
        selection.format.setForeground(HIGHLIGHT_TEXT_COLOR)
        self.text_view.setExtraSelections([selection])
        view_cursor = QTextCursor(cursor)
        view_cursor.clearSelection()
        self.text_view.setTextCursor(view_cursor)
        self.text_view.ensureCursorVisible()

    @Slot(int)
    def _on_section_skipped(self, number: int) -> None:
        unit = self._reader.document.unit if self._reader.document else "Page"
        self.statusBar().showMessage(
            f"{unit} {number} has no readable text (it may be a scanned image). Skipped.", 6000
        )

    @Slot(str)
    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, APP_NAME, message)

    # ----- helpers ------------------------------------------------------

    def _update_controls(self) -> None:
        has_doc = self._reader.section_count > 0
        state = self._reader.state
        self.play_action.setEnabled(has_doc)
        current = self._reader.current_section
        self.prev_action.setEnabled(has_doc and current > 1)
        self.next_action.setEnabled(has_doc and current < self._reader.section_count)
        self.section_spin.setEnabled(has_doc)
        self.go_action.setEnabled(has_doc)
        self.export_action.setEnabled(has_doc and self._export_thread is None)
        self.play_action.setText("Pause" if state is PlayerState.PLAYING else
                                 "Resume" if state is PlayerState.PAUSED else "Play")
        self.stop_action.setEnabled(state is not PlayerState.STOPPED)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API name)
        """Start reading from a sentence when it is clicked (a drag-selection is left alone)."""
        if (
            watched is self.text_view.viewport()
            and event.type() == QEvent.Type.MouseButtonRelease
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
            and not self.text_view.textCursor().hasSelection()
        ):
            position = self.text_view.cursorForPosition(event.position().toPoint()).position()
            index = sentence_at(self._spans, position)
            if index is not None:
                self._reader.play_from(index)
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 (Qt API name)
        """Accept drags that contain a PDF file."""
        if pdf_from_mime(event.mimeData()) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 (Qt API name)
        """Open a PDF dropped onto the window."""
        path = pdf_from_mime(event.mimeData())
        if path is not None:
            event.acceptProposedAction()
            self.open_file(path)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API name)
        """Stop audio and background threads before closing."""
        if self._export_worker is not None and self._export_thread is not None:
            self._export_worker.cancel()
            self._export_thread.quit()
            self._export_thread.wait()
        self._reader.shutdown()
        self._library.close()
        super().closeEvent(event)
