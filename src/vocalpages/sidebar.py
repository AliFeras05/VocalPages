"""Library sidebar widget: Home button, the list of books with progress, and a footer.

Only structure lives here; all styling comes from the theme stylesheet via
object names and dynamic properties.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal, Slot
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vocalpages import theme
from vocalpages.icons import IconSet
from vocalpages.library import BookRecord

_ID_ROLE = Qt.ItemDataRole.UserRole


class ElidedLabel(QLabel):
    """A one-line label that shortens its text with an ellipsis to fit its width."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(1)
        self._elide()

    def full_text(self) -> str:
        """The text before eliding."""
        return self._full_text

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt API name)
        """Re-elide whenever the available width changes."""
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(self.width(), 1)
        self.setText(self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, width))


class BookRow(QWidget):
    """Sidebar row: title, a thin progress bar with its label, and a remove button."""

    remove_clicked = Signal()

    def __init__(self, record: BookRecord, icons: IconSet, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bookRow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.title = ElidedLabel(record.title, self)
        self.title.setObjectName("bookTitle")
        self.title.setToolTip(f"{record.title}\n{record.author}".strip())

        self.progress = QProgressBar(self)
        self.progress.setObjectName("bookProgress")
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Reading progress")
        self.progress_label = QLabel(self)
        self.progress_label.setObjectName("bookProgressLabel")
        self.set_progress(record)

        self.remove_button = QToolButton(self)
        self.remove_button.setObjectName("removeBookButton")
        self.remove_button.setToolTip("Remove from library")
        self.remove_button.setAccessibleName(f"Remove {record.title} from library")
        icons.bind(self.remove_button, "trash-2", size=theme.ICON_SMALL)
        self.remove_button.clicked.connect(self.remove_clicked)

        text = QVBoxLayout()
        text.setSpacing(theme.space(0.5))
        text.addWidget(self.title)
        text.addWidget(self.progress)
        text.addWidget(self.progress_label)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.space(1.5), theme.space(1), theme.space(0.5), theme.space(1))
        layout.setSpacing(theme.space(1))
        layout.addLayout(text, 1)
        layout.addWidget(self.remove_button, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_progress(self, record: BookRecord) -> None:
        """Show ``record``'s position as a bar and a short label."""
        self.progress.setRange(0, max(record.section_count, 1))
        self.progress.setValue(min(record.section, record.section_count))
        self.progress_label.setText(record.progress_text)
        self.progress.setAccessibleDescription(record.progress_text)

    def set_current(self, current: bool) -> None:
        """Mark this row as the open book (styled with the accent color)."""
        self.title.setProperty("current", "true" if current else "false")
        self.title.style().unpolish(self.title)
        self.title.style().polish(self.title)


class LibrarySidebar(QWidget):
    """Persistent sidebar. Emits signals only; the main window does the work."""

    home_requested = Signal()
    book_selected = Signal(str)  # book id
    remove_requested = Signal(str)  # book id

    def __init__(self, icons: IconSet, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setMinimumWidth(theme.SIDEBAR_WIDTH - theme.space(6))
        self._icons = icons

        self.home_button = QToolButton(self)
        self.home_button.setObjectName("homeButton")
        self.home_button.setToolTip("Home")
        self.home_button.setAccessibleName("Home")
        icons.bind(self.home_button, "house")
        self.home_button.clicked.connect(self.home_requested)

        heading = QLabel("LIBRARY", self)
        heading.setObjectName("sidebarHeading")

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(heading)
        top.addStretch()
        top.addWidget(self.home_button)

        self.list = QListWidget(self)
        self.list.setObjectName("bookList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        self.list.itemClicked.connect(lambda item: self.book_selected.emit(item.data(_ID_ROLE)))
        self.list.setAccessibleName("Library")

        self.empty_label = QLabel("No books yet. Add a PDF or EPUB from the home page.", self)
        self.empty_label.setObjectName("emptyLibrary")
        self.empty_label.setWordWrap(True)

        self.footer = QWidget(self)
        self.footer.setObjectName("sidebarFooter")
        self.footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.footer.setFixedHeight(theme.BOTTOM_BAR_HEIGHT)
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(theme.space(2), theme.space(1), theme.space(1.5), theme.space(1))
        self.footer_layout.setSpacing(theme.space(1))

        body = QVBoxLayout()
        body.setContentsMargins(theme.space(2), theme.space(2), theme.space(1), theme.space(1))
        body.setSpacing(theme.space(1))
        body.addLayout(top)
        body.addWidget(self.empty_label)
        body.addWidget(self.list, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(body, 1)
        layout.addWidget(self.footer)
        self._rows: dict[str, BookRow] = {}
        self._current: str | None = None

    def add_footer_widget(self, widget: QWidget, stretch: int = 0) -> None:
        """Place a widget (status text, theme toggle) in the sidebar footer, left to right."""
        self.footer_layout.addWidget(widget, stretch)

    def set_books(self, books: list[BookRecord], current_id: str | None = None) -> None:
        """Replace the list with ``books`` and mark ``current_id`` as the open book."""
        self.list.clear()
        self._rows.clear()
        for record in books:
            item = QListWidgetItem(self.list)
            item.setData(_ID_ROLE, record.id)
            row = BookRow(record, self._icons, self.list)
            row.remove_clicked.connect(lambda book_id=record.id: self.remove_requested.emit(book_id))
            item.setSizeHint(row.sizeHint())
            self.list.setItemWidget(item, row)
            self._rows[record.id] = row
        self.empty_label.setVisible(not books)
        self.select(current_id)

    def update_progress(self, record: BookRecord) -> None:
        """Refresh one book's progress bar and label in place."""
        row = self._rows.get(record.id)
        if row is not None:
            row.set_progress(record)

    def select(self, book_id: str | None) -> None:
        """Highlight the open book, or clear the selection."""
        self._current = book_id
        self.list.clearSelection()
        for i in range(self.list.count()):
            item = self.list.item(i)
            is_current = item.data(_ID_ROLE) == book_id
            item.setSelected(is_current)
            row = self._rows.get(item.data(_ID_ROLE))
            if row is not None:
                row.set_current(is_current)

    @Slot(QPoint)
    def _show_context_menu(self, pos: QPoint) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        remove = menu.addAction("Remove from library…")
        self._icons.bind(remove, "trash-2", size=theme.ICON_SMALL)
        if menu.exec(self.list.viewport().mapToGlobal(pos)) is remove:
            self.remove_requested.emit(item.data(_ID_ROLE))
