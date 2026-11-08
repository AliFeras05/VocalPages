"""Home page: app name, tagline, a drop zone for PDF/EPUB files and a file-picker button.

Only structure lives here; all styling comes from the theme stylesheet via
object names and the ``dragActive`` property.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from vocalpages import APP_NAME, theme
from vocalpages.document import SUPPORTED_EXTENSIONS
from vocalpages.icons import IconSet

FILE_DIALOG_FILTER = "Books (*.pdf *.epub);;PDF files (*.pdf);;EPUB files (*.epub)"
TAGLINE = "Your PDFs and EPUBs, read aloud. Offline."
CONTENT_MAX_WIDTH = 640


def local_file_from_mime(mime: QMimeData) -> Path | None:
    """Return the first local file in dragged data (any type), or None.

    Unsupported types are accepted here on purpose, so the drop can be answered
    with a clear error instead of being silently refused.
    """
    for url in mime.urls():
        if url.isLocalFile():
            return Path(url.toLocalFile())
    return None


def is_supported(path: Path) -> bool:
    """True if the file extension is one the app can open."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


class ErrorBanner(QFrame):
    """An inline error: always an alert icon plus text, never color alone."""

    def __init__(self, icons: IconSet, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("errorBanner")
        self.setAccessibleName("Error")
        self.icon = QLabel(self)
        self.icon.setObjectName("errorIcon")
        self.icon.setAccessibleName("Error")
        icons.bind(self.icon, "circle-alert", role="error", size=theme.ICON_MEDIUM)
        self.text = QLabel(self)
        self.text.setObjectName("errorText")
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.space(2), theme.space(1.5), theme.space(2), theme.space(1.5))
        layout.setSpacing(theme.space(1.5))
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.text, 1)

    def show_message(self, message: str) -> None:
        """Show ``message`` with the alert icon."""
        self.text.setText(message)
        self.setAccessibleDescription(message)
        self.show()


class HomePage(QWidget):
    """Landing page. Emits ``choose_requested``; the main window opens files."""

    choose_requested = Signal()

    def __init__(self, icons: IconSet, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("homePage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        title = QLabel(APP_NAME, self)
        title.setObjectName("homeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline = QLabel(TAGLINE, self)
        tagline.setObjectName("homeTagline")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.drop_zone = QFrame(self)
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setMinimumHeight(theme.space(30))
        self.drop_zone.setAccessibleName("Drop zone for PDF and EPUB files")
        drop_icon = QLabel(self.drop_zone)
        drop_icon.setObjectName("dropIcon")
        icons.bind(drop_icon, "file-up", role="accent", size=theme.space(5))
        drop_title = QLabel("Drop a PDF or EPUB here", self.drop_zone)
        drop_title.setObjectName("dropTitle")
        drop_hint = QLabel("or", self.drop_zone)
        drop_hint.setObjectName("dropHint")

        self.choose_button = QPushButton("  Choose a file", self.drop_zone)  # leading gap after the icon
        self.choose_button.setObjectName("primaryButton")
        self.choose_button.setToolTip("Choose a PDF or EPUB file (Ctrl+O)")
        self.choose_button.setAccessibleName("Choose a file")
        self.choose_button.setCursor(Qt.CursorShape.PointingHandCursor)
        icons.bind(self.choose_button, "folder-open", role="on_accent", size=theme.ICON_MEDIUM)
        self.choose_button.clicked.connect(self.choose_requested)

        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setContentsMargins(theme.space(4), theme.space(4), theme.space(4), theme.space(4))
        drop_layout.setSpacing(theme.space(1.5))
        drop_layout.addStretch()
        for widget in (drop_icon, drop_title, drop_hint, self.choose_button):
            drop_layout.addWidget(widget, alignment=Qt.AlignmentFlag.AlignCenter)
        drop_layout.addStretch()

        self.error = ErrorBanner(icons, self)
        self.error.hide()

        column = QWidget(self)
        column.setMaximumWidth(CONTENT_MAX_WIDTH)
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(0)
        column_layout.addWidget(title)
        column_layout.addSpacing(theme.space(1))
        column_layout.addWidget(tagline)
        column_layout.addSpacing(theme.space(5))
        column_layout.addWidget(self.drop_zone)
        column_layout.addSpacing(theme.space(2))
        column_layout.addWidget(self.error)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.space(5), theme.space(5), theme.space(5), theme.space(5))
        layout.addStretch(2)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(column, 6)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(3)
        self.set_drag_active(False)

    def set_drag_active(self, active: bool) -> None:
        """Turn the drop zone the accent color while a file is dragged over the window."""
        self.drop_zone.setProperty("dragActive", "true" if active else "false")
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

    def show_error(self, message: str) -> None:
        """Show an inline error (alert icon plus text) under the drop zone."""
        self.error.show_message(message)

    def clear_error(self) -> None:
        """Hide the inline error."""
        self.error.hide()

    @property
    def error_label(self) -> QLabel:
        """The error text label (for tests and accessibility tools)."""
        return self.error.text
