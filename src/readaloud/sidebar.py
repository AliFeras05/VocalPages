"""Library sidebar widget: a Home button and the list of books with progress."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from readaloud.library import BookRecord

_ID_ROLE = Qt.ItemDataRole.UserRole


class _BookRow(QWidget):
    """Two-line row: title on top, progress below, with a small remove button."""

    remove_clicked = Signal()

    def __init__(self, record: BookRecord, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = QLabel(record.title, self)
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        self.title.setWordWrap(True)
        self.progress = QLabel(record.progress_text, self)
        self.progress.setStyleSheet("color: palette(placeholder-text);")

        remove = QToolButton(self)
        remove.setText("✕")
        remove.setAutoRaise(True)
        remove.setToolTip("Remove from library (your file is not deleted)")
        remove.clicked.connect(self.remove_clicked)

        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(self.title)
        text.addWidget(self.progress)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 4, 6)
        layout.addLayout(text, 1)
        layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)


class LibrarySidebar(QWidget):
    """Persistent sidebar. Emits signals only; the main window does the work."""

    home_requested = Signal()
    book_selected = Signal(str)  # book id
    remove_requested = Signal(str)  # book id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.home_button = QPushButton("⌂  Home", self)
        self.home_button.setMinimumHeight(34)
        self.home_button.clicked.connect(self.home_requested)

        heading = QLabel("Library", self)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)

        self.list = QListWidget(self)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        self.list.itemClicked.connect(lambda item: self.book_selected.emit(item.data(_ID_ROLE)))

        self.empty_label = QLabel("No books yet.", self)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.empty_label.setStyleSheet("color: palette(placeholder-text);")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.home_button)
        layout.addSpacing(8)
        layout.addWidget(heading)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.list, 1)
        self._rows: dict[str, _BookRow] = {}

    def set_books(self, books: list[BookRecord], current_id: str | None = None) -> None:
        """Replace the list with ``books`` and select ``current_id`` if given."""
        self.list.clear()
        self._rows.clear()
        for record in books:
            item = QListWidgetItem(self.list)
            item.setData(_ID_ROLE, record.id)
            item.setToolTip(f"{record.title}\n{record.author}".strip())
            row = _BookRow(record, self.list)
            row.remove_clicked.connect(lambda book_id=record.id: self.remove_requested.emit(book_id))
            item.setSizeHint(row.sizeHint())
            self.list.setItemWidget(item, row)
            self._rows[record.id] = row
            if record.id == current_id:
                item.setSelected(True)
        self.empty_label.setVisible(not books)

    def update_progress(self, book_id: str, text: str) -> None:
        """Update one book's progress label in place."""
        row = self._rows.get(book_id)
        if row is not None:
            row.progress.setText(text)

    def select(self, book_id: str | None) -> None:
        """Highlight the open book, or clear the selection."""
        self.list.clearSelection()
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(_ID_ROLE) == book_id:
                item.setSelected(True)

    @Slot(QPoint)
    def _show_context_menu(self, pos: QPoint) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        remove = menu.addAction("Remove from library…")
        if menu.exec(self.list.viewport().mapToGlobal(pos)) is remove:
            self.remove_requested.emit(item.data(_ID_ROLE))
