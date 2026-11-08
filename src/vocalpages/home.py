"""Home page: app name, a drop area for PDF/EPUB files and a file-picker button."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from vocalpages import APP_NAME
from vocalpages.document import SUPPORTED_EXTENSIONS

FILE_DIALOG_FILTER = "Books (*.pdf *.epub);;PDF files (*.pdf);;EPUB files (*.epub)"


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


class HomePage(QWidget):
    """Landing page. Emits ``choose_requested``; the main window opens files."""

    choose_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        name = QLabel(APP_NAME, self)
        font = name.font()
        font.setPointSize(font.pointSize() + 26)
        font.setBold(True)
        name.setFont(font)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)

        tagline = QLabel("Listen to your PDFs and EPUBs, read aloud offline.", self)
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline.setStyleSheet("color: palette(placeholder-text);")

        self.drop_area = QFrame(self)
        self.drop_area.setObjectName("dropArea")
        self.drop_area.setMinimumSize(420, 220)
        drop_title = QLabel("Drop a PDF or EPUB here", self.drop_area)
        drop_font = drop_title.font()
        drop_font.setPointSize(drop_font.pointSize() + 6)
        drop_title.setFont(drop_font)
        self.choose_button = QPushButton("Choose a file", self.drop_area)
        self.choose_button.setMinimumHeight(36)
        self.choose_button.clicked.connect(self.choose_requested)
        drop_layout = QVBoxLayout(self.drop_area)
        drop_layout.addStretch()
        drop_layout.addWidget(drop_title, alignment=Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(QLabel("or", self.drop_area), alignment=Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(self.choose_button, alignment=Qt.AlignmentFlag.AlignCenter)
        drop_layout.addStretch()

        self.error_label = QLabel(self)
        self.error_label.setObjectName("homeError")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #e5534b; font-weight: 600;")
        self.error_label.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(2)
        layout.addWidget(name)
        layout.addWidget(tagline)
        layout.addSpacing(28)
        layout.addWidget(self.drop_area, 3)
        layout.addSpacing(12)
        layout.addWidget(self.error_label)
        layout.addStretch(2)
        self.set_drag_active(False)

    def set_drag_active(self, active: bool) -> None:
        """Highlight the drop area while a file is dragged over the window."""
        border = "palette(highlight)" if active else "palette(mid)"
        self.drop_area.setStyleSheet(
            f"#dropArea {{ border: 2px dashed {border}; border-radius: 16px; }}"
        )

    def show_error(self, message: str) -> None:
        """Show an inline error under the drop area."""
        self.error_label.setText(message)
        self.error_label.show()

    def clear_error(self) -> None:
        """Hide the inline error."""
        self.error_label.clear()
        self.error_label.hide()
