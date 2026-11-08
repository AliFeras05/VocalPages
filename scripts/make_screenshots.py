"""Generate the README screenshots with a generated test book.

Runs Qt offscreen with a temporary library and a silent stub voice engine, so
no personal books, library data or TTS model are involved:

    python scripts/make_screenshots.py            # writes docs/screenshots/*.png
    python scripts/make_screenshots.py OUT_DIR
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
WINDOW_SIZE = (1280, 800)

# Original text written for these screenshots (no copyrighted material).
CHAPTER = [
    "The Lighthouse Keeper's Notebook",
    "Mara kept the notebook on the windowsill, where the morning light could find it before she did. "
    "Each entry began the same way: the date, the wind, and the colour of the sea. Some days the sea "
    "was the grey of old pewter. Other days it was so bright that she had to look away.",
    "She had been keeping the light for eleven years. In that time the ships had grown larger and the "
    "visitors fewer, but the work had not changed. Wind the clock. Trim the wick. Polish the glass "
    "until it held the whole horizon. At night the beam swept the water every twelve seconds, steady "
    "as a heartbeat.",
    "Dr. Ellery came on the supply boat each spring, carrying letters, seeds and a crate of oranges. "
    "He asked the same question every year: did she ever feel lonely out here? Mara always gave the "
    "same answer. \"Never,\" she said. \"The sea talks all day, and the light answers all night.\"",
    "That spring, though, the doctor brought something new: a small radio, wrapped in oilcloth. "
    "\"For the long evenings,\" he said. She turned it over in her hands for a long time before she "
    "switched it on. A voice was reading a story, slowly and clearly, the way her grandmother used to.",
]


class SilentEngine:
    """Stands in for Kokoro: loads instantly and 'speaks' silence."""

    is_loaded = True

    def load(self) -> None:
        """Nothing to load."""

    def synthesize(self, text: str, speed: float = 1.0) -> np.ndarray:
        """Return a short silence."""
        return np.zeros(2400, dtype=np.float32)


def make_test_book(path: Path) -> Path:
    """Write a 3-page PDF with title metadata and the sample chapter."""
    doc = pymupdf.open()
    for page_number in range(1, 4):
        page = doc.new_page(width=595, height=842)
        text = "\n\n".join(CHAPTER if page_number == 2 else CHAPTER[1:3])
        page.insert_textbox(pymupdf.Rect(72, 90, 523, 780), text, fontsize=11)
    doc.set_metadata({"title": "The Lighthouse Keeper's Notebook", "author": "VocalPages Sample"})
    doc.save(path)
    doc.close()
    return path


def make_second_book(path: Path) -> Path:
    """A second small PDF so the sidebar shows more than one book."""
    doc = pymupdf.open()
    for _ in range(12):
        doc.new_page().insert_textbox(pymupdf.Rect(72, 90, 523, 780), CHAPTER[3], fontsize=11)
    doc.set_metadata({"title": "Field Notes on Coastal Weather and Other Quiet Observations"})
    doc.save(path)
    doc.close()
    return path


def main(out_dir: Path) -> list[Path]:
    """Render home and reader screenshots in both themes into ``out_dir``."""
    app = QApplication.instance() or QApplication([])
    from vocalpages import theme
    from vocalpages.gui import MainWindow
    from vocalpages.library import Library

    theme.load_fonts()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="vocalpages-shots-") as tmp:
        tmp_path = Path(tmp)
        library = Library(tmp_path / "data", legacy_dirs=[])
        books = [make_second_book(tmp_path / "field-notes.pdf"), make_test_book(tmp_path / "lighthouse.pdf")]
        window = MainWindow(engine=SilentEngine(), library=library, settings_dir=tmp_path / "data")
        window.resize(*WINDOW_SIZE)
        window.show()
        for book in books:
            window.open_file(book)
        record = library.books()[1]
        library.save_position(record.id, 4, 0)
        window.open_file(books[1])
        window._reader.go_to_section(2)
        window._reader.set_document(window._reader.document, start_section=2, start_sentence=4)
        for name in ("light", "dark"):
            window.apply_theme(name)
            for page, show in (("home", window.show_home), ("reader", lambda: window.open_file(books[1]))):
                show()
                for _ in range(20):
                    app.processEvents()
                target = out_dir / f"{page}-{name}.png"
                window.grab().save(str(target))
                written.append(target)
        window.close()
        library.close()
    return written


if __name__ == "__main__":
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs" / "screenshots"
    for path in main(destination):
        print(path.relative_to(destination.parent) if path.is_relative_to(destination.parent) else path.name)
