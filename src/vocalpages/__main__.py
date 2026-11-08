"""GUI entry point: ``vocalpages [file.pdf]`` or ``python -m vocalpages``."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from vocalpages import APP_NAME


def main() -> int:
    """Start the Qt application and return its exit code."""
    level = os.environ.get("VOCALPAGES_LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING), format="%(levelname)s %(name)s: %(message)s"
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    from vocalpages import theme

    theme.load_fonts()
    app.setStyleSheet(theme.build_stylesheet(theme.LIGHT))

    from vocalpages.gui import MainWindow  # imported after QApplication exists

    window = MainWindow()
    window.show()
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        window.open_file(Path(args[0]))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
