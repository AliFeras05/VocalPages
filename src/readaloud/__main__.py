"""GUI entry point: ``readaloud [file.pdf]`` or ``python -m readaloud``."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from readaloud import APP_NAME


def main() -> int:
    """Start the Qt application and return its exit code."""
    level = os.environ.get("READALOUD_LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING), format="%(levelname)s %(name)s: %(message)s"
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    from readaloud.gui import MainWindow  # imported after QApplication exists

    window = MainWindow()
    window.show()
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        window.open_pdf(Path(args[0]))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
