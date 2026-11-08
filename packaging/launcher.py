"""Entry script for the frozen (PyInstaller) app bundle."""

import multiprocessing
import sys

from readaloud.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
