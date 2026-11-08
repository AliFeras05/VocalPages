"""Qt main window. Only widgets and wiring live here; the work happens in
``pdf_extract``, ``playback`` and ``export``."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction, QCloseEvent, QColor, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from readaloud import APP_NAME
from readaloud.pdf_extract import PdfError, extract_pages
from readaloud.playback import PlayerState, Reader
from readaloud.tts import KokoroEngine, locate_segments, normalize_page_text

HIGHLIGHT_COLOR = QColor(255, 230, 140)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, engine: KokoroEngine | None = None) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(900, 700)

        self._engine = engine or KokoroEngine()
        self._reader = Reader(self._engine, self)
        self._pdf_name = ""
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

        for action in (self.open_action, self.play_action, self.stop_action):
            toolbar.addAction(action)

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

        self._pdf_name = path.name
        self.setWindowTitle(f"{path.name} — {APP_NAME}")
        self._reader.set_pages(pages)
        empty = sum(1 for p in pages if not p.has_text)
        if empty:
            self.statusBar().showMessage(
                f"{empty} page(s) have no extractable text (scanned?) and will be skipped.", 8000
            )
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
        self.play_action.setText("Pause" if state is PlayerState.PLAYING else
                                 "Resume" if state is PlayerState.PAUSED else "Play")
        self.stop_action.setEnabled(state is not PlayerState.STOPPED)
        if state is PlayerState.STOPPED:
            self.text_view.setExtraSelections([])

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API name)
        """Stop audio and background threads before closing."""
        self._reader.shutdown()
        super().closeEvent(event)
