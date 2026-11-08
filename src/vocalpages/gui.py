"""Qt main window. Only widgets and wiring live here; the work happens in
``document`` (and its loaders), ``playback`` and ``export``."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QThread, QTimer, Slot
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QKeySequence,
    QMouseEvent,

)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QSplitter,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vocalpages import APP_NAME, theme
from vocalpages.document import Document, DocumentError
from vocalpages.export import ExportResult, output_format, resolve_section_range
from vocalpages.export_dialog import ExportWorker, RangeDialog
from vocalpages.playback import PlayerState, Reader
from vocalpages.reader_view import ReaderView
from vocalpages.icons import IconSet
from vocalpages.home import FILE_DIALOG_FILTER, HomePage, is_supported, local_file_from_mime
from vocalpages.library import BookRecord, Library
from vocalpages.settings import Settings, initial_theme, system_prefers_dark
from vocalpages.sidebar import LibrarySidebar
from vocalpages.sentences import locate_sentences, sentence_at
from vocalpages.tts import KokoroEngine

SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(
        self,
        engine: KokoroEngine | None = None,
        library: Library | None = None,
        settings_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 720)
        self.setAcceptDrops(True)

        self.icons = IconSet(theme.LIGHT, self)
        self._theme = "light"
        self._engine = engine or KokoroEngine()
        self._reader = Reader(self._engine, self)
        self._library = library or Library()
        self._settings = Settings(settings_dir or self._library.data_dir)
        self._book: BookRecord | None = None
        self._export_thread: QThread | None = None
        self._export_worker: ExportWorker | None = None
        self._export_progress: QProgressDialog | None = None
        self._spans: list[tuple[int, int]] = []

        self._build_actions()
        self._build_layout()
        self._connect_reader()
        self.apply_theme(initial_theme(self._settings.theme, system_prefers_dark()))
        self._refresh_sidebar()
        self.show_home()
        self.show_status("Loading voice model…")

    # ----- construction -------------------------------------------------

    def _build_actions(self) -> None:
        self.open_action = self._icon_action("folder-open", "Open a book", QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.choose_file)
        self.play_action = self._icon_action("play", "Play", Qt.Key.Key_Space)
        self.play_action.triggered.connect(self._toggle_play)
        self.stop_action = self._icon_action("square", "Stop")
        self.stop_action.triggered.connect(self._reader.stop)
        self.prev_action = self._icon_action("skip-back", "Previous page", Qt.Key.Key_PageUp)
        self.prev_action.triggered.connect(lambda: self._reader.go_to_section(self._reader.current_section - 1))
        self.next_action = self._icon_action("skip-forward", "Next page", Qt.Key.Key_PageDown)
        self.next_action.triggered.connect(lambda: self._reader.go_to_section(self._reader.current_section + 1))
        self.go_action = self._icon_action("corner-down-left", "Go to page")
        self.go_action.triggered.connect(self._jump_to_spin_section)
        self.export_action = self._icon_action("download", "Export audio", QKeySequence("Ctrl+E"))
        self.export_action.triggered.connect(self.start_export)
        for action in (self.open_action, self.play_action, self.prev_action, self.next_action, self.export_action):
            self.addAction(action)  # shortcuts work wherever the buttons are

        self.section_spin = QSpinBox(self)
        self.section_spin.setMinimum(1)
        self.section_spin.setKeyboardTracking(False)
        self.section_spin.editingFinished.connect(self._jump_to_spin_section)

        self.speed_button = QToolButton(self)
        self.speed_button.setObjectName("speedButton")
        self.speed_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.icons.bind(self.speed_button, "gauge")
        speed_menu = QMenu(self.speed_button)
        for speed in SPEEDS:
            action = speed_menu.addAction(f"{speed:g}×")
            action.setCheckable(True)
            action.setData(speed)
            action.triggered.connect(lambda _checked=False, s=speed: self._set_speed(s))
        self.speed_menu = speed_menu
        self.speed_button.setMenu(speed_menu)
        self.speed_value = QLabel(self)
        self.speed_value.setObjectName("playerLabel")
        self._set_speed(1.0)

    def _icon_action(self, icon: str, label: str, shortcut: object = None) -> QAction:
        """An icon-only action: ``label`` becomes its tooltip and accessible name."""
        action = QAction(label, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
            action.setToolTip(f"{label} ({QKeySequence(shortcut).toString(QKeySequence.SequenceFormat.NativeText)})")
        self.icons.bind(action, icon)
        return action

    def _set_speed(self, speed: float) -> None:
        for action in self.speed_menu.actions():
            action.setChecked(action.data() == speed)
        self.speed_button.setToolTip(f"Reading speed: {speed:g}×")
        self.speed_value.setText(f"{speed:g}×")
        self.speed_button.setAccessibleName(f"Reading speed, {speed:g} times")
        self.speed = speed
        self._reader.set_speed(speed)

    def _action_button(self, action: QAction, object_name: str = "") -> QToolButton:
        """An icon-only button driven by ``action`` (icon, tooltip, enabled state)."""
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if object_name:
            button.setObjectName(object_name)
        button.setAccessibleName(action.text())
        action.changed.connect(lambda: button.setAccessibleName(action.text()))
        return button

    def _build_reader_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("readerPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        self.book_heading = QLabel(page)
        self.book_heading.setObjectName("bookHeading")
        self.page_label = QLabel(page)
        self.page_label.setObjectName("sectionTitle")
        titles = QVBoxLayout()
        titles.setSpacing(theme.space(0.5))
        titles.addWidget(self.page_label)
        titles.addWidget(self.book_heading)
        header = QHBoxLayout()
        header.setContentsMargins(theme.space(4), theme.space(3), theme.space(3), theme.space(1))
        header.addLayout(titles, 1)
        header.addWidget(self._action_button(self.open_action))
        header.addWidget(self._action_button(self.export_action))

        self.text_view = ReaderView(page)
        self.text_view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.text_view.viewport().installEventFilter(self)
        self.text_view.setToolTip("Click a sentence to start reading from it")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.text_view, 1)
        layout.addWidget(self._build_player_bar(page))
        return page

    def _build_player_bar(self, parent: QWidget) -> QFrame:
        bar = QFrame(parent)
        bar.setObjectName("playerBar")
        bar.setAccessibleName("Player controls")
        bar.setFixedHeight(theme.BOTTOM_BAR_HEIGHT)

        self.play_button = self._action_button(self.play_action, "playButton")
        self.icons.bind(self.play_action, "play", role="on_accent", size=theme.ICON_LARGE)
        controls = QHBoxLayout()
        controls.setSpacing(theme.space(1))
        controls.addWidget(self._action_button(self.stop_action))
        controls.addWidget(self._action_button(self.prev_action))
        controls.addWidget(self.play_button)
        controls.addWidget(self._action_button(self.next_action))

        self.position_label = QLabel(bar)
        self.position_label.setObjectName("positionLabel")
        self.section_progress = QProgressBar(bar)
        self.section_progress.setObjectName("sectionProgress")
        self.section_progress.setTextVisible(False)
        self.section_progress.setAccessibleName("Position in book")
        progress = QVBoxLayout()
        progress.setSpacing(theme.space(1))
        progress.addStretch()
        progress.addWidget(self.position_label)
        progress.addWidget(self.section_progress)
        progress.addStretch()

        jump = QHBoxLayout()
        jump.setSpacing(theme.space(0.5))
        jump.addWidget(self.section_spin)
        jump.addWidget(self._action_button(self.go_action))
        speed = QHBoxLayout()
        speed.setSpacing(0)
        speed.addWidget(self.speed_button)
        speed.addWidget(self.speed_value)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(theme.space(3), 0, theme.space(3), 0)
        layout.setSpacing(theme.space(3))
        layout.addLayout(controls)
        layout.addLayout(progress, 1)
        layout.addLayout(jump)
        layout.addLayout(speed)
        return bar

    def _build_layout(self) -> None:
        reading_view = self._build_reader_page()

        self.home = HomePage(self.icons, self)
        self.home.choose_requested.connect(self.choose_file)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.home)
        self.stack.addWidget(reading_view)

        self.sidebar = LibrarySidebar(self.icons, self)
        self.sidebar.home_requested.connect(self.show_home)
        self.sidebar.book_selected.connect(self.open_book)
        self.sidebar.remove_requested.connect(self._confirm_remove)

        self.status_label = QLabel(self)
        self.status_label.setObjectName("statusText")
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName("Status")
        self.sidebar.add_footer_widget(self.status_label, stretch=1)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(lambda: self.status_label.clear())

        self.theme_button = QToolButton(self)
        self.theme_button.setObjectName("themeButton")
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.clicked.connect(self.toggle_theme)
        self.sidebar.add_footer_widget(self.theme_button)

        splitter = QSplitter(self)
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([theme.SIDEBAR_WIDTH, 1100 - theme.SIDEBAR_WIDTH])
        splitter.setHandleWidth(1)
        self.setCentralWidget(splitter)

    def _connect_reader(self) -> None:
        self._reader.section_changed.connect(self._show_section)
        self._reader.position_changed.connect(self._highlight_segment)
        self._reader.position_changed.connect(self._save_position)
        self._reader.section_skipped.connect(self._on_section_skipped)
        self._reader.state_changed.connect(lambda _state: self._update_controls())
        self._reader.finished.connect(lambda: self.show_status("Finished reading.", 5000))
        self._reader.engine_ready.connect(lambda: self.show_status("Voice model ready.", 3000))
        self._reader.error.connect(self._show_error)

    # ----- actions ------------------------------------------------------

    @Slot()
    def choose_file(self) -> None:
        """Ask the user for a document and open it."""
        path, _ = QFileDialog.getOpenFileName(self, "Open a book", str(Path.home()), FILE_DIALOG_FILTER)
        if path:
            self.open_file(Path(path))

    def open_file(self, path: Path) -> None:
        """Add the file at ``path`` to the library (or find it there) and open it.

        Problems are reported inline on the home page, or in a dialog while reading.
        """
        if not is_supported(path):
            self._report_open_error(
                f"“{path.name}” can't be opened. VocalPages reads PDF (.pdf) and EPUB (.epub) files."
            )
            return
        try:
            record, document, _is_new = self._library.add(path)
        except DocumentError as exc:
            self._report_open_error(f"“{path.name}” can't be opened. {exc}")
            return
        except OSError:
            self._report_open_error(f"Could not read “{path.name}”.")
            return
        self.home.clear_error()
        self._show_document(record, document)

    def _report_open_error(self, message: str) -> None:
        if self.stack.currentIndex() == 0:
            self.home.show_error(message)
        else:
            self._show_error(message)

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

    def show_status(self, message: str, timeout_ms: int = 0) -> None:
        """Show a short status message in the sidebar footer (cleared after ``timeout_ms``)."""
        self.status_label.setText(message)
        self._status_timer.stop()
        if message and timeout_ms:
            self._status_timer.start(timeout_ms)

    @property
    def theme_name(self) -> str:
        """The active theme, "light" or "dark"."""
        return self._theme

    def apply_theme(self, name: str) -> None:
        """Switch every screen to the ``name`` palette instantly (playback continues)."""
        palette = theme.PALETTES[name]
        self._theme = name
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.build_stylesheet(palette))
        self.icons.set_palette(palette)
        self.text_view.set_palette(palette)
        to_dark = name == "light"
        label = "Switch to dark theme" if to_dark else "Switch to light theme"
        self.theme_button.setToolTip(label)
        self.theme_button.setAccessibleName(label)
        self.icons.bind(self.theme_button, "moon" if to_dark else "sun")

    @Slot()
    def toggle_theme(self) -> None:
        """Switch between light and dark and remember the choice."""
        new = "dark" if self._theme == "light" else "light"
        self.apply_theme(new)
        self._settings.theme = new

    @Slot()
    def show_home(self) -> None:
        """Stop reading and show the home page."""
        self._reader.stop()
        self.stack.setCurrentIndex(0)
        self.sidebar.list.setFocus()
        self.sidebar.select(None)
        self.setWindowTitle(APP_NAME)
        self.show_status("")

    def _show_document(self, record: BookRecord, document: Document) -> None:
        if not document.section_count:
            self._show_error("This document has nothing to read.")
            return
        self._book = None  # don't save positions while the new book loads
        self.stack.setCurrentIndex(1)
        self.setWindowTitle(f"{document.title} — {APP_NAME}")
        self.book_heading.setText(document.title)
        unit = document.unit.lower()
        self.prev_action.setText(f"Previous {unit}")
        self.next_action.setText(f"Next {unit}")
        self.go_action.setText(f"Go to {unit}")
        self.section_spin.setToolTip(f"{document.unit} number (press Enter to go)")
        self.section_spin.setAccessibleName(f"{document.unit} number")
        for action, key in ((self.prev_action, Qt.Key.Key_PageUp), (self.next_action, Qt.Key.Key_PageDown)):
            native = QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)
            action.setToolTip(f"{action.text()} ({native})")
        self._reader.set_document(document, start_section=record.section, start_sentence=record.sentence)
        self._book = record
        self._refresh_sidebar()
        self.text_view.setFocus()
        empty = sum(1 for section in document.sections if not section.has_text)
        if empty:
            self.show_status(
                f"{empty} {document.unit.lower()}(s) have no readable text (scanned?) and will be skipped.",
                8000,
            )
        self._update_controls()

    @Slot(str)
    def _confirm_remove(self, book_id: str) -> None:
        record = self._library.get(book_id)
        if record is None:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Remove from library")
        box.setText(f"Remove “{record.title}” from the library?")
        box.setInformativeText(
            "This removes VocalPages' copy and your reading position. Your original file is not deleted."
        )
        remove = box.addButton("Remove from library", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is not remove:
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
            self.sidebar.update_progress(self._book)

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
            document.sections, numbers, out_path, self._engine, self.speed
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
        self.show_status("Export cancelled.", 5000)

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
        count = self._reader.section_count
        self.page_label.setText(f"{unit.upper()} {number} OF {count}")
        self.page_label.setAccessibleName(f"{unit} {number} of {count}")
        self.position_label.setText(f"{unit} {number} of {count}")
        self.section_progress.setRange(0, max(count, 1))
        self.section_progress.setValue(number)
        self.section_spin.blockSignals(True)
        self.section_spin.setMaximum(self._reader.section_count)
        self.section_spin.setValue(number)
        self.section_spin.blockSignals(False)
        if section.has_text:
            self._spans = locate_sentences(section.text, list(section.sentences))
            self.text_view.set_section_text(section.text)
        else:
            self._spans = []
            self.text_view.set_section_text(
                f"This {unit.lower()} has no readable text. It may be a scanned image; it will be skipped."
            )
        self._update_controls()

    @Slot(int, int)
    def _highlight_segment(self, section_number: int, index: int) -> None:
        if section_number != self._reader.current_section or not 0 <= index < len(self._spans):
            return
        self.text_view.highlight(*self._spans[index])

    @Slot(int)
    def _on_section_skipped(self, number: int) -> None:
        unit = self._reader.document.unit if self._reader.document else "Page"
        self.show_status(
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
        playing = state is PlayerState.PLAYING
        label = "Pause" if playing else "Resume" if state is PlayerState.PAUSED else "Play"
        self.play_action.setText(label)
        self.play_action.setToolTip(f"{label} (Space)")
        self.icons.bind(self.play_action, "pause" if playing else "play", role="on_accent", size=theme.ICON_LARGE)
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
        """Accept any local file; unsupported ones get an error message on drop."""
        if local_file_from_mime(event.mimeData()) is not None:
            event.acceptProposedAction()
            self.home.set_drag_active(True)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802 (Qt API name)
        """Remove the drop-area highlight."""
        self.home.set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 (Qt API name)
        """Add and open a book dropped anywhere on the window."""
        self.home.set_drag_active(False)
        path = local_file_from_mime(event.mimeData())
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
