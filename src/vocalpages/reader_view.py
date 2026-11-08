"""Reading pane: centered text column, comfortable line height, smooth sentence highlight."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QColor, QResizeEvent, QTextBlockFormat, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QFrame, QTextEdit, QWidget

from vocalpages import theme

SCROLL_DURATION_MS = 260


class ReaderView(QTextEdit):
    """Read-only text view sized to about ``READING_MAX_CHARS`` characters per line."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("readerText")
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAccessibleName("Book text")
        self.document().setDocumentMargin(0)
        self._palette = theme.LIGHT
        self._highlight: tuple[int, int] | None = None
        self._scroll = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._scroll.setDuration(SCROLL_DURATION_MS)
        self._scroll.setEasingCurve(QEasingCurve.Type.OutCubic)

    def set_palette(self, palette: theme.Palette) -> None:
        """Use ``palette`` for the sentence highlight (re-applied immediately)."""
        self._palette = palette
        if self._highlight is not None:
            self.highlight(*self._highlight, scroll=False)

    def set_section_text(self, text: str) -> None:
        """Show ``text`` with the reading line height. Character offsets match ``text``."""
        self._scroll.stop()
        self._highlight = None
        self.setExtraSelections([])
        self.setPlainText(text)
        block_format = QTextBlockFormat()
        block_format.setLineHeight(self._line_height_percent(), QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.mergeBlockFormat(block_format)
        self.verticalScrollBar().setValue(0)
        self._update_margins()

    def _line_height_percent(self) -> float:
        """Percentage of the font's natural line spacing that gives READING_LINE_HEIGHT x font size."""
        metrics = self.fontMetrics()
        font_px = self.font().pixelSize() if self.font().pixelSize() > 0 else metrics.height()
        return 100 * theme.READING_LINE_HEIGHT * font_px / max(metrics.lineSpacing(), 1)

    def clear_highlight(self) -> None:
        """Remove the sentence highlight."""
        self._highlight = None
        self.setExtraSelections([])

    def highlight(self, start: int, end: int, scroll: bool = True) -> None:
        """Highlight characters ``start``..``end`` and smoothly bring them into view."""
        self._highlight = (start, end)
        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format = QTextCharFormat()
        selection.format.setBackground(QColor(self._palette.highlight))
        selection.format.setForeground(QColor(self._palette.highlight_text))
        self.setExtraSelections([selection])
        if scroll:
            self._scroll_to(start, end)

    def _scroll_to(self, start: int, end: int) -> None:
        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        top = self.cursorRect(cursor).top()
        cursor.setPosition(end)
        bottom = self.cursorRect(cursor).bottom()
        viewport_height = self.viewport().height()
        comfort_top, comfort_bottom = viewport_height * 0.15, viewport_height * 0.75
        if comfort_top <= top and bottom <= comfort_bottom:
            return  # already comfortably visible
        bar = self.verticalScrollBar()
        target = bar.value() + top - int(viewport_height * 0.3)
        target = max(bar.minimum(), min(bar.maximum(), target))
        self._scroll.stop()
        self._scroll.setStartValue(bar.value())
        self._scroll.setEndValue(target)
        self._scroll.start()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt API name)
        """Keep the text column centered at about 70 characters wide."""
        super().resizeEvent(event)
        self._update_margins()

    def _update_margins(self) -> None:
        measure = self.fontMetrics().averageCharWidth() * theme.READING_MAX_CHARS
        available = self.width() - self.verticalScrollBar().sizeHint().width()
        side = max(theme.space(4), (available - measure) // 2)
        self.setViewportMargins(side, theme.space(4), side, theme.space(4))
