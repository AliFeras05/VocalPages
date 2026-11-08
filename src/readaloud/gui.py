"""Qt main window. Only widgets and wiring live here; the work happens in
``pdf_extract``, ``playback`` and ``export``."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Slot
from PySide6.QtGui import QAction, QCloseEvent, QColor, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QSpinBox,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from readaloud import APP_NAME
from readaloud.export import ExportResult, output_format, resolve_page_range
from readaloud.export_dialog import ExportWorker, PageRangeDialog
from readaloud.pdf_extract import PdfError, extract_pages
from readaloud.playback import PlayerState, Reader
from readaloud.state import ResumeStore, fingerprint
from readaloud.tts import KokoroEngine, locate_segments, normalize_page_text

HIGHLIGHT_COLOR = QColor(255, 230, 140)
HIGHLIGHT_TEXT_COLOR = QColor(20, 20, 20)  # readable on the highlight in light and dark themes
SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(
        self, engine: KokoroEngine | None = None, resume_store: ResumeStore | None = None
    ) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(900, 700)

        self._engine = engine or KokoroEngine()
        self._reader = Reader(self._engine, self)
        self._store = resume_store or ResumeStore()
        self._pdf_key = ""
        self._pdf_stem = ""
        self._export_thread: QThread | None = None
        self._export_worker: ExportWorker | None = None
        self._export_progress: QProgressDialog | None = None
        self._spans: list[tuple[int, int]] = []

        self._build_actions()
        self._build_layout()
        self._connect_reader()
        self._update_controls()
        self.statusBar().showMessage("Loading voice model…")

    # ----- construction -------------------------------------------------

    def _build_actions(self) -> None:
        toolbar = QToolBar("Playback", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.open_action = QAction("Open PDF…", self, shortcut=QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.choose_pdf)
        self.play_action = QAction("Play", self, shortcut=Qt.Key.Key_Space)
        self.play_action.triggered.connect(self._toggle_play)
        self.stop_action = QAction("Stop", self)
        self.stop_action.triggered.connect(self._reader.stop)
        self.prev_action = QAction("◀ Previous", self, shortcut=QKeySequence.StandardKey.MoveToPreviousPage)
        self.prev_action.triggered.connect(lambda: self._reader.go_to_page(self._reader.current_page - 1))
        self.next_action = QAction("Next ▶", self, shortcut=QKeySequence.StandardKey.MoveToNextPage)
        self.next_action.triggered.connect(lambda: self._reader.go_to_page(self._reader.current_page + 1))

        for action in (self.open_action, self.play_action, self.stop_action, self.prev_action, self.next_action):
            toolbar.addAction(action)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" Go to page ", self))
        self.page_spin = QSpinBox(self)
        self.page_spin.setMinimum(1)
        self.page_spin.setKeyboardTracking(False)
        self.page_spin.editingFinished.connect(self._jump_to_spin_page)
        toolbar.addWidget(self.page_spin)
        self.go_action = QAction("Go", self)
        self.go_action.triggered.connect(self._jump_to_spin_page)
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
        self.page_label = QLabel("No PDF open", self)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.text_view = QPlainTextEdit(self)
        self.text_view.setReadOnly(True)
        font = self.text_view.font()
        font.setPointSize(font.pointSize() + 3)
        self.text_view.setFont(font)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(self.page_label)
        layout.addWidget(self.text_view)
        self.setCentralWidget(central)

    def _connect_reader(self) -> None:
        self._reader.page_changed.connect(self._show_page)
        self._reader.segment_started.connect(self._highlight_segment)
        self._reader.page_skipped.connect(self._on_page_skipped)
        self._reader.state_changed.connect(lambda _state: self._update_controls())
        self._reader.finished.connect(lambda: self.statusBar().showMessage("Finished reading.", 5000))
        self._reader.engine_ready.connect(lambda: self.statusBar().showMessage("Voice model ready.", 3000))
        self._reader.error.connect(self._show_error)

    # ----- actions ------------------------------------------------------

    @Slot()
    def choose_pdf(self) -> None:
        """Ask the user for a PDF and open it."""
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", str(Path.home()), "PDF files (*.pdf)")
        if path:
            self.open_pdf(Path(path))

    def open_pdf(self, path: Path) -> None:
        """Extract the PDF at ``path`` and show its first page."""
        try:
            pages = extract_pages(path)
        except PdfError as exc:
            self._show_error(str(exc))
            return
        if not pages:
            self._show_error("This PDF has no pages.")
            return

        self._pdf_key = ""  # don't record the old PDF's key while switching
        self.setWindowTitle(f"{path.name} — {APP_NAME}")
        self._pdf_stem = path.stem
        key = fingerprint(path)
        self._reader.set_pages(pages, start_page=self._ask_resume_page(key, len(pages)))
        self._pdf_key = key
        self._store.set(key, self._reader.current_page)
        empty = sum(1 for p in pages if not p.has_text)
        if empty:
            self.statusBar().showMessage(
                f"{empty} page(s) have no extractable text (scanned?) and will be skipped.", 8000
            )
        self._update_controls()

    def _ask_resume_page(self, key: str, page_count: int) -> int:
        """Offer to resume from the saved page; return the page to start on."""
        saved = self._store.get(key)
        if saved is None or saved <= 1 or saved > page_count:
            return 1
        answer = QMessageBox.question(
            self,
            APP_NAME,
            f"You stopped at page {saved} of {page_count} last time. Resume from there?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return saved if answer == QMessageBox.StandardButton.Yes else 1

    @Slot()
    def _jump_to_spin_page(self) -> None:
        if self.page_spin.value() != self._reader.current_page:
            self._reader.go_to_page(self.page_spin.value())

    @Slot()
    def start_export(self) -> None:
        """Ask for a page range and output file, then export on a worker thread."""
        if self._export_thread is not None or self._reader.page_count == 0:
            return
        dialog = PageRangeDialog(self._reader.page_count, self._reader.current_page, self)
        if dialog.exec() != PageRangeDialog.DialogCode.Accepted:
            return
        try:
            numbers = resolve_page_range(*dialog.selected_range(), self._reader.page_count)
        except ValueError as exc:
            self._show_error(str(exc))
            return

        suggested = str(Path.home() / f"{self._pdf_stem}.mp3")
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
            self._reader.pages, numbers, out_path, self._engine, self.speed_combo.currentData()
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
        minutes, seconds = divmod(round(result.duration_seconds), 60)
        message = f"Exported {result.path.name} ({minutes}:{seconds:02d})."
        if result.skipped_pages:
            pages = ", ".join(map(str, result.skipped_pages))
            message += f"\nSkipped page(s) with no extractable text: {pages}."
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
    def _show_page(self, number: int) -> None:
        page = self._reader.page(number)
        self.page_label.setText(f"Page {number} of {self._reader.page_count}")
        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(self._reader.page_count)
        self.page_spin.setValue(number)
        self.page_spin.blockSignals(False)
        if self._pdf_key:
            self._store.set(self._pdf_key, number)
        if page.has_text:
            display = normalize_page_text(page.text)
            self._spans = locate_segments(display, self._reader.segments(number))
            self.text_view.setPlainText(display)
        else:
            self._spans = []
            self.text_view.setPlainText(
                "This page has no extractable text. It may be a scanned image; it will be skipped."
            )
        self._update_controls()

    @Slot(int, int)
    def _highlight_segment(self, page_number: int, index: int) -> None:
        if page_number != self._reader.current_page or not 0 <= index < len(self._spans):
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
    def _on_page_skipped(self, number: int) -> None:
        self.statusBar().showMessage(
            f"Page {number} has no extractable text (it may be a scanned image). Skipped.", 6000
        )

    @Slot(str)
    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, APP_NAME, message)

    # ----- helpers ------------------------------------------------------

    def _update_controls(self) -> None:
        has_doc = self._reader.page_count > 0
        state = self._reader.state
        self.play_action.setEnabled(has_doc)
        current = self._reader.current_page
        self.prev_action.setEnabled(has_doc and current > 1)
        self.next_action.setEnabled(has_doc and current < self._reader.page_count)
        self.page_spin.setEnabled(has_doc)
        self.go_action.setEnabled(has_doc)
        self.export_action.setEnabled(has_doc and self._export_thread is None)
        self.play_action.setText("Pause" if state is PlayerState.PLAYING else
                                 "Resume" if state is PlayerState.PAUSED else "Play")
        self.stop_action.setEnabled(state is not PlayerState.STOPPED)
        if state is PlayerState.STOPPED:
            self.text_view.setExtraSelections([])

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API name)
        """Stop audio and background threads before closing."""
        if self._export_worker is not None and self._export_thread is not None:
            self._export_worker.cancel()
            self._export_thread.quit()
            self._export_thread.wait()
        self._reader.shutdown()
        super().closeEvent(event)
