"""Export dialog and the background worker that runs ``export.export_sections``."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QWidget,
)

from readaloud.document import Section
from readaloud.export import ExportCancelled, ExportError, Synthesizer, export_sections
from readaloud.tts import TtsError


class RangeDialog(QDialog):
    """Lets the user choose the whole document or a range of sections.

    ``unit`` is the section name shown to the user, e.g. "Page" or "Chapter".
    """

    def __init__(self, unit: str, count: int, current: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export audio")

        plural = f"{unit.lower()}s"
        self.all_radio = QRadioButton(f"All {plural} (1–{count})", self)
        self.range_radio = QRadioButton(plural.capitalize(), self)
        group = QButtonGroup(self)
        group.addButton(self.all_radio)
        group.addButton(self.range_radio)
        self.all_radio.setChecked(True)

        self.start_spin = QSpinBox(self)
        self.end_spin = QSpinBox(self)
        for spin in (self.start_spin, self.end_spin):
            spin.setRange(1, count)
            spin.setEnabled(False)
        self.start_spin.setValue(current)
        self.end_spin.setValue(count)
        self.start_spin.valueChanged.connect(lambda v: self.end_spin.setMinimum(v))
        self.range_radio.toggled.connect(self.start_spin.setEnabled)
        self.range_radio.toggled.connect(self.end_spin.setEnabled)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Choose file…")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QGridLayout(self)
        layout.addWidget(self.all_radio, 0, 0, 1, 4)
        layout.addWidget(self.range_radio, 1, 0)
        layout.addWidget(self.start_spin, 1, 1)
        layout.addWidget(QLabel("to", self), 1, 2)
        layout.addWidget(self.end_spin, 1, 3)
        layout.addWidget(buttons, 2, 0, 1, 4)

    def selected_range(self) -> tuple[int | None, int | None]:
        """Return (start, end); ``(None, None)`` means the whole document."""
        if self.all_radio.isChecked():
            return None, None
        return self.start_spin.value(), self.end_spin.value()


class ExportWorker(QObject):
    """Runs an export on a worker thread and reports progress with signals."""

    progress = Signal(int, int)
    finished = Signal(object)  # ExportResult
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        sections: Sequence[Section],
        numbers: Sequence[int],
        out_path: Path,
        engine: Synthesizer,
        speed: float,
    ) -> None:
        super().__init__()
        self._args = (list(sections), list(numbers), out_path, engine, speed)
        self._cancel = False

    def cancel(self) -> None:
        """Ask the export to stop after the current sentence (thread-safe flag)."""
        self._cancel = True

    @Slot()
    def run(self) -> None:
        """Do the export; emits exactly one of finished, failed or cancelled."""
        sections, numbers, out_path, engine, speed = self._args
        try:
            result = export_sections(
                sections,
                numbers,
                out_path,
                engine,
                speed,
                progress=self.progress.emit,
                is_cancelled=lambda: self._cancel,
            )
        except ExportCancelled:
            self.cancelled.emit()
        except (ExportError, TtsError, OSError) as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(result)
